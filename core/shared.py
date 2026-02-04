from functools import wraps
from flask import session, flash, redirect, url_for, request, jsonify
from datetime import datetime
import requests
from core import database
import os

def sanitize_redis_url(url):
    if not url:
        return url
    
    url = url.strip()
    
    # Handle Upstash/Redis copy-paste CLI prefixes
    tls_mode = False
    if " --tls" in url:
        tls_mode = True
        
    # Remove common CLI wrappers
    prefixes = ["redis-cli -u ", "redis-cli --tls -u ", "redis-cli "]
    for p in prefixes:
        if url.startswith(p):
            url = url[len(p):]
            break
            
    # Remove leading '-u ' if it somehow remained
    if url.startswith("-u "):
        url = url[3:]

    # Force rediss:// if TLS was indicated or it's a known secure provider (Upstash)
    is_secure = tls_mode or "upstash.io" in url.lower()
    
    if is_secure and url.startswith("redis://"):
        url = url.replace("redis://", "rediss://", 1)
    elif is_secure and not url.startswith("rediss://") and "://" not in url:
        # If it's just host:port, prepend rediss://
        url = "rediss://" + url
    elif not is_secure and not url.startswith("redis://") and "://" not in url:
        # Default to redis:// if no protocol
        url = "redis://" + url
        
    return url.strip()

from functools import wraps
from flask import session, flash, redirect, url_for, request, jsonify
from datetime import datetime
import requests
from core import database
from core.extensions import cache

# Global cache instance is now imported from extensions

@cache.memoize(timeout=300)
def _get_cached_settings():
    if database.db is None: 
        return {}
    doc = database.db.collection('settings').document('website').get()
    data = doc.to_dict() if doc.exists else {}
    if not data:
        # Don't return empty cached data if we expect it to be there
        # This is a bit tricky with memoize. Let's just log it.
        print("⚠️ [shared.py] get_settings: 'website' doc is EMPTY in Firestore")
    else:
        print(f"✅ [shared.py] get_settings: Loaded {len(data)} fields")
    return data

def get_settings():
    if database.db is None:
        return {}
    if cache:
        return _get_cached_settings()
    doc = database.db.collection('settings').document('website').get()
    return doc.to_dict() if doc.exists else {}

@cache.memoize(timeout=300)
def _get_cached_seo():
    if database.db is None: return {}
    doc = database.db.collection('settings').document('seo').get()
    return doc.to_dict() if doc.exists else {}

def get_seo():
    if database.db is None:
        return {}
    if cache:
        return _get_cached_seo()
    doc = database.db.collection('settings').document('seo').get()
    return doc.to_dict() if doc.exists else {}

@cache.memoize(timeout=300)
def _get_cached_ui():
    if database.db is None: return {'primary_color': '#FFD700', 'theme': 'dark'}
    doc = database.db.collection('settings').document('ui').get()
    return doc.to_dict() if doc.exists else {'primary_color': '#FFD700', 'theme': 'dark'}

def get_ui_settings():
    if database.db is None:
        return {'primary_color': '#FFD700', 'theme': 'dark'}
    if cache:
        return _get_cached_ui()
    doc = database.db.collection('settings').document('ui').get()
    return doc.to_dict() if doc.exists else {'primary_color': '#FFD700', 'theme': 'dark'}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('You need to log in first.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('You need to log in first.', 'warning')
            return redirect(url_for('auth.login'))
        if not session['user'].get('is_admin'):
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('dashboard.dashboard_home'))
        return f(*args, **kwargs)
    return decorated_function

def root_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            flash('You need to log in first.', 'warning')
            return redirect(url_for('auth.login'))
        if not session['user'].get('is_root'):
            flash('Root Admin privileges required.', 'danger')
            return redirect(url_for('dashboard.dashboard_home'))
        return f(*args, **kwargs)
    return decorated_function

def maintenance_guard(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        settings = get_settings()
        if settings.get('maintenance_mode'):
            return jsonify({
                'status': 'maintenance', 
                'message': 'This portfolio is undergoing scheduled maintenance. Please check back later.'
            }), 503
        return f(*args, **kwargs)
    return decorated_function

def track_view(item_type, item_id, title):
    if database.db:
        database.db.collection('analytics').add({
            'item_type': item_type,
            'item_id': item_id,
            'title': title,
            'timestamp': datetime.now(),
            'user_agent': request.headers.get('User-Agent'),
            'ip': request.remote_addr
        })

def trigger_rebuild():
    """Triggers external frontend build webhooks if configured."""
    settings = get_settings()
    webhook_url = settings.get('rebuild_webhook_url')
    if webhook_url:
        try:
            requests.post(webhook_url, json={'triggered_by': 'Portfolio Manager CMS'})
        except:
            pass

def send_push_notification(title, message):
    """Sends a push notification to all subscribers."""
    import os, json
    try:
        from pywebpush import webpush, WebPushException
        private_key = os.getenv('VAPID_PRIVATE_KEY')
        if not private_key or not database.db: return

        settings = get_settings()
        icon = settings.get('favicon_url', '')
        payload = json.dumps({'title': title, 'message': message, 'icon': icon})
        claims = {"sub": f"mailto:{os.getenv('ADMIN_EMAIL', 'admin@example.com')}"}
        
        for sub_doc in database.db.collection('push_subs').get():
            sub = sub_doc.to_dict().get('subscription')
            if not sub: continue
            try:
                webpush(sub, data=payload, vapid_private_key=private_key, vapid_claims=claims)
            except WebPushException as ex:
                if ex.response and ex.response.status_code == 410:
                    database.db.collection('push_subs').document(sub_doc.id).delete()
            except: pass
    except ImportError: pass
