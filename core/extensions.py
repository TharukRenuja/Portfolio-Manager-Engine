from flask_bcrypt import Bcrypt
from flask_apscheduler import APScheduler
from flask_cors import CORS

bcrypt = Bcrypt()
scheduler = APScheduler()
cors = CORS()
