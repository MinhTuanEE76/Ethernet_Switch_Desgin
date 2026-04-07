# routes/api.py
from flask import Blueprint, jsonify, request, current_app
from models import db, Switch, Schedule, SwitchHistory, get_vietnam_time, ensure_aware, to_naive_vietnam, VIETNAM_TZ
import json

api_bp = Blueprint('api', __name__)


# ============= API cho ESP32 =============

@api_bp.route('/switch/<int:switch_id>', methods=['GET'])
def get_switch_status(switch_id):
    """Lấy trạng thái của một switch (cho ESP32 polling)"""
    switch = Switch.query.get(switch_id)
    
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    schedules = Schedule.query.filter_by(switch_id=switch_id, active=True).all()
    
    auto_off_timer = None
    if switch.auto_off_minutes and switch.auto_off_start:
        auto_off_start = ensure_aware(switch.auto_off_start)
        auto_off_timer = {
            'minutes': switch.auto_off_minutes,
            'start_time': auto_off_start.isoformat() if auto_off_start else None
        }
    
    # Get current time
    now = get_vietnam_time()
    
    # Convert time string (HH:MM) to seconds since midnight
    def time_to_seconds(time_obj):
        """Convert time object to seconds since midnight"""
        if time_obj and hasattr(time_obj, 'hour'):
            return time_obj.hour * 3600 + time_obj.minute * 60 + getattr(time_obj, 'second', 0)
        return 0
    
    # Calculate current seconds in day
    seconds_in_day = now.hour * 3600 + now.minute * 60 + now.second
    
    last_on_aware = ensure_aware(switch.last_on)
    
    return jsonify({
        'id': switch.id,
        'name': switch.name,
        'status': switch.status,
        'uptime': switch.uptime or 0,
        'last_on': last_on_aware.strftime('%Y-%m-%dT%H:%M:%S') if last_on_aware else None,
        'auto_off_timer': auto_off_timer,
        'schedules': [{
            'id': s.id,
            'switch_id': s.switch_id,
            'time': time_to_seconds(s.time),
            'action': s.action,
            'auto_off': s.auto_off,
            'repeat_type': s.repeat_type,
            'days_of_week': s.days_of_week,
            'active': 1 if s.active else 0,
            'created_at': ensure_aware(s.created_at).strftime('%Y-%m-%dT%H:%M:%S') if s.created_at else None
        } for s in schedules],
        'current_time': {
            'seconds_in_day': seconds_in_day,
            'timestamp': now.isoformat(),
            'weekday': now.weekday()
        }
    })


@api_bp.route('/switch/<int:switch_id>/status', methods=['POST'])
def update_switch_status(switch_id):
    """Cập nhật trạng thái switch từ ESP32"""
    data = request.json
    status = data.get('status')
    uptime = data.get('uptime', 0)
    
    switch = Switch.query.get(switch_id)
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    old_status = switch.status
    now = get_vietnam_time()
    now_naive = to_naive_vietnam(now)
    
    if status == 'ON':
        switch.status = 'ON'
        switch.uptime = uptime
        switch.last_on = now_naive
        
        if old_status != 'ON':
            history = SwitchHistory(
                switch_id=switch_id,
                action='ON',
                timestamp=now_naive,
                triggered_by='esp32'
            )
            db.session.add(history)
    else:
        if old_status == 'ON' and switch.last_on:
            last_on_aware = ensure_aware(switch.last_on)
            duration = int((now - last_on_aware).total_seconds())
            if duration > 0:
                history = SwitchHistory(
                    switch_id=switch_id,
                    action='OFF',
                    timestamp=now_naive,
                    duration=duration,
                    triggered_by='esp32'
                )
                db.session.add(history)
        
        switch.status = 'OFF'
        switch.uptime = uptime
        switch.auto_off_minutes = None
        switch.auto_off_start = None
    
    db.session.commit()
    
    # Emit socket event - SỬA LẠI PHẦN NÀY
    try:
        from app import socketio
        socketio.emit('switch_update', switch.to_dict(), namespace='/')
        socketio.sleep(0)  # Đảm bảo message được gửi
    except Exception as e:
        current_app.logger.error(f"Socket emit error: {e}")
    
    return jsonify({'success': True})


