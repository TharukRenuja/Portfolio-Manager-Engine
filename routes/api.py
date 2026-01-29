from flask import Blueprint, jsonify, request, make_response
from core import database
from core.shared import get_settings, get_seo, maintenance_guard, admin_required, login_required
from google.cloud.firestore import FieldFilter
from datetime import datetime
import os
import requests
import json

api_bp = Blueprint('api', __name__)

# --- Public API Endpoints ---

@api_bp.route('/api/settings', methods=['GET'])
@maintenance_guard
def get_api_settings():
    return jsonify(get_settings())

@api_bp.route('/api/seo', methods=['GET'])
@maintenance_guard
def get_api_seo():
    seo = get_seo()
    settings = get_settings()
    json_ld = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": settings.get('site_name'),
        "jobTitle": "Software Developer",
        "url": seo.get('canonical_url'),
        "sameAs": [settings.get('github_url'), settings.get('linkedin_url'), settings.get('twitter_url')],
        "description": settings.get('site_bio')
    }
    json_ld["sameAs"] = [s for s in json_ld["sameAs"] if s]
    seo['json_ld'] = json_ld
    return jsonify(seo)

@api_bp.route('/api/sitemap', methods=['GET'])
@maintenance_guard
def get_sitemap():
    blogs = database.db.collection('blog').where(filter=FieldFilter('status', '==', 'published')).get()
    projects = database.db.collection('projects').get()
    seo = get_seo()
    base_url = seo.get('canonical_url', '').rstrip('/')
    urls = []
    def make_url(path, priority, freq, mod=None):
        full_path = f"{base_url}{path}" if base_url else path
        item = {'path': full_path, 'priority': priority, 'changefreq': freq}
        if mod: item['lastmod'] = mod
        return item
    urls.append(make_url('/', 1.0, 'daily'))
    urls.append(make_url('/blog', 0.8, 'weekly'))
    urls.append(make_url('/projects', 0.8, 'weekly'))
    urls.append(make_url('/experience', 0.7, 'monthly'))
    for blog in blogs:
        b = blog.to_dict()
        urls.append(make_url(f"/blog/{b.get('permalink')}", 0.6, 'monthly', b.get('date')))
    for project in projects:
        p = project.to_dict()
        urls.append(make_url(f"/project/{p.get('permalink')}", 0.6, 'monthly', p.get('date')))
    return jsonify({'urls': urls})

@api_bp.route('/api/blog', methods=['GET'])
@maintenance_guard
def get_blog_api():
    # Fetch published blogs and sort in Python to avoid composite index requirement
    blogs = database.db.collection('blog').where(filter=FieldFilter('status', '==', 'published')).get()
    # Sort by date descending in Python
    sorted_blogs = sorted(blogs, key=lambda b: b.to_dict().get('date', ''), reverse=True)
    return jsonify({b.id: b.to_dict() for b in sorted_blogs})

@api_bp.route('/api/projects', methods=['GET'])
@maintenance_guard
def get_projects_api():
    # Fetch all projects and sort in Python to avoid index requirement
    projects = database.db.collection('projects').get()
    # Sort by date descending in Python
    sorted_projects = sorted(projects, key=lambda p: p.to_dict().get('date', ''), reverse=True)
    return jsonify({p.id: p.to_dict() for p in sorted_projects})

@api_bp.route('/api/downloads', methods=['GET'])
@maintenance_guard
def get_downloads_api():
    downloads = database.db.collection('downloads').get()
    return jsonify({d.id: d.to_dict() for d in downloads})

@api_bp.route('/api/experience', methods=['GET'])
@maintenance_guard
def get_experience_api():
    items = database.db.collection('career').where(filter=FieldFilter('type', '==', 'experience')).get()
    return jsonify({i.id: i.to_dict() for i in items})

@api_bp.route('/api/health')
def health_check():
    return jsonify({'status': 'ok', 'service': 'portfolio-api'})

@api_bp.route('/api/contact', methods=['POST'])
@maintenance_guard
def api_contact():
    """External API to receive messages from the portfolio frontend."""
    data = request.json
    if not data or not data.get('email'):
        return jsonify({'error': 'Missing contact data'}), 400
        
    msg_data = {
        'name': data.get('name', 'Anonymous'),
        'email': data.get('email'),
        'subject': data.get('subject', 'New Portfolio Lead'),
        'message': data.get('message', ''),
        'timestamp': datetime.now(),
        'is_read': False,
        'is_system': False
    }
    database.db.collection('messages').add(msg_data)
    return jsonify({'status': 'success', 'message': 'Message sent successfully.'})

# --- View Tracking & Interaction ---

@api_bp.route('/api/blog/<permalink>/update_view', methods=['GET', 'POST'])
def update_blog_view(permalink):
    blog_query = database.db.collection('blog').where('permalink', '==', permalink).limit(1).get()
    if blog_query:
        doc = blog_query[0]
        database.db.collection('blog').document(doc.id).update({'views': doc.to_dict().get('views', 0) + 1})
        database.db.collection('analytics').add({'type': 'blog', 'id': doc.id, 'title': doc.to_dict().get('title'), 'timestamp': datetime.now()})
        return jsonify({'status': 'tracked'})
    return jsonify({'error': 'Not found'}), 404

