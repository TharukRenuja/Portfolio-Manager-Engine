from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from firebase_admin import firestore
from core import database
from core.shared import login_required, admin_required, trigger_rebuild
from google.cloud.firestore import FieldFilter

tools_bp = Blueprint('tools', __name__)

# --- Messages ---
@tools_bp.route('/messages')
@login_required
def messages_list():
    # Only show inbound messages here
    # Fetch all and filter in Python to avoid composite index requirement
    all_msgs = database.db.collection('messages').get()
    inbound = {}
    for m in all_msgs:
        d = m.to_dict()
        if not d.get('is_system'):
            # Normalize timestamp to datetime object for template
            ts = d.get('timestamp')
            if isinstance(ts, str):
                try:
                    from datetime import datetime as dt
                    d['timestamp'] = dt.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    d['timestamp'] = None
            inbound[m.id] = d
    
    # Normalize timestamp for sorting (handle both datetime and strings from backups)
    def get_sortable_timestamp(msg_id):
        ts = inbound[msg_id].get('timestamp')
        if isinstance(ts, str):
            try:
                from datetime import datetime as dt
                return dt.fromisoformat(ts.replace('Z', '+00:00'))
            except:
                return datetime.min
        return ts or datetime.min
    
    # Sort by timestamp descending
    sorted_keys = sorted(inbound.keys(), key=get_sortable_timestamp, reverse=True)
    sorted_inbound = {k: inbound[k] for k in sorted_keys}
    
    return render_template('messages.html', messages=sorted_inbound)

@tools_bp.route('/notifications')
@login_required
def notification_center():
    # Show UNREAD system alerts AND unread human messages here
    # Fetch all and filter in Python to avoid composite index requirement
    all_msgs = database.db.collection('messages').get()
    alerts = []
    for m in all_msgs:
        d = m.to_dict()
        if d.get('is_read', False): continue
        
        is_system = d.get('is_system', False)
        
        # Determine link
        link = url_for('tools.notification_center')
        subject = d.get('subject', '')
        if 'Domain Alert' in subject:
            link = url_for('tools.domain_list')
        elif 'Outage' in subject:
            link = url_for('tools.vault_list')
        elif not is_system:
            link = url_for('tools.messages_list')
            
        alerts.append({'id': m.id, 'link': link, **d})
    
    # Normalize timestamps for sorting (handle both datetime objects and strings from backups)
    def get_sortable_timestamp(alert):
        ts = alert.get('timestamp')
        if isinstance(ts, str):
            try:
                from datetime import datetime as dt
                return dt.fromisoformat(ts.replace('Z', '+00:00'))
            except:
                return datetime.min
        return ts or datetime.min
    
    # Sort by timestamp descending
    alerts.sort(key=get_sortable_timestamp, reverse=True)
        
    return render_template('notifications_center.html', alerts=alerts)

@tools_bp.route('/messages/read/<msg_id>', methods=['POST'])
@login_required
def message_toggle_read(msg_id):
    msg_ref = database.db.collection('messages').document(msg_id)
    doc = msg_ref.get()
    if doc.exists:
        msg_ref.update({'is_read': not doc.to_dict().get('is_read', False)})
    return redirect(url_for('tools.messages_list'))

@tools_bp.route('/messages/delete', methods=['POST'])
@admin_required
def message_delete():
    msg_id = request.form.get('message_id')
    if msg_id: database.db.collection('messages').document(msg_id).delete()
    return redirect(url_for('tools.messages_list'))

# --- Media Manager ---
@tools_bp.route('/media')
@login_required
def media_manager():
    # Dynamically extract cover images from blogs and projects (old system)
    images = []
    
    # Check blogs
    blogs = database.db.collection('blog').get()
    for b in blogs:
        d = b.to_dict()
        if d.get('img'):
            images.append({
                'url': d['img'],
                'source': d.get('title', 'Untitled'),
                'type': 'Blog Cover',
                'id': f'blog_{b.id}'
            })
        
    # Check projects
    projects = database.db.collection('projects').get()
    for p in projects:
        d = p.to_dict()
        if d.get('img'):
            images.append({
                'url': d['img'],
                'source': d.get('title', 'Untitled'),
                'type': 'Project Cover',
                'id': f'project_{p.id}'
            })
        
    return render_template('media.html', images=images)

