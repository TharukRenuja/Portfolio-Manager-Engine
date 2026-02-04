from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import os
from datetime import datetime
from core import database
from core.extensions import bcrypt
from core.shared import login_required, admin_required, root_admin_required, get_settings, get_seo, sanitize_redis_url
from google.cloud.firestore import FieldFilter

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/settings/website', methods=['GET', 'POST'])
@admin_required
def settings_website():
    if request.method == 'POST':
        # Handle website settings
        data = request.form.to_dict()
        data['maintenance_mode'] = 'maintenance_mode' in request.form
        data['updated_at'] = datetime.now()
        
        # Extract UI settings (colors) from data before saving to website
        ui_settings = {}
        if 'primary_color' in data:
            ui_settings['primary_color'] = data.pop('primary_color')
        if 'accent_color' in data:
            ui_settings['accent_color'] = data.pop('accent_color')
        
        # Save website settings
        database.db.collection('settings').document('website').set(data, merge=True)
        
        # Save UI settings if any colors were updated
        if ui_settings:
            ui_settings['updated_at'] = datetime.now()
            database.db.collection('settings').document('ui').set(ui_settings, merge=True)
        
        # Handle feature toggles
        features = {
            'blog': 'feature_blog' in request.form,
            'projects': 'feature_projects' in request.form,
            'career': 'feature_career' in request.form,
            'links': 'feature_links' in request.form,
            'vault': 'feature_vault' in request.form,
            'monitor': 'feature_monitor' in request.form,
            'resumes': 'feature_resumes' in request.form,
            'downloads': 'feature_downloads' in request.form
        }
        database.db.collection('settings').document('features').set(features, merge=True)
        
        # Clear cache so new settings load immediately
        # Clear cache so new settings load immediately
        import core.shared as shared
        if shared.cache:
            shared.cache.clear()  # Clear all cached data
        
        flash('Website settings and module configuration saved.', 'success')
        return redirect(url_for('admin.settings_website'))
    return render_template('settings/website.html', settings=get_settings())

@admin_bp.route('/settings/integrations', methods=['GET', 'POST'])
@root_admin_required
def settings_integrations():
    if request.method == 'POST':
        # Data for UI/Integrations (lowercase)
        ui_data = {
            'imgbb_api_key': request.form.get('imgbb_api_key'),
            'redis_url': sanitize_redis_url(request.form.get('redis_url')),
            'vapid_public_key': request.form.get('vapid_public_key'),
            'vapid_private_key': request.form.get('vapid_private_key'),
            'updated_at': datetime.now()
        }
        database.db.collection('settings').document('integrations').set(ui_data, merge=True)
        
        # Data for Environment/Infrastructure (UPPERCASE)
        env_data = {k.upper(): v for k, v in ui_data.items() if v}
        env_data['updated_at'] = datetime.now()
        database.db.collection('settings').document('infrastructure').set(env_data, merge=True)
        
        # Update current environment
        for k, v in env_data.items():
            if v and k not in ['UPDATED_AT', 'updated_at']: 
                os.environ[k] = str(v)
            
        flash('Integration settings updated.', 'success')
        return redirect(url_for('admin.settings_integrations'))
    
    # Get current integrations with fallback to infrastructure
    infra_doc = database.db.collection('settings').document('infrastructure').get()
    integrations_doc = database.db.collection('settings').document('integrations').get()
    
    infra = infra_doc.to_dict() if infra_doc.exists else {}
    integrations = integrations_doc.to_dict() if integrations_doc.exists else {}
    
    # Merge and Normalize: Prefer 'integrations' (manual), then 'infra' (auto), then 'os.environ' (local)
    combined = {}
    
    # List of keys we track
    tracked_keys = ['imgbb_api_key', 'redis_url', 'vapid_public_key', 'vapid_private_key']
    
    # 1. Start with os.environ (lowest priority fallback)
    for key in tracked_keys:
        val = os.getenv(key.upper())
        if val: combined[key] = val
            
    # 2. Layer infra on top
    for k, v in infra.items():
        if v and k.lower() in tracked_keys:
            combined[k.lower()] = v
            
    # 3. Layer integrations on top (highest priority)
    for k, v in integrations.items():
        if v and k.lower() in tracked_keys:
            combined[k.lower()] = v
            
    print(f"🔍 [admin.py] Dashboard merge complete. Keys found: {list(combined.keys())}")
    return render_template('settings/integrations.html', integrations=combined)

