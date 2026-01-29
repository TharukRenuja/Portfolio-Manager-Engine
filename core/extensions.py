from flask_bcrypt import Bcrypt
from flask_apscheduler import APScheduler
from flask_cors import CORS
from flask_caching import Cache

bcrypt = Bcrypt()
scheduler = APScheduler()
cors = CORS()
cache = Cache()