@tools_bp.route('/media/upload', methods=['POST'])
@admin_required
def media_upload():
    data = request.form.to_dict()
    data['uploaded_at'] = datetime.now()
    database.db.collection('media').add(data)
    flash('Media entry added!', 'success')
    return redirect(url_for('tools.media_manager'))

@tools_bp.route('/media/delete', methods=['POST'])
@admin_required
def media_delete():
    media_id = request.form.get('media_id')
    if media_id: database.db.collection('media').document(media_id).delete()
    flash('Media entry removed.', 'warning')
    return redirect(url_for('tools.media_manager'))

# --- Vault ---
@tools_bp.route('/vault')
@login_required
def vault_list():
    items = database.db.collection('vault').get()
    vault_data = {i.id: i.to_dict() for i in items}
    return render_template('vault.html', vault=vault_data)

@tools_bp.route('/vault/add', methods=['POST'])
@admin_required
def vault_add():
    data = request.form.to_dict()
    data['updated_at'] = datetime.now()
    database.db.collection('vault').add(data)
    flash('Item added to vault.', 'success')
    return redirect(url_for('tools.vault_list'))

@tools_bp.route('/vault/edit/<item_id>', methods=['POST'])
@admin_required
def vault_edit(item_id):
    data = request.form.to_dict()
    data['updated_at'] = datetime.now()
    database.db.collection('vault').document(item_id).update(data)
    flash('Vault item updated.', 'success')
    return redirect(url_for('tools.vault_list'))

@tools_bp.route('/vault/delete', methods=['POST'])
@admin_required
def vault_delete():
    item_id = request.form.get('item_id')
    if item_id: database.db.collection('vault').document(item_id).delete()
    flash('Vault item removed.', 'warning')
    return redirect(url_for('tools.vault_list'))

@tools_bp.route('/vault/checks')
@login_required
def vault_run_checks():
    import requests
    from datetime import datetime
    from core.shared import get_settings
    
    results = []
    settings = get_settings()
    is_maint = settings.get('maintenance_mode')

    # Status check functions
    def probe_db():
        return database.db.collection('settings').document('website').get()
    
    def probe_gateway():
        if is_maint: return 'maintenance'
        try:
            # Use the current host URL (works for localhost, custom domains, cloud servers)
            base_url = request.host_url.rstrip('/')
            r = requests.get(f'{base_url}/api/health', timeout=2)
            return 'operational' if r.status_code == 200 else 'degraded'
        except: return 'offline'

    probes = {
        'Database': probe_db,
        'Gateway': probe_gateway,
        'Auth': lambda: database.db.collection('users').limit(1).get()
    }
    
    for name, probe_fn in probes.items():
        start = datetime.now()
        try:
            res = probe_fn()
            # Determine status based on probe result
            if isinstance(res, str): status = res
            else: status = 'operational' if (not hasattr(res, 'status_code') or res.status_code < 400) else 'degraded'
            
            results.append({
                'name': name, 
                'status': status, 
                'latency': f"{(datetime.now()-start).microseconds//1000}ms" if status != 'maintenance' else 'N/A'
            })
        except:
            results.append({'name': name, 'status': 'offline', 'latency': 'N/A'})

    # Failure alert persistence
    failures = [r['name'] for r in results if r['status'] in ['offline', 'degraded']]
    if failures:
        from core.shared import send_push_notification
        subject = "⚠️ System Health Alert"
        # Avoid duplicate alerts - fetch by subject only, then filter by timestamp in Python
        # This avoids requiring a composite index on (subject, timestamp)
        from datetime import timedelta
        threshold = datetime.now() - timedelta(hours=1)
        recent_msgs = database.db.collection('messages').where(filter=FieldFilter('subject', '==', subject)).get()
        already_sent = any(
            m.to_dict().get('timestamp') and 
            hasattr(m.to_dict().get('timestamp'), 'replace') and
            m.to_dict().get('timestamp').replace(tzinfo=None) > threshold 
            for m in recent_msgs
        )
        
        if not already_sent:
            send_push_notification(subject, f"Issues: {', '.join(failures)}")
            database.db.collection('messages').add({
                'name': 'System Monitor',
                'subject': subject,
                'message': f"Services failing: {', '.join(failures)}",
                'timestamp': datetime.now(), 'is_read': False, 'is_system': True, 'alert_type': 'critical'
            })
    
    return jsonify({'results': results})