@admin_bp.route('/settings/integrations/generate-vapid', methods=['POST'])
@root_admin_required
def generate_vapid_keys():
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        import base64
        
        # Generate P-256 curve key
        pk = ec.generate_private_key(ec.SECP256R1())
        
        # Private key bytes (d value)
        private_value = pk.private_numbers().private_value
        private_bytes = private_value.to_bytes(32, 'big')
        private_b64 = base64.urlsafe_b64encode(private_bytes).decode('utf-8').rstrip('=')
        
        # Public key bytes (uncompressed 65 bytes: 0x04 + x + y)
        public_bytes = pk.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        public_b64 = base64.urlsafe_b64encode(public_bytes).decode('utf-8').rstrip('=')
        
        data = {
            'vapid_public_key': public_b64,
            'vapid_private_key': private_b64,
            'updated_at': datetime.now()
        }
        database.db.collection('settings').document('integrations').set(data, merge=True)
        
        # Save uppercase for environment recovery
        env_data = {
            'VAPID_PUBLIC_KEY': public_b64,
            'VAPID_PRIVATE_KEY': private_b64,
            'updated_at': datetime.now()
        }
        database.db.collection('settings').document('infrastructure').set(env_data, merge=True)
        
        os.environ['VAPID_PUBLIC_KEY'] = public_b64
        os.environ['VAPID_PRIVATE_KEY'] = private_b64
        
        flash('VAPID keys auto-generated successfully.', 'success')
    except Exception as e:
        flash(f'Failed to generate VAPID keys: {str(e)}', 'danger')
        
    return redirect(url_for('admin.settings_integrations'))

@admin_bp.route('/settings/seo', methods=['GET', 'POST'])
@admin_required
def settings_seo():
    if request.method == 'POST':
        data = {
            'meta_title': request.form.get('meta_title'),
            'meta_description': request.form.get('meta_description'),
            'meta_keywords': request.form.get('meta_keywords'),
            'canonical_url': request.form.get('canonical_url'),
            'custom_scripts': request.form.get('custom_scripts'),
            'og_title': request.form.get('og_title'),
            'og_description': request.form.get('og_description'),
            'og_image': request.form.get('og_image'),
            'updated_at': datetime.now()
        }
        database.db.collection('settings').document('seo').set(data, merge=True)
        flash('SEO settings updated.', 'success')
        return redirect(url_for('admin.settings_seo'))
    return render_template('settings/seo.html', seo=get_seo())

@admin_bp.route('/settings/users')
@admin_required
def settings_users():
    admins = database.db.collection('admins').get()
    admins_data = {a.id: a.to_dict() for a in admins}
    has_root = any(data.get('is_root') for data in admins_data.values())
    if not has_root and admins_data:
        earliest_email = min(admins_data.keys(), key=lambda k: admins_data[k].get('added_at', datetime.now()))
        admins_data[earliest_email]['is_root'] = True
        database.db.collection('admins').document(earliest_email).update({'is_root': True})
    return render_template('settings/users.html', admins=admins_data)

@admin_bp.route('/settings/users/add', methods=['POST'])
@admin_required
def settings_users_add():
    email = request.form.get('email')
    password = request.form.get('password')
    if email and password:
        existing = database.db.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if existing:
            flash(f'User {email} already exists.', 'danger')
            return redirect(url_for('admin.settings_users'))
        password = password[:72]
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        database.db.collection('users').add({'email': email, 'password': hashed_password, 'is_admin': True, 'created_at': datetime.now()})
        database.db.collection('admins').document(email).set({'email': email, 'added_at': datetime.now()})
        flash(f'Admin {email} created.', 'success')
    return redirect(url_for('admin.settings_users'))

@admin_bp.route('/settings/users/delete', methods=['POST'])
@admin_required
def settings_users_delete():
    email = request.form.get('email')
    if not email: return redirect(url_for('admin.settings_users'))
    admin_doc = database.db.collection('admins').document(email).get()
    if admin_doc.exists and admin_doc.to_dict().get('is_root'):
        flash('Root Admin protected.', 'danger')
        return redirect(url_for('admin.settings_users'))
    if email == session['user']['email']:
        flash('Cannot delete yourself.', 'danger')
    else:
        database.db.collection('admins').document(email).delete()
        flash('Admin removed.', 'warning')
    return redirect(url_for('admin.settings_users'))

@admin_bp.route('/settings/users/password', methods=['POST'])
@login_required
def settings_users_password():
    new_password = request.form.get('password')
    confirm_password = request.form.get('confirm_password')
    if not new_password or new_password != confirm_password:
        flash('Invalid password entry.', 'danger')
        return redirect(url_for('admin.settings_users'))
    user_email = session['user']['email']
    new_password = new_password[:72]
    hashed_password = bcrypt.generate_password_hash(new_password).decode('utf-8')
    user_refs = database.db.collection('users').where(filter=FieldFilter('email', '==', user_email)).limit(1).get()
    if user_refs:
        database.db.collection('users').document(user_refs[0].id).update({'password': hashed_password, 'updated_at': datetime.now()})
        flash('Password updated.', 'success')
    return redirect(url_for('admin.settings_users'))