@api_bp.route('/api/projects/<permalink>/update_view', methods=['GET', 'POST'])
def update_project_view(permalink):
    project_query = database.db.collection('projects').where('permalink', '==', permalink).limit(1).get()
    if project_query:
        doc = project_query[0]
        database.db.collection('projects').document(doc.id).update({'views': doc.to_dict().get('views', 0) + 1})
        database.db.collection('analytics').add({'type': 'project', 'id': doc.id, 'title': doc.to_dict().get('title'), 'timestamp': datetime.now()})
        return jsonify({'status': 'tracked'})
    return jsonify({'error': 'Not found'}), 404

@api_bp.route('/api/downloads/<download_id>/hit', methods=['GET', 'POST', 'PATCH'])
def track_download_hit(download_id):
    doc_ref = database.db.collection('downloads').document(download_id)
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.update({'downloads_count': doc.to_dict().get('downloads_count', 0) + 1})
        database.db.collection('analytics').add({'type': 'download', 'id': download_id, 'title': doc.to_dict().get('title'), 'timestamp': datetime.now()})
        return jsonify({'status': 'tracked'})
    return jsonify({'error': 'Not found'}), 404

# --- Admin & Internal APIs ---

@api_bp.route('/api/notifications/new')
@login_required
def check_new_notifications():
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(seconds=60)
    # Fetch recent messages by timestamp only (single-field index is default)
    recent_docs = database.db.collection('messages').where(filter=FieldFilter('timestamp', '>', cutoff)).get()
    
    for doc in recent_docs:
        msg = doc.to_dict()
        # Only notify for UNREAD messages
        if not msg.get('is_read', False):
            is_system = msg.get('is_system', False)
            return jsonify({
                'has_new': True, 
                'id': doc.id, 
                'title': msg.get('subject') if is_system else f"New message from {msg.get('name')}", 
                'body': msg.get('message', '')[:100] if is_system else msg.get('subject')
            })
    return jsonify({'has_new': False})

@api_bp.route('/api/messages', methods=['POST'])
@maintenance_guard
def post_message():
    data = request.json
    if not data or not data.get('name') or not data.get('message'):
        return jsonify({'error': 'Missing required fields'}), 400
    
    if database.db:
        database.db.collection('messages').add({
            'name': data.get('name'),
            'email': data.get('email', ''),
            'subject': data.get('subject', 'General Inquiry'),
            'message': data.get('message'),
            'timestamp': datetime.now(),
            'is_read': False,
            'is_system': False,
            'source': 'Contact Form'
        })
        return jsonify({'status': 'success', 'message': 'Message sent successfully.'})
    return jsonify({'error': 'Database offline'}), 503

@api_bp.route('/api/analytics', methods=['POST'])
@maintenance_guard
def log_analytics():
    data = request.json
    if not data: return jsonify({'error': 'No data'}), 400
    
    if database.db:
        database.db.collection('analytics').add({
            'path': data.get('path', '/'),
            'referrer': data.get('referrer', ''),
            'user_agent': request.headers.get('User-Agent'),
            'timestamp': datetime.now(),
            'ip': request.remote_addr
        })
        return jsonify({'status': 'success'})
    return jsonify({'error': 'Database offline'}), 503

@api_bp.route('/api/upload-image', methods=['POST'])
@login_required
def upload_image():
    if 'image' not in request.files: return jsonify({'error': 'No image'}), 400

    if 'image' not in request.files: return jsonify({'error': 'No image'}), 400
    file = request.files['image']
    
    # Check form key first (for setup), then env, then DB
    key = request.form.get('api_key') or os.getenv('IMGBB_API_KEY')
    if not key and database.db:
        doc = database.db.collection('settings').document('integrations').get()
        if doc.exists:
            key = doc.to_dict().get('imgbb_api_key')
            
    if not key: return jsonify({'error': 'ImgBB Key missing'}), 500
    
    try:
        import base64
        file.seek(0) # Reset pointer
        data = base64.b64encode(file.read()).decode('utf-8')
        resp = requests.post('https://api.imgbb.com/1/upload', data={'key': key, 'image': data}, timeout=30).json()
        if resp.get('status') == 200:
            return jsonify({'url': resp['data']['url']})
        else:
            error_msg = resp.get('error', {}).get('message', 'Upload failed')
            return jsonify({'error': f"ImgBB: {error_msg}"}), 400
    except Exception as e:
        return jsonify({'error': f"Server error: {str(e)}"}), 500

@api_bp.route('/api/notifications/dismiss/<msg_id>', methods=['POST', 'DELETE'])
@admin_required
def dismiss_notification_api(msg_id):
    if request.method == 'DELETE':
        database.db.collection('messages').document(msg_id).delete()
    else:
        # Change from delete to mark as read so it stays in Inbound Messages but leaves Tray/Center
        database.db.collection('messages').document(msg_id).update({'is_read': True})
    return jsonify({'status': 'success'})

