# app.py
from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, login_required, current_user
from config import Config
from models import db, User, Switch, Schedule, SwitchHistory, ActivityStats, get_vietnam_time, ensure_aware, to_naive_vietnam, VIETNAM_TZ
from datetime import datetime, timedelta, time as dt_time
import threading
import time
import json

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Vui lòng đăng nhập để truy cập trang này.'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Import và đăng ký blueprints
from routes.auth_routes import auth_bp
from routes.main import main_bp
from routes.api import api_bp
from routes.admin import admin_bp

app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(main_bp)
app.register_blueprint(api_bp, url_prefix='/api')
app.register_blueprint(admin_bp, url_prefix='/admin')

# Khởi tạo database
def init_database():
    with app.app_context():
        db.create_all()
        
        # Tạo admin mặc định nếu chưa có
        admin = User.query.filter_by(username=Config.DEFAULT_ADMIN_USERNAME).first()
        if not admin:
            admin = User(
                username=Config.DEFAULT_ADMIN_USERNAME,
                email=Config.DEFAULT_ADMIN_EMAIL,
                is_admin=True,
                is_approved=True
            )
            admin.set_password(Config.DEFAULT_ADMIN_PASSWORD)
            db.session.add(admin)
            print(f"Created default admin: {Config.DEFAULT_ADMIN_USERNAME}/{Config.DEFAULT_ADMIN_PASSWORD}")
        
        # Tạo 8 switches mặc định
        for i in range(1, 9):
            switch = Switch.query.get(i)
            if not switch:
                switch = Switch(id=i, name=f'Node {i}', status='OFF')
                db.session.add(switch)
        
        db.session.commit()
        print("Database initialized successfully!")

# Background Tasks
def check_schedules():
    """Kiểm tra và thực thi các lịch hẹn"""
    while True:
        try:
            with app.app_context():
                now = get_vietnam_time()
                current_time = now.time().replace(second=0, microsecond=0)
                
                schedules = Schedule.query.filter_by(active=True).all()
                
                for schedule in schedules:
                    try:
                        schedule_time = schedule.time.replace(second=0, microsecond=0)
                        
                        # Kiểm tra thời gian và ngày
                        if schedule_time == current_time and schedule.should_run_today():
                            # Kiểm tra xem đã thực thi trong phút này chưa
                            if schedule.last_executed:
                                last_exec = ensure_aware(schedule.last_executed)
                                time_diff = (now - last_exec).total_seconds()
                                if time_diff < 60:
                                    continue
                            
                            switch = Switch.query.get(schedule.switch_id)
                            if switch:
                                execute_schedule(switch, schedule, now)
                                
                    except Exception as e:
                        print(f"Error processing schedule {schedule.id}: {e}")
                        continue
                        
        except Exception as e:
            print(f"Schedule checker error: {e}")
        
        time.sleep(30)


def execute_schedule(switch, schedule, now):
    """Thực thi một schedule cụ thể"""
    try:
        old_status = switch.status
        now_naive = to_naive_vietnam(now)
        
        if schedule.action == 'on':
            switch.status = 'ON'
            switch.last_on = now_naive
            if schedule.auto_off:
                switch.auto_off_minutes = schedule.auto_off
                switch.auto_off_start = now_naive
            action = 'SCHEDULED_ON'
        else:
            if old_status == 'ON' and switch.last_on:
                last_on_aware = ensure_aware(switch.last_on)
                duration = int((now - last_on_aware).total_seconds())
                if duration > 0:
                    switch.uptime = (switch.uptime or 0) + duration
                record_history(switch.id, 'SCHEDULED_OFF', duration, 'schedule')
            switch.status = 'OFF'
            switch.auto_off_minutes = None
            switch.auto_off_start = None
            action = 'SCHEDULED_OFF'
        
        schedule.last_executed = now_naive
        
        # Nếu là lịch một lần, deactivate
        if schedule.repeat_type == 'once':
            schedule.active = False
        
        db.session.commit()
        
        # Gửi update real-time - SỬA LẠI PHẦN NÀY
        socketio.emit('switch_update', switch.to_dict(), namespace='/')
        
        if schedule.action == 'on':
            record_history(switch.id, 'SCHEDULED_ON', None, 'schedule')
            
        print(f"✅ Schedule executed: Switch {switch.id} -> {action}")
        
    except Exception as e:
        print(f"❌ Execute schedule error: {e}")
        db.session.rollback()


