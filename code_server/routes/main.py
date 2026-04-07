# routes/main.py
from flask import Blueprint, render_template, jsonify, request, Response, current_app
from flask_login import login_required, current_user
from models import db, Switch, Schedule, SwitchHistory, ActivityStats, get_vietnam_time
from datetime import datetime, timedelta
import csv
import io
import json

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))

@main_bp.route('/dashboard')
@login_required
def dashboard():
    switches = Switch.query.order_by(Switch.id).all()
    return render_template('dashboard.html', switches=switches)

@main_bp.route('/node/<int:node_id>')
@login_required
def node_detail(node_id):
    switch = Switch.query.get_or_404(node_id)
    schedules = Schedule.query.filter_by(switch_id=node_id).order_by(Schedule.time).all()
    
    # Lịch sử 24h gần nhất
    yesterday = get_vietnam_time() - timedelta(days=1)
    history = SwitchHistory.query.filter(
        SwitchHistory.switch_id == node_id,
        SwitchHistory.timestamp >= yesterday
    ).order_by(SwitchHistory.timestamp.desc()).limit(50).all()
    
    return render_template('node_detail.html', switch=switch, schedules=schedules, history=history)

@main_bp.route('/schedules')
@login_required
def schedules():
    all_schedules = Schedule.query.join(Switch).order_by(Switch.id, Schedule.time).all()
    switches = Switch.query.order_by(Switch.id).all()
    return render_template('schedules.html', schedules=all_schedules, switches=switches)

@main_bp.route('/history')
@login_required
def history():
    switches = Switch.query.order_by(Switch.id).all()
    return render_template('history.html', switches=switches)

@main_bp.route('/api/history')
@login_required
def get_history():
    """API lấy lịch sử với bộ lọc"""
    switch_id = request.args.get('switch_id', type=int)
    action = request.args.get('action')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    
    query = SwitchHistory.query
    
    if switch_id:
        query = query.filter_by(switch_id=switch_id)
    
    if action:
        query = query.filter(SwitchHistory.action.like(f'%{action}%'))
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(SwitchHistory.timestamp >= from_date)
        except:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(SwitchHistory.timestamp < to_date)
        except:
            pass
    
    query = query.order_by(SwitchHistory.timestamp.desc())
    
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'history': [h.to_dict() for h in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@main_bp.route('/api/history/export')
@login_required
def export_history():
    """Xuất lịch sử ra CSV"""
    switch_id = request.args.get('switch_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    query = SwitchHistory.query.join(Switch)
    
    if switch_id:
        query = query.filter(SwitchHistory.switch_id == switch_id)
    
    if date_from:
        try:
            from_date = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(SwitchHistory.timestamp >= from_date)
        except:
            pass
    
    if date_to:
        try:
            to_date = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(SwitchHistory.timestamp < to_date)
        except:
            pass
    
    records = query.order_by(SwitchHistory.timestamp.desc()).all()
    
    # Tạo CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['ID', 'Node', 'Hành động', 'Thời gian', 'Thời lượng (giây)', 'Nguồn kích hoạt', 'Chi tiết'])
    
    for record in records:
        writer.writerow([
            record.id,
            record.switch.name if record.switch else '',
            record.action,
            record.timestamp.strftime('%Y-%m-%d %H:%M:%S') if record.timestamp else '',
            record.duration or '',
            record.triggered_by or '',
            record.details or ''
        ])
    
    output.seek(0)
    
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=switch_history_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'}
    )

@main_bp.route('/api/stats/hourly')
@login_required
def get_hourly_stats():
    """Lấy thống kê hoạt động theo giờ"""
    switch_id = request.args.get('switch_id', type=int)
    date_str = request.args.get('date')
    
    if date_str:
        try:
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except:
            target_date = get_vietnam_time().date()
    else:
        target_date = get_vietnam_time().date()
    
    query = ActivityStats.query.filter_by(date=target_date)
    
    if switch_id:
        query = query.filter_by(switch_id=switch_id)
    
    stats = query.order_by(ActivityStats.hour).all()
    
    # Tạo data cho tất cả 24 giờ
    result = {}
    switches = Switch.query.all() if not switch_id else [Switch.query.get(switch_id)]
    
    for switch in switches:
        result[switch.id] = {
            'name': switch.name,
            'data': [0] * 24
        }
    
    for stat in stats:
        if stat.switch_id in result:
            result[stat.switch_id]['data'][stat.hour] = stat.active_minutes
    
    return jsonify({
        'date': target_date.isoformat(),
        'stats': result
    })

@main_bp.route('/api/stats/realtime')
@login_required
def get_realtime_stats():
    """Lấy thống kê realtime cho biểu đồ"""
    # Lấy dữ liệu 1 giờ gần nhất
    now = get_vietnam_time()
    one_hour_ago = now - timedelta(hours=1)
    
    switches = Switch.query.all()
    result = []
    
    for switch in switches:
        # Lấy lịch sử 1 giờ gần nhất
        history = SwitchHistory.query.filter(
            SwitchHistory.switch_id == switch.id,
            SwitchHistory.timestamp >= one_hour_ago
        ).order_by(SwitchHistory.timestamp).all()
        
        result.append({
            'id': switch.id,
            'name': switch.name,
            'status': switch.status,
            'history': [{'time': h.timestamp.strftime('%H:%M:%S'), 'action': h.action} for h in history]
        })
    
    return jsonify({
        'timestamp': now.isoformat(),
        'switches': result
    })

from flask import redirect, url_for