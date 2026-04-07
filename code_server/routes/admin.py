# routes/admin.py
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from functools import wraps
from models import db, User, Switch, SwitchHistory, get_vietnam_time

admin_bp = Blueprint('admin', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Bạn không có quyền truy cập trang này!', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/')
@login_required
@admin_required
def dashboard():
    users = User.query.all()
    switches = Switch.query.all()
    pending_users = User.query.filter_by(is_approved=False).count()
    
    # Thống kê
    total_history = SwitchHistory.query.count()
    active_switches = Switch.query.filter_by(status='ON').count()
    
    return render_template('admin/dashboard.html', 
                         users=users, 
                         switches=switches,
                         pending_users=pending_users,
                         total_history=total_history,
                         active_switches=active_switches)

@admin_bp.route('/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)

@admin_bp.route('/user/<int:user_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    db.session.commit()
    
    return jsonify({'success': True})

@admin_bp.route('/user/<int:user_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.is_admin:
        return jsonify({'error': 'Cannot delete admin user'}), 400
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({'success': True})

@admin_bp.route('/user/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot modify your own admin status'}), 400
    
    user.is_admin = not user.is_admin
    db.session.commit()
    
    return jsonify({'success': True, 'is_admin': user.is_admin})

@admin_bp.route('/user/<int:user_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if user.id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400
    
    if user.is_admin:
        return jsonify({'error': 'Cannot delete admin user'}), 400
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({'success': True})

@admin_bp.route('/api/stats')
@login_required
@admin_required
def get_admin_stats():
    """Lấy thống kê cho admin dashboard"""
    from datetime import timedelta
    
    now = get_vietnam_time()
    today = now.date()
    
    # Thống kê người dùng
    total_users = User.query.count()
    pending_users = User.query.filter_by(is_approved=False).count()
    active_today = User.query.filter(
        User.last_login >= now - timedelta(days=1)
    ).count()
    
    # Thống kê switches
    total_switches = Switch.query.count()
    active_switches = Switch.query.filter_by(status='ON').count()
    
    # Thống kê lịch sử
    history_today = SwitchHistory.query.filter(
        SwitchHistory.timestamp >= today
    ).count()
    
    return jsonify({
        'users': {
            'total': total_users,
            'pending': pending_users,
            'active_today': active_today
        },
        'switches': {
            'total': total_switches,
            'active': active_switches
        },
        'history': {
            'today': history_today
        }
    })