@api_bp.route('/switch/<int:switch_id>/toggle', methods=['POST'])
def toggle_switch(switch_id):
    """Bật/tắt switch từ web"""
    from flask_login import current_user
    
    switch = Switch.query.get(switch_id)
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    now = get_vietnam_time()
    now_naive = to_naive_vietnam(now)
    old_status = switch.status
    new_status = 'OFF' if old_status == 'ON' else 'ON'
    
    user_id = current_user.id if hasattr(current_user, 'id') and current_user.is_authenticated else None
    
    if new_status == 'ON':
        switch.status = 'ON'
        switch.last_on = now_naive
        
        history = SwitchHistory(
            switch_id=switch_id,
            action='ON',
            timestamp=now_naive,
            triggered_by='user',
            user_id=user_id
        )
        db.session.add(history)
    else:
        duration = None
        if old_status == 'ON' and switch.last_on:
            last_on_aware = ensure_aware(switch.last_on)
            duration = int((now - last_on_aware).total_seconds())
            if duration > 0:
                switch.uptime = (switch.uptime or 0) + duration
        
        switch.status = 'OFF'
        switch.auto_off_minutes = None
        switch.auto_off_start = None
        
        history = SwitchHistory(
            switch_id=switch_id,
            action='OFF',
            timestamp=now_naive,
            duration=duration if duration and duration > 0 else None,
            triggered_by='user',
            user_id=user_id
        )
        db.session.add(history)
    
    db.session.commit()
    
    # Emit socket event - SỬA LẠI PHẦN NÀY
    try:
        from app import socketio
        socketio.emit('switch_update', switch.to_dict(), namespace='/')
        socketio.sleep(0)
    except Exception as e:
        current_app.logger.error(f"Socket emit error: {e}")
    
    return jsonify({'success': True, 'status': new_status})


@api_bp.route('/switch/<int:switch_id>/timer', methods=['POST'])
def set_auto_off_timer(switch_id):
    """Bật switch với hẹn giờ tự tắt"""
    from flask_login import current_user
    
    data = request.json
    minutes = data.get('minutes')
    
    if not minutes or not isinstance(minutes, (int, float)) or minutes < 1:
        return jsonify({'error': 'Invalid minutes'}), 400
    
    switch = Switch.query.get(switch_id)
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    now = get_vietnam_time()
    now_naive = to_naive_vietnam(now)
    
    user_id = current_user.id if hasattr(current_user, 'id') and current_user.is_authenticated else None
    
    switch.status = 'ON'
    switch.last_on = now_naive
    switch.auto_off_minutes = int(minutes)
    switch.auto_off_start = now_naive
    
    history = SwitchHistory(
        switch_id=switch_id,
        action='ON',
        timestamp=now_naive,
        triggered_by='timer',
        user_id=user_id,
        details=json.dumps({'auto_off_minutes': int(minutes)})
    )
    db.session.add(history)
    
    db.session.commit()
    
    # Emit socket event - SỬA LẠI PHẦN NÀY
    try:
        from app import socketio
        socketio.emit('switch_update', switch.to_dict(), namespace='/')
        socketio.sleep(0)
    except Exception as e:
        current_app.logger.error(f"Socket emit error: {e}")
    
    return jsonify({'success': True})

@api_bp.route('/switch/all/off', methods=['POST'])
def turn_off_all():
    """Tắt tất cả switches"""
    from flask_login import current_user
    
    now = get_vietnam_time()
    now_naive = to_naive_vietnam(now)
    switches = Switch.query.filter_by(status='ON').all()
    
    user_id = current_user.id if hasattr(current_user, 'id') and current_user.is_authenticated else None
    
    for switch in switches:
        duration = None
        if switch.last_on:
            last_on_aware = ensure_aware(switch.last_on)
            duration = int((now - last_on_aware).total_seconds())
            if duration > 0:
                switch.uptime = (switch.uptime or 0) + duration
        
        switch.status = 'OFF'
        switch.auto_off_minutes = None
        switch.auto_off_start = None
        
        history = SwitchHistory(
            switch_id=switch.id,
            action='OFF',
            timestamp=now_naive,
            duration=duration if duration and duration > 0 else None,
            triggered_by='user',
            user_id=user_id,
            details=json.dumps({'action': 'turn_off_all'})
        )
        db.session.add(history)
    
    db.session.commit()
    
    # Emit socket event - SỬA LẠI PHẦN NÀY
    try:
        from app import socketio
        socketio.emit('all_switches_off', {}, namespace='/')
        # Gửi từng switch update
        for switch in switches:
            socketio.emit('switch_update', switch.to_dict(), namespace='/')
        socketio.sleep(0)
    except Exception as e:
        current_app.logger.error(f"Socket emit error: {e}")
    
    return jsonify({'success': True})


@api_bp.route('/switches', methods=['GET'])
def get_all_switches():
    """Lấy tất cả switches cho web dashboard"""
    switches = Switch.query.order_by(Switch.id).all()
    
    result = {}
    for switch in switches:
        schedules = Schedule.query.filter_by(switch_id=switch.id, active=True).all()
        
        switch_data = switch.to_dict()
        switch_data['schedules'] = [s.to_dict() for s in schedules]
        result[switch.id] = switch_data
    
    return jsonify(result)


# ============= Schedule APIs =============

