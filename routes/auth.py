from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
import pyotp
import qrcode
import io
import base64
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
from core import database
from core.extensions import bcrypt
from core.shared import login_required, get_settings
from google.cloud.firestore import FieldFilter

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    # Check if system is already bootstrapped
    try:
        if database.db:
            users = database.db.collection('users').limit(1).get()
            if users:
                flash('System already configured.', 'info')
                return redirect(url_for('auth.login'))
    except:
        pass
    
    # Detect if filesystem is writable (for environment-aware setup)
    is_readonly = False
    try:
        test_file = '.write_test_temp'
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
    except:
        is_readonly = True
    
    # Check if Firebase config exists in environment
    has_firebase_env = bool(os.getenv('FIREBASE_CONFIG'))
    
    if request.method == 'GET':
        return render_template('setup.html', 
                             is_readonly=is_readonly, 
                             has_firebase_env=has_firebase_env)

    if request.method == 'POST':
        # Handle Firebase credentials first
        firebase_json = request.form.get('firebase_credentials', '').strip()
        if firebase_json:
            try:
                import json as json_lib
                firebase_data = json_lib.loads(firebase_json)
                if 'project_id' in firebase_data and 'private_key' in firebase_data:
                    # Save to firebase-key.json (for local development & VPS)
                    try:
                        with open('firebase-key.json', 'w') as f:
                            json_lib.dump(firebase_data, f, indent=2)
                        print("✅ Firebase credentials saved to firebase-key.json")
                    except Exception as e:
                        print(f"ℹ️  Could not write firebase-key.json (read-only filesystem): {e}")
                    
                    if firebase_admin._apps:
                        del firebase_admin._apps[firebase_admin._DEFAULT_APP_NAME]
                    
                    # Initialize from data directly
                    cred = credentials.Certificate(firebase_data)
                    firebase_admin.initialize_app(cred)
                    # Update global db reference
                    database.db = firestore.client()
                    database.firebase_initialized = True
                    
                    # Store in session for post-setup instructions
                    session['firebase_config_for_vercel'] = firebase_json
                    session['setup_completed'] = True
            except Exception as e:
                flash(f'Firebase setup failed: {str(e)}', 'danger')
        
        if database.db is None:
            flash('Database not initialized. Please check your credentials.', 'danger')
            return render_template('setup.html')

        # Check if user is restoring from backup
        restore_backup = request.form.get('restore_backup', '').strip()
        if restore_backup:
            try:
                import json as json_lib
                backup_data = json_lib.loads(restore_backup)
                
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
                    if backup_key in backup_data and backup_data[backup_key]:
                        for doc_id, doc_data in backup_data[backup_key].items():
                            database.db.collection(firestore_col).document(doc_id).set(doc_data)
                
                # Restore all settings documents
                if 'settings' in backup_data:
                    settings_data = backup_data['settings']
                    
                    # Handle new format (settings as nested object) or old format (flat)
                    if isinstance(settings_data, dict):
                        # New format: settings.website, settings.seo, etc.
                        for doc_name in ['website', 'seo', 'features', 'ui', 'integrations']:
                            if doc_name in settings_data:
                                database.db.collection('settings').document(doc_name).set(settings_data[doc_name], merge=True)
                        
                        # If old format compatibility: settings was get_settings() result
                        if 'site_name' in settings_data and 'website' not in settings_data:
                            # Old format - settings is the website settings directly
                            database.db.collection('settings').document('website').set(settings_data, merge=True)
                
                # Handle old backup format that had 'seo' as top-level key
                if 'seo' in backup_data and 'settings' not in backup_data:
                    database.db.collection('settings').document('seo').set(backup_data['seo'], merge=True)
                
                # Create admin account from form
                email = request.form.get('email', 'admin@example.com')
                password = request.form.get('password', 'password')[:72]
                hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
                
                database.db.collection('users').add({
                    'email': email,
                    'password': hashed_password,
                    'is_admin': True,
                    'is_root': True,
                    'created_at': datetime.now()
                })
                
                database.db.collection('admins').document(email).set({
                    'email': email,
                    'is_root': True,
                    'added_at': datetime.now()
                })
                
                flash('🎉 Backup restored successfully! You can now login.', 'success')
                return redirect(url_for('auth.login'))
                
            except Exception as e:
                flash(f'Backup restoration failed: {str(e)}', 'danger')
                return render_template('setup.html')

        # Continue with manual setup if no backup
        email = request.form['email']
        password = request.form['password'][:72]

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        database.db.collection('users').add({
            'email': email,
            'password': hashed_password,
            'is_admin': True,
            'is_root': True,
            'created_at': datetime.now()
        })
        
        database.db.collection('admins').document(email).set({
            'email': email,
            'is_root': True,
            'added_at': datetime.now()
        })
        
        # Initial settings creation
        database.db.collection('settings').document('website').set({
            'site_name': request.form.get('site_name', ''), 
            'site_bio': request.form.get('site_bio', ''),
            'contact_email': request.form.get('contact_email', ''),
            'github_url': request.form.get('github_url', ''),
            'linkedin_url': request.form.get('linkedin_url', ''),
            'twitter_url': request.form.get('twitter_url', ''),
            'favicon_url': request.form.get('favicon_url', ''),
            'updated_at': datetime.now()
        })
        
        database.db.collection('settings').document('seo').set({
            'meta_title': request.form.get('meta_title', ''),
            'meta_description': request.form.get('meta_description', ''),
            'updated_at': datetime.now()
        })
        
        
        database.db.collection('settings').document('ui').set({
            'primary_color': request.form.get('primary_color', '#FFD700'),
            'accent_color': request.form.get('accent_color', '#10B981'),
            'updated_at': datetime.now()
        })

        # --- Auto-generate Infrastructure Keys ---
        try:
            import secrets
            from pywebpush import vapid_lookup_file
            
            env_path = '.env'
            env_content = {}
            if os.path.exists(env_path):
                with open(env_path, 'r') as f:
                    for line in f:
                        if '=' in line:
                            k, v = line.strip().split('=', 1)
                            env_content[k] = v
            
            # Generate SECRET_KEY if default or missing
            if 'SECRET_KEY' not in env_content or env_content['SECRET_KEY'] == 'dev-key-123':
                env_content['SECRET_KEY'] = secrets.token_urlsafe(32)
            
            # Generate VAPID keys if missing
            if 'VAPID_PRIVATE_KEY' not in env_content:
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
                    
                    env_content['VAPID_PRIVATE_KEY'] = private_b64
                    env_content['VAPID_PUBLIC_KEY'] = public_b64
                except Exception as ve:
                    print(f"❌ VAPID Generation Failed: {ve}")

            # Add ImgBB Key to .env if provided in setup
            imgbb_key = request.form.get('imgbb_api_key')
            if imgbb_key:
                env_content['IMGBB_API_KEY'] = imgbb_key

            # Write back to .env (Try silently)
            try:
                with open(env_path, 'w') as f:
                    for k, v in env_content.items():
                        f.write(f"{k}={v}\n")
            except:
                pass
                    
            # Update current app config and environment
            from flask import current_app
            current_app.config['SECRET_KEY'] = env_content.get('SECRET_KEY', current_app.config.get('SECRET_KEY'))
            os.environ['VAPID_PRIVATE_KEY'] = env_content.get('VAPID_PRIVATE_KEY', '')
            os.environ['VAPID_PUBLIC_KEY'] = env_content.get('VAPID_PUBLIC_KEY', '')
            if imgbb_key:
                os.environ['IMGBB_API_KEY'] = imgbb_key
            
        except Exception as e:
            print(f"⚠️ Key generation skipped or failed: {e}")

        database.db.collection('settings').document('integrations').set({
            'imgbb_api_key': request.form.get('imgbb_api_key', ''),
            'updated_at': datetime.now()
        })

        database.db.collection('settings').document('features').set({
            'blog': 'feature_blog' in request.form,
            'projects': 'feature_projects' in request.form,
            'career': 'feature_career' in request.form,
            'links': 'feature_links' in request.form,
            'vault': 'feature_vault' in request.form,
            'monitor': 'feature_monitor' in request.form,
            'resumes': 'feature_resumes' in request.form,
            'downloads': 'feature_downloads' in request.form,
            'updated_at': datetime.now()
        })
        
        flash('🎉 Setup complete! All modules configured.', 'success')
        return redirect(url_for('auth.login'))

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user_ref = database.db.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1).get()
            admin_ref = database.db.collection('admins').document(email).get()
            is_admin = admin_ref.exists
            
            if user_ref:
                user_data = user_ref[0].to_dict()
                if bcrypt.check_password_hash(user_data['password'], password):
                    if user_data.get('mfa_enabled'):
                        session['mfa_user'] = {
                            'uid': user_ref[0].id, 
                            'email': email, 
                            'is_admin': is_admin,
                            'secret': user_data.get('mfa_secret')
                        }
                        return redirect(url_for('auth.login_mfa'))
                        
                    session['user'] = {'uid': user_ref[0].id, 'email': email, 'is_admin': is_admin}
                    flash('Login successful!', 'success')
                    return redirect(url_for('dashboard.dashboard_home'))
            
            flash('Invalid credentials.', 'danger')
        except Exception as e:
            flash(f'Error: {str(e)}', 'danger')
    
    return render_template('login.html')