@api_bp.route('/api/export')
@admin_required
def export_data():
    # Export all content collections
    export = {
        'blogs': {b.id: b.to_dict() for b in database.db.collection('blog').get()},
        'projects': {p.id: p.to_dict() for p in database.db.collection('projects').get()},
        'career': {c.id: c.to_dict() for c in database.db.collection('career').get()},
        'links': {l.id: l.to_dict() for l in database.db.collection('links').get()},
        'downloads': {d.id: d.to_dict() for d in database.db.collection('downloads').get()},
        'resumes': {r.id: r.to_dict() for r in database.db.collection('resumes').get()},
        'vault': {v.id: v.to_dict() for v in database.db.collection('vault').get()},
        'messages': {m.id: m.to_dict() for m in database.db.collection('messages').get()},
        'domains': {d.id: d.to_dict() for d in database.db.collection('domains').get()},
        'analytics': {a.id: a.to_dict() for a in database.db.collection('analytics').get()},
    }
    
    # Export all settings documents separately
    settings_ref = database.db.collection('settings')
    export['settings'] = {}
    
    # Get all settings documents
    for doc in ['website', 'seo', 'features', 'ui', 'integrations']:
        doc_ref = settings_ref.document(doc).get()
        if doc_ref.exists:
            export['settings'][doc] = doc_ref.to_dict()
    
    response = make_response(json.dumps(export, indent=2, default=str))
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = f'attachment; filename=portfolio_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
    return response

@api_bp.route('/api/restore', methods=['POST'])
@admin_required
def restore_data():
    file_key = 'file' if 'file' in request.files else 'backup_file'
    if file_key not in request.files: return jsonify({'error': 'No file'}), 400
    
    try:
        from flask import flash, url_for, redirect
        data = json.load(request.files[file_key])
        
        # Restore all content collections
        collections_map = {
            'blogs': 'blog',
            'projects': 'projects',
            'career': 'career',
            'links': 'links',
            'downloads': 'downloads',
            'resumes': 'resumes',
            'vault': 'vault',
            'messages': 'messages',
            'domains': 'domains',
            'analytics': 'analytics'
        }
        
        for backup_key, firestore_col in collections_map.items():
            if backup_key in data and data[backup_key]:
                for doc_id, doc_data in data[backup_key].items():
                    database.db.collection(firestore_col).document(doc_id).set(doc_data)
        
        # Restore all settings documents
        if 'settings' in data:
            settings_data = data['settings']
            
            # Handle new format (settings as nested object)
            if isinstance(settings_data, dict):
                for doc_name in ['website', 'seo', 'features', 'ui', 'integrations']:
                    if doc_name in settings_data:
                        database.db.collection('settings').document(doc_name).set(settings_data[doc_name], merge=True)
                
                # Backward compatibility: if data inside 'settings' is actually 'website' data
                if 'site_name' in settings_data and 'website' not in settings_data:
                    database.db.collection('settings').document('website').set(settings_data, merge=True)
            else:
                # Old format: 'settings' was just the 'website' document data
                database.db.collection('settings').document('website').set(settings_data, merge=True)
        
        # Handle older SEO format compatibility
        if 'seo' in data and 'settings' not in data:
            database.db.collection('settings').document('seo').set(data['seo'], merge=True)
            
        # Clear cache so changes reflect immediately
        from core.shared import cache
        if cache: cache.clear()
            
        flash('🎉 Backup restored successfully! All data and settings recovered.', 'success')
        return redirect(url_for('admin.settings_website'))
    except Exception as e:
        flash(f'Failed to restore: {str(e)}', 'danger')
        return redirect(url_for('admin.settings_website'))

# --- Push Notification Endpoints ---

@api_bp.route('/api/push/public-key', methods=['GET'])
def get_push_key():
    key = os.getenv('VAPID_PUBLIC_KEY')
    # Return 200 even if null to avoid constant 500 errors in console if not configured
    return jsonify({'publicKey': key})

@api_bp.route('/api/push/subscribe', methods=['POST'])
def push_subscribe():
    if not request.json: return jsonify({'error': 'No data'}), 400
    database.db.collection('push_subs').add({'subscription': request.json, 'timestamp': datetime.now()})
    return jsonify({'status': 'subscribed'}), 201

@api_bp.route('/api/push/send', methods=['POST'])
@admin_required
def push_send():
    data = request.json or {}
    if not data.get('message'): return jsonify({'error': 'Message missing'}), 400
    
    title = data.get('title', 'Portfolio Update')
    msg = data['message']
    
    from core.shared import send_push_notification
    send_push_notification(title, msg)
    
    # Also log to system notifications so it shows up in tray/center
    database.db.collection('messages').add({
        'name': 'System Admin',
        'subject': title,
        'message': msg,
        'timestamp': datetime.now(),
        'is_read': False,
        'is_system': True,
        'alert_type': 'info'
    })
    
    return jsonify({'status': 'sent'})