@api_bp.route('/switch/<int:switch_id>/schedule', methods=['POST'])
def add_schedule(switch_id):
    """Thêm lịch hẹn"""
    from flask_login import current_user
    from datetime import time as dt_time
    
    data = request.json
    
    switch = Switch.query.get(switch_id)
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    try:
        time_str = data.get('time', '')
        time_parts = time_str.split(':')
        if len(time_parts) < 2:
            raise ValueError("Invalid time format")
        schedule_time = dt_time(int(time_parts[0]), int(time_parts[1]))
    except (ValueError, AttributeError) as e:
        return jsonify({'error': f'Invalid time format: {e}'}), 400
    
    action = data.get('action', '').lower()
    if action not in ['on', 'off']:
        return jsonify({'error': 'Action must be "on" or "off"'}), 400
    
    user_id = current_user.id if hasattr(current_user, 'id') and current_user.is_authenticated else None
    
    schedule = Schedule(
        switch_id=switch_id,
        time=schedule_time,
        action=action,
        auto_off=data.get('auto_off'),
        repeat_type=data.get('repeat', 'once'),
        days_of_week=data.get('days_of_week'),
        created_by=user_id
    )
    
    db.session.add(schedule)
    db.session.commit()
    
    return jsonify({'success': True, 'schedule': schedule.to_dict()})


@api_bp.route('/switch/<int:switch_id>/schedule/<int:schedule_id>', methods=['DELETE'])
def remove_schedule(switch_id, schedule_id):
    """Xóa lịch hẹn"""
    schedule = Schedule.query.filter_by(id=schedule_id, switch_id=switch_id).first()
    
    if not schedule:
        return jsonify({'error': 'Schedule not found'}), 404
    
    db.session.delete(schedule)
    db.session.commit()
    
    return jsonify({'success': True})


@api_bp.route('/switch/<int:switch_id>/schedule/<int:schedule_id>', methods=['PUT'])
def update_schedule(switch_id, schedule_id):
    """Cập nhật lịch hẹn"""
    from datetime import time as dt_time
    
    data = request.json
    schedule = Schedule.query.filter_by(id=schedule_id, switch_id=switch_id).first()
    
    if not schedule:
        return jsonify({'error': 'Schedule not found'}), 404
    
    if 'time' in data:
        try:
            time_str = data['time']
            time_parts = time_str.split(':')
            if len(time_parts) < 2:
                raise ValueError("Invalid time format")
            schedule.time = dt_time(int(time_parts[0]), int(time_parts[1]))
        except (ValueError, AttributeError) as e:
            return jsonify({'error': f'Invalid time format: {e}'}), 400
    
    if 'action' in data:
        action = data['action'].lower()
        if action not in ['on', 'off']:
            return jsonify({'error': 'Action must be "on" or "off"'}), 400
        schedule.action = action
        
    if 'auto_off' in data:
        schedule.auto_off = data['auto_off']
    if 'repeat_type' in data:
        schedule.repeat_type = data['repeat_type']
    if 'days_of_week' in data:
        schedule.days_of_week = data['days_of_week']
    if 'active' in data:
        schedule.active = bool(data['active'])
    
    db.session.commit()
    
    return jsonify({'success': True, 'schedule': schedule.to_dict()})


@api_bp.route('/schedules', methods=['GET'])
def get_all_schedules():
    """Lấy tất cả lịch hẹn"""
    schedules = Schedule.query.join(Switch).order_by(Switch.id, Schedule.time).all()
    
    return jsonify({
        'schedules': [s.to_dict() for s in schedules]
    })


# ============= Node Management APIs =============

@api_bp.route('/switch/<int:switch_id>', methods=['PUT'])
def update_switch(switch_id):
    """Cập nhật thông tin switch"""
    data = request.json
    switch = Switch.query.get(switch_id)
    
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    if 'name' in data:
        switch.name = data['name']
    if 'description' in data:
        switch.description = data['description']
    
    db.session.commit()
    
    return jsonify({'success': True, 'switch': switch.to_dict()})


# ============= History APIs =============

@api_bp.route('/switch/<int:switch_id>/history', methods=['GET'])
def get_switch_history(switch_id):
    """Lấy lịch sử hoạt động của switch"""
    switch = Switch.query.get(switch_id)
    if not switch:
        return jsonify({'error': 'Switch not found'}), 404
    
    limit = request.args.get('limit', 50, type=int)
    history = SwitchHistory.query.filter_by(switch_id=switch_id)\
        .order_by(SwitchHistory.timestamp.desc())\
        .limit(limit)\
        .all()
    
    return jsonify({
        'switch_id': switch_id,
        'history': [h.to_dict() for h in history]
    })


@api_bp.route('/history', methods=['GET'])
def get_all_history():
    """Lấy lịch sử tất cả switches"""
    limit = request.args.get('limit', 100, type=int)
    history = SwitchHistory.query\
        .order_by(SwitchHistory.timestamp.desc())\
        .limit(limit)\
        .all()
    
    return jsonify({
        'history': [h.to_dict() for h in history]
    })