def check_auto_off_timers():
    """Kiểm tra và thực thi auto-off timers"""
    while True:
        try:
            with app.app_context():
                now = get_vietnam_time()
                
                switches = Switch.query.filter(
                    Switch.status == 'ON',
                    Switch.auto_off_minutes.isnot(None),
                    Switch.auto_off_start.isnot(None)
                ).all()
                
                for switch in switches:
                    try:
                        start_time = ensure_aware(switch.auto_off_start)
                        if start_time is None:
                            continue
                            
                        elapsed_minutes = (now - start_time).total_seconds() / 60
                        
                        if elapsed_minutes >= switch.auto_off_minutes:
                            # Tính duration
                            duration = 0
                            if switch.last_on:
                                last_on_aware = ensure_aware(switch.last_on)
                                if last_on_aware:
                                    duration = int((now - last_on_aware).total_seconds())
                            else:
                                duration = int(switch.auto_off_minutes * 60)
                            
                            if duration > 0:
                                switch.uptime = (switch.uptime or 0) + duration
                            
                            switch.status = 'OFF'
                            switch.auto_off_minutes = None
                            switch.auto_off_start = None
                            
                            db.session.commit()
                            
                            # Record history
                            record_history(switch.id, 'AUTO_OFF', duration, 'timer')
                            
                            # Gửi update real-time - SỬA LẠI PHẦN NÀY
                            socketio.emit('switch_update', switch.to_dict(), namespace='/')
                            
                            print(f"⏰ Auto-off executed: Switch {switch.id}, duration: {duration}s")
                            
                    except Exception as e:
                        print(f"❌ Error processing auto-off for switch {switch.id}: {e}")
                        continue
                        
        except Exception as e:
            print(f"❌ Auto-off checker error: {e}")
        
        time.sleep(10)


def update_activity_stats():
    """Cập nhật thống kê hoạt động mỗi phút"""
    while True:
        try:
            with app.app_context():
                now = get_vietnam_time()
                today = now.date()
                current_hour = now.hour
                
                # Lấy các switch đang ON
                active_switches = Switch.query.filter_by(status='ON').all()
                
                for switch in active_switches:
                    try:
                        # Tìm hoặc tạo record thống kê
                        stat = ActivityStats.query.filter_by(
                            switch_id=switch.id,
                            date=today,
                            hour=current_hour
                        ).first()
                        
                        if not stat:
                            stat = ActivityStats(
                                switch_id=switch.id,
                                date=today,
                                hour=current_hour,
                                active_minutes=0,
                                on_count=0,
                                off_count=0
                            )
                            db.session.add(stat)
                        
                        stat.active_minutes += 1  # Thêm 1 phút
                        
                    except Exception as e:
                        print(f"Error updating stats for switch {switch.id}: {e}")
                        continue
                    
                db.session.commit()
                
        except Exception as e:
            print(f"Stats updater error: {e}")
        
        time.sleep(60)  # Mỗi phút


def record_history(switch_id, action, duration=None, triggered_by='user', user_id=None, details=None):
    """Ghi lịch sử hoạt động"""
    try:
        now = get_vietnam_time()
        now_naive = to_naive_vietnam(now)
        
        history = SwitchHistory(
            switch_id=switch_id,
            action=action,
            timestamp=now_naive,
            duration=duration,
            triggered_by=triggered_by,
            user_id=user_id,
            details=json.dumps(details) if details else None
        )
        db.session.add(history)
        
        # Cập nhật thống kê
        stat = ActivityStats.query.filter_by(
            switch_id=switch_id,
            date=now.date(),
            hour=now.hour
        ).first()
        
        if not stat:
            stat = ActivityStats(
                switch_id=switch_id,
                date=now.date(),
                hour=now.hour,
                active_minutes=0,
                on_count=0,
                off_count=0
            )
            db.session.add(stat)
        
        if 'ON' in action:
            stat.on_count = (stat.on_count or 0) + 1
        elif 'OFF' in action:
            stat.off_count = (stat.off_count or 0) + 1
        
        db.session.commit()
        
    except Exception as e:
        print(f"Record history error: {e}")
        db.session.rollback()


# Socket.IO Events
# Thêm vào app.py - Phần Socket.IO Events (thay thế phần hiện tại)

# Socket.IO Events
@socketio.on('connect')
def handle_connect():
    print(f'✅ Client connected: {request.sid}')
    emit('connection_status', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    print(f'❌ Client disconnected: {request.sid}')

@socketio.on('request_status')
def handle_request_status():
    """Gửi trạng thái tất cả switches"""
    try:
        switches = Switch.query.all()
        switches_data = {}
        for s in switches:
            switches_data[s.id] = s.to_dict()
        emit('all_switches', switches_data)
        print(f'📤 Sent status to client: {request.sid}')
    except Exception as e:
        print(f'❌ Error sending status: {e}')

# Helper function để emit socket events một cách an toàn
def emit_switch_update(switch_id):
    """Emit switch update to all connected clients"""
    try:
        switch = Switch.query.get(switch_id)
        if switch:
            socketio.emit('switch_update', switch.to_dict(), namespace='/')
            print(f'🔄 Emitted update for switch {switch_id}: {switch.status}')
    except Exception as e:
        print(f'❌ Error emitting switch update: {e}')

def emit_all_switches_off():
    """Emit all switches off event"""
    try:
        socketio.emit('all_switches_off', {}, namespace='/')
        print('⚠️ Emitted all switches off')
    except Exception as e:
        print(f'❌ Error emitting all switches off: {e}')

# Expose cho routes
app.record_history = record_history

if __name__ == '__main__':
    init_database()
    
    # Start background threads
    schedule_thread = threading.Thread(target=check_schedules, daemon=True)
    schedule_thread.start()
    
    timer_thread = threading.Thread(target=check_auto_off_timers, daemon=True)
    timer_thread.start()
    
    stats_thread = threading.Thread(target=update_activity_stats, daemon=True)
    stats_thread.start()
    
    print("Starting server on http://0.0.0.0:8018")
    socketio.run(app, host='0.0.0.0', port=8018, debug=True, allow_unsafe_werkzeug=True)