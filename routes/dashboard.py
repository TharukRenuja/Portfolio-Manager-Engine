from flask import Blueprint, render_template, request, session, redirect, url_for
from datetime import datetime, timedelta
from firebase_admin import firestore
from core import database
from core.shared import login_required, get_settings, get_ui_settings
from core.analytics_aggregator import get_analytics_summary
from google.cloud.firestore import FieldFilter

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/')
@login_required
def dashboard_home():
    # Get pre-aggregated analytics summary (much faster!)
    analytics_summary = get_analytics_summary()
    
    if analytics_summary:
        total_analytics = analytics_summary.get('total_views', 0)
        monthly_count = analytics_summary.get('monthly_views', 0)
        yearly_count = analytics_summary.get('yearly_views', 0)
    else:
        # Fallback to real-time calculation if summary doesn't exist
        total_analytics = database.db.collection('analytics').count().get()[0][0].value if database.db else 0
        monthly_count = 0
        yearly_count = 0
    
    # Aggregate analytics by day for the last 7 days
    now = datetime.now()
    chart_labels = []
    chart_views = []
    
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        # Count analytics for this day
        day_count = 0
        if database.db:
            day_analytics = database.db.collection('analytics').where(filter=FieldFilter('timestamp', '>=', day_start)).where(filter=FieldFilter('timestamp', '<=', day_end)).get()
            day_count = len(list(day_analytics))
        
        chart_labels.append(day.strftime('%a'))
        chart_views.append(day_count)
    
    # Calculate bandwidth estimate (views * average page size in KB)
    chart_bandwidth = [v * 0.5 for v in chart_views]  # Assume 500KB per view
    
    # Get deployment health from vault
    deployments_health = []
    offline_count = 0
    if database.db:
        vault_items = database.db.collection('vault').where(filter=FieldFilter('category', '==', 'deployment')).get()
        for item in vault_items:
            data = item.to_dict()
            deployments_health.append({
                'name': data.get('name', 'Unknown'),
                'last_status': data.get('last_status', 'unknown')
            })
            if data.get('last_status') == 'offline':
                offline_count += 1
    
    # Get downloads data
    downloads = database.db.collection('downloads').get() if database.db else []
    downloads_list = list(downloads)
    download_hits = sum([d.to_dict().get('downloads_count', 0) for d in downloads_list])
    
    stats = {
        'projects': database.db.collection('projects').count().get()[0][0].value if database.db else 0,
        'blogs': database.db.collection('blog').count().get()[0][0].value if database.db else 0,
        'messages': len([m for m in database.db.collection('messages').where(filter=FieldFilter('is_read', '==', False)).get() if not m.to_dict().get('is_system', False)]) if database.db else 0,
        'analytics': total_analytics,
        'downloads_count': len(downloads_list),
        'download_hits': download_hits,
        'offline_count': offline_count,
        'deployments_health': deployments_health,
        'chart_data': {
            'labels': chart_labels,
            'views': chart_views,
            'bandwidth': [round(v * 1.8 + download_hits * 0.05 + 2.1, 1) for v in chart_views]
        },# Additional fields for dashboard
        'career_count': database.db.collection('career').count().get()[0][0].value if database.db else 0,
        'vault_count': database.db.collection('vault').count().get()[0][0].value if database.db else 0,
        'blogs_count': database.db.collection('blog').count().get()[0][0].value if database.db else 0,
        'total_messages': database.db.collection('messages').where(filter=FieldFilter('is_system', '==', False)).count().get()[0][0].value if database.db else 0,
        'popular_content': [],
        'total_views': total_analytics,
        'monthly_views': monthly_count,
        'yearly_views': yearly_count
    }
    
    # Get top performing content
    if database.db:
        blogs = database.db.collection('blog').order_by('views', direction=firestore.Query.DESCENDING).limit(5).get()
        for blog in blogs:
            data = blog.to_dict()
            stats['popular_content'].append({
                'title': data.get('title', 'Untitled'),
                'type': 'Blog',
                'views': data.get('views', 0)
            })
    
    return render_template('dashboard.html', stats=stats)

@dashboard_bp.app_context_processor
def inject_globals():
    notifications = []
    valid_notifs = []
    if database.db:
        # Unified Center: Show UNREAD system alerts AND UNREAD human messages
        # Fetch all messages and filter in Python to avoid multi-field index requirement
        all_msgs = database.db.collection('messages').get()
        
        for m in all_msgs:
            d = m.to_dict()
            if d.get('is_read', False): continue
            
            is_system = d.get('is_system', False)
            msg_time = d.get('timestamp')
            # Handle both datetime objects and strings from restored backups
            if msg_time:
                if isinstance(msg_time, str):
                    try:
                        from datetime import datetime as dt
                        msg_time = dt.fromisoformat(msg_time.replace('Z', '+00:00'))
                    except:
                        msg_time = None
                if msg_time and hasattr(msg_time, 'replace'):
                    msg_time = msg_time.replace(tzinfo=None)
            
            # Determine best link for redirection
            link = url_for('tools.notification_center')
            subject = d.get('subject', '')
            if 'Domain Alert' in subject:
                link = url_for('tools.domain_list')
            elif 'Outage' in subject:
                link = url_for('tools.vault_list')
            elif not is_system:
                link = url_for('tools.messages_list')

            valid_notifs.append({
                'id': m.id, 
                'type': 'alert' if is_system else 'message',
                'title': subject if is_system else f"New message from {d.get('name')}",
                'subtitle': d.get('message', '')[:60] + ("..." if len(d.get('message', '')) > 60 else ""),
                'time': msg_time or datetime.now(),
                'timestamp': msg_time or datetime.now(), # Keep for sorting
                'icon': 'alert-triangle' if (is_system and d.get('alert_type') == 'critical') else ('bell' if is_system else 'mail'),
                'link': link,
                'priority': 'high' if (is_system and d.get('alert_type') == 'critical') else 'normal'
            })
        
    # Sort by timestamp descending
    valid_notifs.sort(key=lambda x: x.get('timestamp') or datetime.min, reverse=True)
    notifications = valid_notifs[:5]

    # Fetch feature flags with safety check for uninitialized DB
    features = {
        'blog': True, 'projects': True, 'career': True, 'links': True, 
        'vault': True, 'monitor': True, 'resumes': True, 'downloads': True
    }
    
    if database.db:
        features_doc = database.db.collection('settings').document('features').get()
        if features_doc.exists:
            features = features_doc.to_dict()

    return {
        'now': datetime.now(),
        'settings': get_settings(),
        'ui': get_ui_settings(),
        'notifications': notifications,
        'features': features
    }
