# routes/auth_routes.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from models import db, User, get_vietnam_time

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(username=username).first()
        
        if not user:
            flash('Tên đăng nhập không tồn tại!', 'error')
            return render_template('login.html')
        
        if not user.check_password(password):
            flash('Mật khẩu không đúng!', 'error')
            return render_template('login.html')
        
        if not user.is_approved:
            flash('Tài khoản chưa được phê duyệt. Vui lòng chờ admin xác nhận!', 'warning')
            return render_template('login.html')
        
        # Cập nhật last login
        user.last_login = get_vietnam_time()
        db.session.commit()
        
        login_user(user, remember=remember)
        
        next_page = request.args.get('next')
        if next_page:
            return redirect(next_page)
        
        if user.is_admin:
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('main.dashboard'))
    
    return render_template('login.html')

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if not username or not email or not password:
            flash('Vui lòng điền đầy đủ thông tin!', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp!', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('Mật khẩu phải có ít nhất 6 ký tự!', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại!', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Email đã được sử dụng!', 'error')
            return render_template('register.html')
        
        # Tạo user mới
        user = User(username=username, email=email, is_approved=False)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Đăng ký thành công! Vui lòng chờ admin phê duyệt tài khoản.', 'success')
        return redirect(url_for('auth.login'))
    
    return render_template('register.html')

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Đã đăng xuất thành công!', 'success')
    return redirect(url_for('auth.login'))