from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
from core import database
from core.extensions import bcrypt
from core.shared import login_required, admin_required, get_settings, get_seo
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
