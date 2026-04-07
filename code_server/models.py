# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytz

db = SQLAlchemy()

VIETNAM_TZ = pytz.timezone('Asia/Ho_Chi_Minh')

def get_vietnam_time():
    """Lấy thời gian hiện tại theo múi giờ Việt Nam (timezone-aware)"""
    return datetime.now(VIETNAM_TZ)

def ensure_aware(dt):
    """Đảm bảo datetime có timezone info (Vietnam)"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return VIETNAM_TZ.localize(dt)
    return dt.astimezone(VIETNAM_TZ)

def to_naive_vietnam(dt):
    """Chuyển datetime thành naive datetime theo giờ Việt Nam (để lưu DB)"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(VIETNAM_TZ)
    return dt.replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: to_naive_vietnam(get_vietnam_time()))
    last_login = db.Column(db.DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'is_admin': self.is_admin,
            'is_approved': self.is_approved,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'last_login': self.last_login.strftime('%Y-%m-%d %H:%M:%S') if self.last_login else None
        }


class Switch(db.Model):
    __tablename__ = 'switches'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='OFF')  # ON, OFF, SCHEDULED
    uptime = db.Column(db.Integer, default=0)  # Tổng thời gian hoạt động (giây)
    last_on = db.Column(db.DateTime)
    auto_off_minutes = db.Column(db.Integer)  # Số phút tự động tắt
    auto_off_start = db.Column(db.DateTime)   # Thời điểm bắt đầu đếm
    last_update = db.Column(db.DateTime, 
                           default=lambda: to_naive_vietnam(get_vietnam_time()), 
                           onupdate=lambda: to_naive_vietnam(get_vietnam_time()))
    description = db.Column(db.Text)
    
    # Relationships
    schedules = db.relationship('Schedule', backref='switch', lazy='dynamic', cascade='all, delete-orphan')
    history = db.relationship('SwitchHistory', backref='switch', lazy='dynamic', cascade='all, delete-orphan')
    
    def get_last_on_aware(self):
        """Lấy last_on với timezone"""
        return ensure_aware(self.last_on)
    
    def get_auto_off_start_aware(self):
        """Lấy auto_off_start với timezone"""
        return ensure_aware(self.auto_off_start)
    
    def to_dict(self):
        auto_off_timer = None
        if self.auto_off_minutes and self.auto_off_start:
            auto_off_start_aware = ensure_aware(self.auto_off_start)
            auto_off_timer = {
                'minutes': self.auto_off_minutes,
                'start_time': auto_off_start_aware.isoformat() if auto_off_start_aware else None
            }
        
        last_on_aware = ensure_aware(self.last_on)
        
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'uptime': self.uptime or 0,
            'last_on': last_on_aware.strftime('%H:%M:%S') if last_on_aware else None,
            'auto_off_timer': auto_off_timer,
            'last_update': ensure_aware(self.last_update).isoformat() if self.last_update else None,
            'description': self.description
        }


class Schedule(db.Model):
    __tablename__ = 'schedules'
    
    id = db.Column(db.Integer, primary_key=True)
    switch_id = db.Column(db.Integer, db.ForeignKey('switches.id'), nullable=False)
    time = db.Column(db.Time, nullable=False)
    action = db.Column(db.String(10), nullable=False)  # on, off
    auto_off = db.Column(db.Integer)  # Tự động tắt sau bao nhiêu phút
    repeat_type = db.Column(db.String(20), default='once')  # once, daily, weekdays, weekends, custom
    days_of_week = db.Column(db.String(20))  # "0,1,2,3,4,5,6" cho custom
    active = db.Column(db.Boolean, default=True)
    last_executed = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: to_naive_vietnam(get_vietnam_time()))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    def get_last_executed_aware(self):
        """Lấy last_executed với timezone"""
        return ensure_aware(self.last_executed)
    
    def to_dict(self):
        last_exec_aware = ensure_aware(self.last_executed)
        created_aware = ensure_aware(self.created_at)
        
        return {
            'id': self.id,
            'switch_id': self.switch_id,
            'time': self.time.strftime('%H:%M') if self.time else None,
            'action': self.action,
            'auto_off': self.auto_off,
            'repeat_type': self.repeat_type,
            'days_of_week': self.days_of_week,
            'active': self.active,
            'last_executed': last_exec_aware.isoformat() if last_exec_aware else None,
            'created_at': created_aware.isoformat() if created_aware else None
        }
    
    def should_run_today(self):
        """Kiểm tra xem schedule có nên chạy hôm nay không"""
        today = get_vietnam_time().weekday()  # 0 = Monday, 6 = Sunday
        
        if self.repeat_type == 'daily':
            return True
        elif self.repeat_type == 'weekdays':
            return today < 5  # Monday - Friday
        elif self.repeat_type == 'weekends':
            return today >= 5  # Saturday, Sunday
        elif self.repeat_type == 'custom' and self.days_of_week:
            try:
                days = [int(d.strip()) for d in self.days_of_week.split(',') if d.strip()]
                return today in days
            except ValueError:
                return False
        elif self.repeat_type == 'once':
            # Chỉ chạy nếu chưa từng chạy
            return self.last_executed is None
        return False


class SwitchHistory(db.Model):
    __tablename__ = 'switch_history'
    
    id = db.Column(db.Integer, primary_key=True)
    switch_id = db.Column(db.Integer, db.ForeignKey('switches.id'), nullable=False)
    action = db.Column(db.String(20), nullable=False)  # ON, OFF, SCHEDULED_ON, SCHEDULED_OFF, AUTO_OFF
    timestamp = db.Column(db.DateTime, default=lambda: to_naive_vietnam(get_vietnam_time()), index=True)
    duration = db.Column(db.Integer)  # Thời gian hoạt động (giây) - chỉ khi OFF
    triggered_by = db.Column(db.String(50))  # user, schedule, timer, esp32
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    details = db.Column(db.Text)  # JSON string cho thông tin bổ sung
    
    def to_dict(self):
        timestamp_aware = ensure_aware(self.timestamp)
        
        return {
            'id': self.id,
            'switch_id': self.switch_id,
            'switch_name': self.switch.name if self.switch else None,
            'action': self.action,
            'timestamp': timestamp_aware.strftime('%Y-%m-%d %H:%M:%S') if timestamp_aware else None,
            'duration': self.duration,
            'triggered_by': self.triggered_by,
            'details': self.details
        }


class ActivityStats(db.Model):
    """Bảng lưu thống kê hoạt động theo giờ để vẽ biểu đồ"""
    __tablename__ = 'activity_stats'
    
    id = db.Column(db.Integer, primary_key=True)
    switch_id = db.Column(db.Integer, db.ForeignKey('switches.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    hour = db.Column(db.Integer, nullable=False)  # 0-23
    active_minutes = db.Column(db.Integer, default=0)  # Số phút hoạt động trong giờ đó
    on_count = db.Column(db.Integer, default=0)  # Số lần bật
    off_count = db.Column(db.Integer, default=0)  # Số lần tắt
    
    __table_args__ = (
        db.UniqueConstraint('switch_id', 'date', 'hour', name='unique_stats'),
    )