@auth_bp.route('/login/mfa', methods=['GET', 'POST'])
def login_mfa():
    if 'mfa_user' not in session:
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        token = request.form.get('token')
        mfa_user = session['mfa_user']
        totp = pyotp.TOTP(mfa_user['secret'])
        if totp.verify(token):
            session['user'] = {'uid': mfa_user['uid'], 'email': mfa_user['email'], 'is_admin': mfa_user['is_admin']}
            session.pop('mfa_user', None)
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard.dashboard_home'))
        else:
            flash('Invalid verification code.', 'danger')
            
    return render_template('mfa_login.html')

@auth_bp.route('/logout')
def logout():
    session.pop('user', None)
    flash('Logged out successfully.', 'success')
    return redirect(url_for('auth.login'))

# MFA Management Routes
@auth_bp.route('/settings/security/mfa/setup')
@login_required
def settings_mfa_setup():
    secret = pyotp.random_base32()
    email = session['user']['email']
    site_name = get_settings().get('site_name', 'Portfolio Manager')
    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=site_name)
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    return jsonify({'secret': secret, 'qr_code': f"data:image/png;base64,{qr_base64}"})

@auth_bp.route('/settings/security/mfa/verify', methods=['POST'])
@login_required
def settings_mfa_verify():
    secret = request.form.get('secret')
    token = request.form.get('token')
    if not secret or not token: return jsonify({'success': False}), 400
    
    if pyotp.TOTP(secret).verify(token):
        email = session['user']['email']
        user_query = database.db.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1).get()
        if user_query:
            database.db.collection('users').document(user_query[0].id).update({'mfa_secret': secret, 'mfa_enabled': True})
        database.db.collection('admins').document(email).update({'mfa_enabled': True})
        flash('MFA enabled.', 'success')
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid code.'})

@auth_bp.route('/settings/security/mfa/disable', methods=['POST'])
@login_required
def settings_mfa_disable():
    email = session['user']['email']
    user_query = database.db.collection('users').where(filter=FieldFilter('email', '==', email)).limit(1).get()
    if user_query:
        database.db.collection('users').document(user_query[0].id).update({'mfa_enabled': False})
    database.db.collection('admins').document(email).update({'mfa_enabled': False})
    flash('MFA disabled.', 'warning')
    return redirect(url_for('admin.settings_users'))
