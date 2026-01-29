from flask import Flask, redirect, url_for, request
import os
from dotenv import load_dotenv
from core.extensions import bcrypt, scheduler, cors
from core import database
import requests
from datetime import datetime
from flask_caching import Cache

# Import Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.cms import cms_bp
from routes.admin import admin_bp
from routes.tools import tools_bp
from routes.api import api_bp
from core.shared import get_settings, send_push_notification, init_cache
from google.cloud.firestore import FieldFilter

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-key-123')

# Configure Caching
app.config['CACHE_TYPE'] = 'SimpleCache'  # Use Redis in production
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 minutes
cache = Cache(app)

# Initialize cache in shared module
init_cache(cache)

# Initialize Extensions
bcrypt.init_app(app)
cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
scheduler.init_app(app)
scheduler.start()

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(cms_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(tools_bp)
app.register_blueprint(api_bp)

# Global Jinja Filters & Globals
def format_number(value):
    try:
        value = float(value)
        if value < 1000: return f"{int(value)}"
        elif value < 1000000: return f"{value/1000:.1f}K"
        else: return f"{value/1000000:.1f}M"
    except: return value

app.jinja_env.filters['format_number'] = format_number 
app.jinja_env.globals.update(hasattr=hasattr)

@app.before_request
def bootstrap_check():
    # Global Maintenance Mode Check for APIs
    if request.path.startswith('/api/') and request.path not in ['/api/health', '/api/push/public-key']:
        # Bypass for authenticated users (internal dashboard checks)
        from flask import session, jsonify
        if not session.get('user'):
            if get_settings().get('maintenance_mode'):
                return jsonify({'status': 'maintenance', 'message': 'Scheduled maintenance in progress.'}), 503

    # Setup Check
    if request.path.startswith('/static') or request.path in ['/setup', '/login', '/logout', '/login/mfa']:
        return
    try:
        print(f"🔍 Bootstrap check for path: {request.path}")
        print(f"🔍 Database object exists: {database.db is not None}")
        print(f"🔍 Firebase initialized: {database.firebase_initialized}")
        
        if database.db:
            users = database.db.collection('users').limit(1).get()
            print(f"🔍 Users query result: {len(users) if users else 0} users found")
            if not users: 
                print("ℹ️  Redirecting to setup: No users found in DB")
                return redirect(url_for('auth.setup'))
            else:
                print(f"✅ Bootstrap check passed - Found user(s) in database")
        else: 
            print("ℹ️  Redirecting to setup: Database not initialized")
            return redirect(url_for('auth.setup'))
    except Exception as e: 
        print(f"⚠️  Bootstrap check error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return redirect(url_for('auth.setup'))

# --- Background Jobs (Maintained in main.py for state access) ---
@scheduler.task('interval', id='update_analytics_aggregate', minutes=5, misfire_grace_time=300)
def update_analytics_aggregate():
    with app.app_context():
        if not database.db: return
        from core.analytics_aggregator import aggregate_analytics
        aggregate_analytics()
        print(f"[{datetime.now()}] Background Job: Analytics aggregates updated")

@scheduler.task('interval', id='check_services_health', minutes=30, misfire_grace_time=900)
def check_services_health():
    with app.app_context():
        if not database.db: return
        
        # 1. Vault Deployments
        for d in database.db.collection('vault').where(filter=FieldFilter('category', '==', 'deployment')).get():
            data = d.to_dict()
            url = data.get('url', '')
            if not url.startswith('http'): url = 'https://' + url
            try:
                status = 'online' if requests.head(url, timeout=10).status_code < 400 else 'offline'
            except:
                status = 'offline'
            
            database.db.collection('vault').document(d.id).update({'last_check': datetime.now(), 'last_status': status})
            if status == 'offline':
                subject = f"🚨 Outage: {data.get('name')}"
                msg = f"Unreachable: {url}"
                
                # Avoid duplicate alerts - check if one exists in last 24h
                from datetime import timedelta
                threshold = datetime.now() - timedelta(hours=24)
                recent_msgs = database.db.collection('messages').where('subject', '==', subject).get()
                already_sent = any(m.to_dict().get('timestamp').replace(tzinfo=None) > threshold for m in recent_msgs if m.to_dict().get('timestamp'))
                
                if not already_sent:
                    send_push_notification(subject, msg)
                    database.db.collection('messages').add({
                        'name': 'System Monitor',
                        'subject': subject,
                        'message': msg,
                        'timestamp': datetime.now(),
                        'is_read': False,
                        'is_system': True,
                        'alert_type': 'critical'
                    })

        # 2. Domain Expiries
        print(f"[{datetime.now()}] Background Job: Checking domain expiries...")
        for d in database.db.collection('domains').get():
            data = d.to_dict()
            expiry_str = data.get('expiry_date')
            if expiry_str:
                try:
                    # Handle both YYYY-MM-DD and potentially other formats if needed
                    expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
                    days = (expiry_date - datetime.now()).days + 1 # +1 to round up correctly
                    print(f"--- Domain: {data.get('domain_name')} | Expires in: {days} days")
                    
                    if days <= 30:
                        alert_type = 'critical' if days <= 7 else 'warning'
                        subject = f"{'🚨' if days <= 7 else '📅'} Domain Alert: {data.get('domain_name')}"
                        msg = f"Expires in {days} days ({expiry_str})."
                        
                        # Avoid duplicate alerts - check if one exists in last 24h
                        from datetime import timedelta
                        threshold = datetime.now() - timedelta(hours=24)
                        # Fetch messages with same subject and check timestamp manually to avoid composite index error
                        recent_msgs = database.db.collection('messages').where(filter=FieldFilter('subject', '==', subject)).get()
                        already_sent = any(m.to_dict().get('timestamp').replace(tzinfo=None) > threshold for m in recent_msgs if m.to_dict().get('timestamp'))
                        
                        if not already_sent:
                            print(f"!!! Sending Alert for {data.get('domain_name')}")
                            send_push_notification(subject, msg)
                            database.db.collection('messages').add({
                                'name': 'System Monitor',
                                'subject': subject,
                                'message': msg,
                                'timestamp': datetime.now(),
                                'is_read': False,
                                'is_system': True,
                                'alert_type': alert_type
                            })
                except Exception as e:
                    print(f"!!! Error parsing domain {data.get('domain_name')}: {e}")
                    pass

if __name__ == '__main__':
    app.run(debug=True)