@tools_bp.route('/vault/ping', methods=['POST'])
@login_required
def vault_ping():
    import requests
    url = request.json.get('url')
    if not url: return jsonify({'status': 'error', 'message': 'No URL provided'}), 400
    try:
        r = requests.get(url, timeout=5)
        return jsonify({'status': 'online' if r.status_code == 200 else 'offline', 'code': r.status_code})
    except:
        return jsonify({'status': 'offline', 'message': 'Connection failed'})

@tools_bp.route('/vault/sync', methods=['POST'])
@login_required
def vault_sync():
    """Sync all vault deployments - ping URLs and update statuses"""
    import requests
    from datetime import datetime
    
    deployments = database.db.collection('vault').where('category', '==', 'deployment').get()
    synced = 0
    
    for deployment in deployments:
        data = deployment.to_dict()
        url = data.get('url')
        
        if url:
            try:
                r = requests.get(url, timeout=5)
                status = 'online' if r.status_code == 200 else 'offline'
            except:
                status = 'offline'
            
            # Update vault item
            database.db.collection('vault').document(deployment.id).update({
                'last_status': status,
                'last_check': datetime.now()
            })
            synced += 1
    
    return jsonify({'message': f'Synced {synced} deployments', 'count': synced})

# --- Domains ---
@tools_bp.route('/domains')
@login_required
def domain_list():
    domains = database.db.collection('domains').get()
    domains_data = {d.id: d.to_dict() for d in domains}
    return render_template('domains.html', domains=domains_data)

@tools_bp.route('/domains/add', methods=['POST'])
@admin_required
def domain_add():
    data = request.form.to_dict()
    database.db.collection('domains').add(data)
    flash('Domain added to tracking.', 'success')
    return redirect(url_for('tools.domain_list'))

@tools_bp.route('/domains/delete', methods=['POST'])
@admin_required
def domain_delete():
    domain_id = request.form.get('domain_id')
    if domain_id: database.db.collection('domains').document(domain_id).delete()
    flash('Domain tracking removed.', 'warning')
    return redirect(url_for('tools.domain_list'))

# --- Additional (Links, Downloads, Webhooks) ---
@tools_bp.route('/links')
@login_required
def links_list():
    links = database.db.collection('links').order_by('order').get()
    links_data = {l.id: l.to_dict() for l in links}
    return render_template('links.html', links=links_data)

@tools_bp.route('/links/add', methods=['POST'])
@admin_required
def link_add():
    data = request.form.to_dict()
    data['order'] = int(data.get('order', 0))
    database.db.collection('links').add(data)
    trigger_rebuild()
    flash('Link added.', 'success')
    return redirect(url_for('tools.links_list'))

@tools_bp.route('/links/delete', methods=['POST'])
@admin_required
def link_delete():
    link_id = request.form.get('link_id')
    if link_id: database.db.collection('links').document(link_id).delete()
    trigger_rebuild()
    flash('Link deleted.', 'warning')
    return redirect(url_for('tools.links_list'))

