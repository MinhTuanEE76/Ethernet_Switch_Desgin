# config.py
import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-super-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///switch_manager.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session config
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # Timezone
    TIMEZONE = 'Asia/Ho_Chi_Minh'
    
    # Default admin
    DEFAULT_ADMIN_USERNAME = 'admin'
    DEFAULT_ADMIN_PASSWORD = 'admin123'
    DEFAULT_ADMIN_EMAIL = 'admin@localhost'