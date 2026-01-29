import firebase_admin
from firebase_admin import credentials, firestore
import json
import os

db = None
firebase_initialized = False

def init_firebase():
    global db, firebase_initialized
    if not firebase_admin._apps:
        try:
            # 1. Try Environment Variable (Best for Vercel/Heroku)
            firebase_config = os.getenv('FIREBASE_CONFIG')
            if firebase_config:
                try:
                    config = json.loads(firebase_config)
                    cred = credentials.Certificate(config)
                    firebase_admin.initialize_app(cred)
                    firebase_initialized = True
                    db = firestore.client()
                    print("✅ Firebase initialized from FIREBASE_CONFIG env var")
                    return db
                except Exception as e:
                    print(f"⚠️  Env var init failed: {e}")

            # 2. Try Local File (Local development & VPS)
            cred_path = 'firebase-key.json'
            if os.path.exists(cred_path):
                with open(cred_path, 'r') as f:
                    config = json.load(f)
                
                if config.get('client_email') and config.get('private_key'):
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                    firebase_initialized = True
                    db = firestore.client()
                    print("✅ Firebase initialized from local key file")
                    return db
                else:
                    print("ℹ️  Waiting for valid Firebase credentials (Run /setup)")
            else:
                # Create placeholder for first-time setup (Try silently)
                try:
                    placeholder = {
                        "type": "service_account",
                        "project_id": "placeholder"
                    }
                    with open(cred_path, 'w') as f:
                        json.dump(placeholder, f, indent=2)
                except:
                    pass
                print("⚠️  No Firebase credentials found. Please configure via /setup")
        except Exception as e:
            print(f"⚠️  Firebase initialization skipped: {e}")
            
    if not db:
        try:
            db = firestore.client()
        except:
            pass
    return db

# Initialize immediately for module-level access if possible
db = init_firebase()