# --- Resumes ---
@tools_bp.route('/resumes')
@login_required
def resumes_list():
    resumes = database.db.collection('resumes').order_by('created_at', direction='DESCENDING').get()
    resumes_data = {r.id: r.to_dict() for r in resumes}
    return render_template('resumes.html', resumes=resumes_data)

@tools_bp.route('/resumes/add', methods=['POST'])
@admin_required
def resumes_add():
    data = request.form.to_dict()
    data['created_at'] = datetime.now()
    data['is_primary'] = 'is_primary' in data
    
    if data['is_primary']:
        # Unset other primary resumes
        batch = database.db.batch()
        current_primary = database.db.collection('resumes').where(filter=FieldFilter('is_primary', '==', True)).stream()
        for doc in current_primary:
            batch.update(doc.reference, {'is_primary': False})
        batch.commit()

    database.db.collection('resumes').add(data)
    flash('Resume added to vault.', 'success')
    return redirect(url_for('tools.resumes_list'))

@tools_bp.route('/resumes/delete', methods=['POST'])
@admin_required
def resumes_delete():
    resume_id = request.form.get('resume_id')
    if resume_id: database.db.collection('resumes').document(resume_id).delete()
    flash('Resume removed.', 'warning')
    return redirect(url_for('tools.resumes_list'))

@tools_bp.route('/resumes/primary/<resume_id>', methods=['POST'])
@admin_required
def set_primary_resume(resume_id):
    # Unset all others
    batch = database.db.batch()
    all_resumes = database.db.collection('resumes').stream()
    for doc in all_resumes:
        batch.update(doc.reference, {'is_primary': False})
    batch.commit()

    # Set new primary
    database.db.collection('resumes').document(resume_id).update({'is_primary': True})
    flash('Primary resume updated.', 'success')
    return redirect(url_for('tools.resumes_list'))

@tools_bp.route('/downloads')
@login_required
def downloads_list():
    downloads = database.db.collection('downloads').get()
    downloads_data = {d.id: d.to_dict() for d in downloads}
    return render_template('downloads/list.html', downloads=downloads_data)

@tools_bp.route('/downloads/add', methods=['POST'])
@admin_required
def download_add():
    data = request.form.to_dict()
    data['downloads_count'] = 0
    database.db.collection('downloads').add(data)
    trigger_rebuild()
    flash('Download resource added.', 'success')
    return redirect(url_for('tools.downloads_list'))

@tools_bp.route('/downloads/delete', methods=['POST'])
@admin_required
def download_delete():
    dl_id = request.form.get('download_id')
    if dl_id: database.db.collection('downloads').document(dl_id).delete()
    trigger_rebuild()
    flash('Download removed.', 'warning')
    return redirect(url_for('tools.downloads_list'))

@tools_bp.route('/downloads/new')
@login_required
def download_new():
    return render_template('downloads/edit.html', download={}, download_id=None)

@tools_bp.route('/downloads/edit/<download_id>')
@login_required
def download_edit(download_id):
    dl_ref = database.db.collection('downloads').document(download_id).get()
    if not dl_ref.exists:
        flash('Download not found', 'danger')
        return redirect(url_for('tools.downloads_list'))
    return render_template('downloads/edit.html', download=dl_ref.to_dict(), download_id=download_id)

@tools_bp.route('/downloads/update/<download_id>', methods=['POST'])
@admin_required
def download_update(download_id):
    data = request.form.to_dict()
    database.db.collection('downloads').document(download_id).update(data)
    trigger_rebuild()
    flash('Download updated.', 'success')
    return redirect(url_for('tools.downloads_list'))

@tools_bp.route('/api/test-webhook', methods=['POST'])
@admin_required
def test_webhook():
    import requests
    webhook_url = request.json.get('url')
    if not webhook_url: return jsonify({'status': 'error', 'message': 'No URL'}), 400
    try:
        r = requests.post(webhook_url, json={'triggered_by': 'Test Webhook'})
        return jsonify({'status': 'success', 'code': r.status_code})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
