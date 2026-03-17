"""
Main Flask Application for SOLI MICROLINK - Render.com Production Version
"""
import os
import json
import secrets
from werkzeug.exceptions import abort
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
import stripe
import pytz
from sqlalchemy.exc import OperationalError

# Load environment variables from .env file (local development only)
# On Render, these will come from environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__, 
            template_folder='../frontend/templates',
            static_folder='../frontend/static')

# ==================== CONFIGURATION ====================
# Secret Key - MUST be set in Render environment variables
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Database - Use PostgreSQL on Render, SQLite for local development
database_url = os.environ.get('DATABASE_URL', 'sqlite:///simple_solimicrolink.db')

# Fix for Render's PostgreSQL URL (starts with postgres://)
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 300,
    'pool_pre_ping': True,
}

print(f"📁 Database type: {'PostgreSQL' if 'postgresql' in database_url else 'SQLite'}")
print(f"📁 Database URL: {database_url.split('@')[0] if '@' in database_url else database_url}")

# Stripe Configuration - Use environment variables (no defaults in production)
app.config['STRIPE_PUBLIC_KEY'] = os.environ.get('STRIPE_PUBLIC_KEY', '')
app.config['STRIPE_SECRET_KEY'] = os.environ.get('STRIPE_SECRET_KEY', '')
if app.config['STRIPE_SECRET_KEY']:
    stripe.api_key = app.config['STRIPE_SECRET_KEY']

# Email Configuration - Use environment variables only (no hardcoded defaults)
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])

# Admin Email - Use environment variable
app.config['ADMIN_EMAIL'] = os.environ.get('ADMIN_EMAIL', 'admin@soli-microlink.com')

# Base URL - Use Render's external URL in production
app.config['BASE_URL'] = os.environ.get('RENDER_EXTERNAL_URL', os.environ.get('BASE_URL', 'http://localhost:5011'))

# Warn if critical environment variables are missing
if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
    print("⚠️  WARNING: Email credentials not set in environment variables")
if not app.config['STRIPE_SECRET_KEY']:
    print("⚠️  WARNING: Stripe secret key not set in environment variables")
if app.config['SECRET_KEY'] == 'dev-secret-key-change-in-production':
    print("⚠️  WARNING: Using default SECRET_KEY - set a secure one in production!")

print(f"📧 Email configured for: {app.config['MAIL_USERNAME'] or 'Not set'}")
print(f"📧 Admin email: {app.config['ADMIN_EMAIL']}")
print(f"💳 Stripe configured: {'Yes' if app.config['STRIPE_PUBLIC_KEY'] else 'No'}")
print(f"🌐 Base URL: {app.config['BASE_URL']}")

# ===== TEMPLATE FILTERS =====
@app.template_filter('from_json')
def from_json(value):
    """Convert JSON string to Python object"""
    if value:
        try:
            return json.loads(value)
        except:
            return []
    return []

# ==================== INITIALIZE EXTENSIONS ====================
db = SQLAlchemy(app)
mail = Mail(app)

# ==================== DATABASE MODELS ====================

class User(db.Model):
    """User accounts for customers"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    is_verified = db.Column(db.Boolean, default=False)
    verification_token = db.Column(db.String(100), unique=True)
    reset_token = db.Column(db.String(100), unique=True)
    reset_token_expiry = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relationships
    bookings = db.relationship('Booking', back_populates='user_rel', lazy=True)
    reviews = db.relationship('Review', back_populates='user_rel', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def generate_verification_token(self):
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token
    
    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
        return self.reset_token

class Teacher(db.Model):
    """Teacher model for STEM faculty"""
    __tablename__ = 'teachers'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    subject = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(50), nullable=False)
    rating = db.Column(db.Float, default=0.0)
    reviews_count = db.Column(db.Integer, default=0)
    bio = db.Column(db.Text)
    photo_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    availabilities = db.relationship('TeacherAvailability', back_populates='teacher', lazy=True, cascade='all, delete-orphan')
    teacher_bookings = db.relationship('Booking', back_populates='teacher_rel', lazy=True, foreign_keys='Booking.teacher_id')
    teacher_reviews = db.relationship('Review', back_populates='teacher_rel', lazy=True, foreign_keys='Review.teacher_id')

class TeacherAvailability(db.Model):
    """Teacher availability for bookings"""
    __tablename__ = 'teacher_availability'
    
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    day_of_week = db.Column(db.Integer)  # 0-6 (Monday-Sunday)
    start_time = db.Column(db.String(5))  # HH:MM format
    end_time = db.Column(db.String(5))    # HH:MM format
    is_recurring = db.Column(db.Boolean, default=True)
    specific_date = db.Column(db.Date, nullable=True)  # For non-recurring
    is_blocked = db.Column(db.Boolean, default=False)  # For blocking specific slots
    
    # Relationship
    teacher = db.relationship('Teacher', back_populates='availabilities')

class Service(db.Model):
    """Services (courses, tutoring, research)"""
    __tablename__ = 'services'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(50), nullable=False)  # data, research, training
    subcategory = db.Column(db.String(50))  # e.g., 'python', 'thesis', 'ai-ml'
    price = db.Column(db.Float, nullable=False)
    discounted_price = db.Column(db.Float, nullable=True)
    duration_hours = db.Column(db.Float, default=1.0)  # Session duration
    features = db.Column(db.Text)  # JSON string of features
    is_popular = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String(500))
    rating = db.Column(db.Float, default=0.0)  # Average rating
    reviews_count = db.Column(db.Integer, default=0)  # Number of reviews
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    service_bookings = db.relationship('Booking', back_populates='service_rel', lazy=True, foreign_keys='Booking.service_id')
    service_reviews = db.relationship('Review', back_populates='service_rel', lazy=True, foreign_keys='Review.service_id')

class Booking(db.Model):
    """Booking records"""
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20))
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    booking_type = db.Column(db.String(20), nullable=False)  # service, teacher, consultation
    booking_date = db.Column(db.Date, nullable=False)
    booking_time = db.Column(db.String(5), nullable=False)  # HH:MM
    end_time = db.Column(db.String(5))  # HH:MM
    duration_hours = db.Column(db.Float, default=1.0)
    amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, completed, cancelled
    payment_status = db.Column(db.String(20), default='unpaid')  # unpaid, paid, refunded
    payment_intent_id = db.Column(db.String(100))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user_rel = db.relationship('User', back_populates='bookings')
    service_rel = db.relationship('Service', back_populates='service_bookings')
    teacher_rel = db.relationship('Teacher', back_populates='teacher_bookings')

class CartItem(db.Model):
    """Shopping cart items"""
    __tablename__ = 'cart_items'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100), nullable=True)  # Flask session ID (null for logged-in users)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    item_type = db.Column(db.String(20), nullable=False)  # service, teacher_booking
    quantity = db.Column(db.Integer, default=1)
    price = db.Column(db.Float, nullable=False)
    booking_date = db.Column(db.Date, nullable=True)
    booking_time = db.Column(db.String(5), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    service = db.relationship('Service')
    teacher = db.relationship('Teacher')
    user = db.relationship('User')

class Review(db.Model):
    """Customer reviews"""
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    customer_email = db.Column(db.String(100))
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    user_rel = db.relationship('User', back_populates='reviews')
    service_rel = db.relationship('Service', back_populates='service_reviews')
    teacher_rel = db.relationship('Teacher', back_populates='teacher_reviews')

class TimeBlock(db.Model):
    """Blocked time slots (admin only)"""
    __tablename__ = 'time_blocks'
    
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=True)
    block_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    reason = db.Column(db.String(200))
    created_by = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship
    teacher = db.relationship('Teacher')

class Admin(db.Model):
    """Admin users"""
    __tablename__ = 'admins'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_super = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Setting(db.Model):
    """Website settings for header and footer"""
    __tablename__ = 'settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='text')  # text, image, json
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ==================== NEW MODELS FOR ADDITIONAL PAGES ====================

class FAQ(db.Model):
    """Frequently Asked Questions"""
    __tablename__ = 'faqs'
    
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500), nullable=False)
    answer = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default='general')
    order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Policy(db.Model):
    """Policies and Terms"""
    __tablename__ = 'policies'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    content = db.Column(db.Text, nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = db.Column(db.String(20), default='1.0')
    is_active = db.Column(db.Boolean, default=True)

class AboutUs(db.Model):
    """About Us page content"""
    __tablename__ = 'about_us'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), default='About SOLI MICROLINK')
    content = db.Column(db.Text, nullable=False)
    mission = db.Column(db.Text)
    vision = db.Column(db.Text)
    values = db.Column(db.Text)  # JSON array
    team_members = db.Column(db.Text)  # JSON array
    stats = db.Column(db.Text)  # JSON object
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Location(db.Model):
    """Location and contact information"""
    __tablename__ = 'locations'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), default='Main Office')
    address = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    country = db.Column(db.String(100))
    postal_code = db.Column(db.String(20))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    hours = db.Column(db.Text)  # JSON object
    is_primary = db.Column(db.Boolean, default=True)
    map_embed_url = db.Column(db.Text)

# ==================== DATABASE INITIALIZATION ====================

def init_db():
    """Initialize database - create tables if they don't exist"""
    with app.app_context():
        try:
            # Create all tables
            db.create_all()
            print("✅ Database tables created/verified")
            
            # Check if admin exists
            admin = Admin.query.filter_by(username='admin').first()
            if not admin:
                admin = Admin(username='admin')
                admin.set_password('Admin123!')
                db.session.add(admin)
                db.session.commit()
                print("✅ Admin user created")
            else:
                print("✅ Admin user exists")
            
            # Check for training services
            training_count = Service.query.filter_by(category='training').count()
            print(f"✅ Training services in database: {training_count}")
            
            if training_count == 0:
                print("⚠️ No training services found! You may need to add them.")
            else:
                print("✅ Training services found:")
                for s in Service.query.filter_by(category='training').all():
                    print(f"   - {s.name} (ID: {s.id}, Subcategory: {s.subcategory})")
                
        except Exception as e:
            print(f"❌ Database initialization error: {e}")

# Run database initialization
init_db()

# ==================== DECORATORS ====================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Please login as admin to access this page.', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ==================== HELPER FUNCTIONS ====================

def generate_booking_number():
    """Generate unique booking number"""
    import random
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_num = random.randint(1000, 9999)
    return f"BK-{timestamp}-{random_num}"

def send_verification_email(user):
    """Send email verification link"""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        print("⚠️ Email not configured - skipping verification email")
        return False
        
    token = user.generate_verification_token()
    db.session.commit()
    
    verification_url = f"{app.config['BASE_URL']}/verify-email/{token}"
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #002868, #1a4c7a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .button {{ display: inline-block; background: #BF0A30; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Welcome to SOLI MICROLINK!</h1>
            </div>
            <div class="content">
                <h2>Hello {user.full_name},</h2>
                <p>Thank you for registering with SOLI MICROLINK! Please verify your email address to activate your account.</p>
                <p>Click the button below to verify your email:</p>
                <div style="text-align: center;">
                    <a href="{verification_url}" class="button">Verify Email Address</a>
                </div>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{verification_url}</p>
                <p>This link will expire in 48 hours.</p>
                <p>If you didn't create an account with SOLI MICROLINK, please ignore this email.</p>
            </div>
            <div class="footer">
                <p>&copy; 2026 SOLI MICROLINK. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        msg = Message(
            subject='Verify Your SOLI MICROLINK Account',
            recipients=[user.email],
            html=html_body
        )
        mail.send(msg)
        print(f"✅ Verification email sent to {user.email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def send_welcome_email(user):
    """Send welcome email after verification"""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        return False
        
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #002868, #1a4c7a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .features {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; margin: 20px 0; }}
            .feature {{ background: white; padding: 15px; border-radius: 10px; text-align: center; }}
            .button {{ display: inline-block; background: #BF0A30; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Welcome to SOLI MICROLINK, {user.full_name}!</h1>
            </div>
            <div class="content">
                <p>Your email has been verified successfully. You now have full access to:</p>
                
                <div class="features">
                    <div class="feature">
                        <h3>📚 Courses</h3>
                        <p>Access all data analytics and research courses</p>
                    </div>
                    <div class="feature">
                        <h3>👨‍🏫 Expert Teachers</h3>
                        <p>Book sessions with PhD-level instructors</p>
                    </div>
                    <div class="feature">
                        <h3>📝 Research Support</h3>
                        <p>Thesis and paper writing assistance</p>
                    </div>
                </div>
                
                <div style="text-align: center;">
                    <a href="{app.config['BASE_URL']}/teachers" class="button">Browse Teachers</a>
                    <a href="{app.config['BASE_URL']}/data-analytics" class="button" style="background: #002868;">Explore Courses</a>
                </div>
            </div>
            <div class="footer">
                <p>&copy; 2026 SOLI MICROLINK. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        msg = Message(
            subject='Welcome to SOLI MICROLINK!',
            recipients=[user.email],
            html=html_body
        )
        mail.send(msg)
        print(f"✅ Welcome email sent to {user.email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def send_password_reset_email(user):
    """Send password reset link"""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        return False
        
    token = user.generate_reset_token()
    db.session.commit()
    
    reset_url = f"{app.config['BASE_URL']}/reset-password/{token}"
    
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #002868, #1a4c7a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .button {{ display: inline-block; background: #BF0A30; color: white; padding: 12px 30px; text-decoration: none; border-radius: 30px; margin: 20px 0; }}
            .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Password Reset Request</h1>
            </div>
            <div class="content">
                <h2>Hello {user.full_name},</h2>
                <p>We received a request to reset your password for your SOLI MICROLINK account.</p>
                <p>Click the button below to reset your password:</p>
                <div style="text-align: center;">
                    <a href="{reset_url}" class="button">Reset Password</a>
                </div>
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666;">{reset_url}</p>
                <p>This link will expire in 24 hours.</p>
                <p>If you didn't request a password reset, please ignore this email or contact support if you have concerns.</p>
            </div>
            <div class="footer">
                <p>&copy; 2026 SOLI MICROLINK. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    try:
        msg = Message(
            subject='Reset Your SOLI MICROLINK Password',
            recipients=[user.email],
            html=html_body
        )
        mail.send(msg)
        print(f"✅ Password reset email sent to {user.email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def send_booking_notification(booking):
    """Send email notification for new booking"""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        return False
        
    try:
        subject = f"New Booking Confirmation - {booking.booking_number}"
        
        # Get service/teacher details
        item_name = "Consultation"
        if booking.service_rel:
            item_name = booking.service_rel.name
        elif booking.teacher_rel:
            item_name = f"Session with {booking.teacher_rel.name}"
        
        html_body = f"""
        <h2>New Booking Received</h2>
        <p><strong>Booking #:</strong> {booking.booking_number}</p>
        <p><strong>Customer:</strong> {booking.customer_name}</p>
        <p><strong>Email:</strong> {booking.customer_email}</p>
        <p><strong>Phone:</strong> {booking.customer_phone or 'Not provided'}</p>
        <p><strong>Service:</strong> {item_name}</p>
        <p><strong>Date:</strong> {booking.booking_date.strftime('%B %d, %Y')}</p>
        <p><strong>Time:</strong> {booking.booking_time}</p>
        <p><strong>Duration:</strong> {booking.duration_hours} hour(s)</p>
        <p><strong>Amount:</strong> ${booking.amount}</p>
        <p><strong>Status:</strong> {booking.status}</p>
        <p><strong>Payment:</strong> {booking.payment_status}</p>
        <p><strong>Notes:</strong> {booking.notes or 'None'}</p>
        <hr>
        <p><a href="{app.config['BASE_URL']}/admin/booking/{booking.id}">View in Admin Panel</a></p>
        """
        
        msg = Message(
            subject=subject,
            recipients=[app.config['ADMIN_EMAIL']],
            html=html_body
        )
        mail.send(msg)
        print(f"✅ Booking notification sent to admin")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def send_booking_confirmation(booking):
    """Send booking confirmation to customer"""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        return False
        
    try:
        # Get service/teacher details
        item_name = "Consultation"
        if booking.service_rel:
            item_name = booking.service_rel.name
        elif booking.teacher_rel:
            item_name = f"Session with {booking.teacher_rel.name}"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #002868, #1a4c7a); color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .details {{ background: white; padding: 20px; border-radius: 10px; margin: 20px 0; }}
                .button {{ display: inline-block; background: #BF0A30; color: white; padding: 10px 25px; text-decoration: none; border-radius: 30px; }}
                .footer {{ text-align: center; margin-top: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Booking Confirmed!</h1>
                </div>
                <div class="content">
                    <h2>Thank you for your booking, {booking.customer_name}!</h2>
                    <p>Your booking has been confirmed. Here are the details:</p>
                    
                    <div class="details">
                        <p><strong>Booking #:</strong> {booking.booking_number}</p>
                        <p><strong>Service:</strong> {item_name}</p>
                        <p><strong>Date:</strong> {booking.booking_date.strftime('%B %d, %Y')}</p>
                        <p><strong>Time:</strong> {booking.booking_time}</p>
                        <p><strong>Duration:</strong> {booking.duration_hours} hour(s)</p>
                        <p><strong>Amount:</strong> ${booking.amount}</p>
                    </div>
                    
                    <p>You can view your bookings in your <a href="{app.config['BASE_URL']}/profile">profile</a>.</p>
                    
                    <p>If you have any questions, please contact us at <a href="mailto:{app.config['ADMIN_EMAIL']}">{app.config['ADMIN_EMAIL']}</a></p>
                </div>
                <div class="footer">
                    <p>&copy; 2026 SOLI MICROLINK. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        msg = Message(
            subject=f'Booking Confirmation - {booking.booking_number}',
            recipients=[booking.customer_email],
            html=html_body
        )
        mail.send(msg)
        print(f"✅ Booking confirmation sent to {booking.customer_email}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def get_available_slots(teacher_id=None, service_id=None, date=None):
    """Get available time slots for a given teacher/service and date"""
    if not date:
        date = datetime.now().date()
    
    # Default business hours (9 AM - 8 PM)
    all_slots = []
    for hour in range(9, 20):  # 9 AM to 8 PM
        for minute in [0, 30]:  # 30-minute intervals
            time_str = f"{hour:02d}:{minute:02d}"
            all_slots.append(time_str)
    
    # Get booked slots
    booked_slots = []
    if teacher_id:
        bookings = Booking.query.filter(
            Booking.teacher_id == teacher_id,
            Booking.booking_date == date,
            Booking.status.in_(['confirmed', 'pending'])
        ).all()
        for booking in bookings:
            booked_slots.append(booking.booking_time)
    
    # Get blocked slots
    blocked_slots = []
    blocks = TimeBlock.query.filter(
        TimeBlock.block_date == date
    ).all()
    for block in blocks:
        current = datetime.strptime(block.start_time, '%H:%M')
        end = datetime.strptime(block.end_time, '%H:%M')
        while current < end:
            time_str = current.strftime('%H:%M')
            blocked_slots.append(time_str)
            current += timedelta(minutes=30)
    
    # Filter available slots (not booked, not blocked)
    available_slots = [slot for slot in all_slots 
                      if slot not in booked_slots 
                      and slot not in blocked_slots]
    
    return available_slots

# ==================== CONTEXT PROCESSORS ====================

@app.context_processor
def inject_cart_count():
    """Get cart count for current user or session with error handling"""
    cart_count = 0
    try:
        if 'user_id' in session:
            # Logged in user - get cart items by user_id
            cart_count = CartItem.query.filter_by(user_id=session['user_id']).count()
        elif 'cart_id' in session:
            # Guest user - get cart items by session_id
            cart_count = CartItem.query.filter_by(session_id=session['cart_id']).count()
    except Exception as e:
        # Any error - return 0
        print(f"Error getting cart count: {e}")
        cart_count = 0
    
    return dict(cart_items_count=cart_count)

@app.context_processor
def inject_now():
    return {'now': datetime.now}

@app.context_processor
def inject_settings():
    """Inject settings into all templates with error handling"""
    settings_dict = {}
    try:
        settings = Setting.query.all()
        settings_dict = {s.key: s.value for s in settings}
        
        # Parse JSON settings
        for key in ['nav_links', 'portfolio_links', 'footer_links']:
            if key in settings_dict and settings_dict[key]:
                try:
                    settings_dict[key] = json.loads(settings_dict[key])
                except:
                    settings_dict[key] = []
        
        # Add Stripe public key for templates
        settings_dict['stripe_publishable_key'] = app.config['STRIPE_PUBLIC_KEY']
    except Exception as e:
        print(f"Error loading settings: {e}")
        settings_dict = {'stripe_publishable_key': app.config['STRIPE_PUBLIC_KEY']}
    
    return dict(settings=settings_dict)

# ==================== USER ACCOUNT ROUTES ====================

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration page"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        full_name = request.form.get('full_name')
        phone = request.form.get('phone')
        
        # Validation
        if not email or not password or not full_name:
            flash('Please fill in all required fields', 'danger')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('register'))
        
        # Check if user exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered. Please login.', 'warning')
            return redirect(url_for('login'))
        
        # Create new user
        user = User(
            email=email,
            full_name=full_name,
            phone=phone
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        # Send verification email
        if send_verification_email(user):
            flash('Registration successful! Please check your email to verify your account.', 'success')
        else:
            flash('Registration successful! However, we could not send verification email. Please contact support.', 'warning')
        
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User login page"""
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)
        
        user = User.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            if not user.is_verified:
                flash('Please verify your email before logging in. Check your inbox for the verification link.', 'warning')
                return redirect(url_for('login'))
            
            # Update last login
            user.last_login = datetime.utcnow()
            
            # Transfer cart items from session to user
            if 'cart_id' in session:
                cart_items = CartItem.query.filter_by(session_id=session['cart_id']).all()
                for item in cart_items:
                    item.user_id = user.id
                    item.session_id = None
                db.session.commit()
            
            session['user_id'] = user.id
            session['user_name'] = user.full_name
            session['user_email'] = user.email
            session.permanent = remember
            
            flash(f'Welcome back, {user.full_name}!', 'success')
            
            # Redirect to previous page or home
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """User logout"""
    session.pop('user_id', None)
    session.pop('user_name', None)
    session.pop('user_email', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))

@app.route('/verify-email/<token>')
def verify_email(token):
    """Verify user email"""
    user = User.query.filter_by(verification_token=token).first()
    
    if not user:
        flash('Invalid or expired verification link', 'danger')
        return redirect(url_for('login'))
    
    if user.is_verified:
        flash('Email already verified. Please login.', 'info')
        return redirect(url_for('login'))
    
    user.is_verified = True
    user.verification_token = None
    db.session.commit()
    
    # Send welcome email
    send_welcome_email(user)
    
    flash('Email verified successfully! You can now login.', 'success')
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """Forgot password page"""
    if request.method == 'POST':
        email = request.form.get('email')
        
        user = User.query.filter_by(email=email).first()
        
        if user:
            if send_password_reset_email(user):
                flash('Password reset link sent to your email', 'success')
            else:
                flash('Could not send reset email. Please try again later.', 'danger')
        else:
            # Don't reveal that email doesn't exist
            flash('If that email is registered, you will receive a password reset link', 'info')
        
        return redirect(url_for('login'))
    
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Reset password page"""
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or user.reset_token_expiry < datetime.utcnow():
        flash('Invalid or expired reset link', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return redirect(url_for('reset_password', token=token))
        
        user.set_password(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        flash('Password reset successful! You can now login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', token=token)

@app.route('/profile')
@login_required
def profile():
    """User profile page"""
    user = User.query.get(session['user_id'])
    bookings = Booking.query.filter_by(user_id=user.id).order_by(Booking.created_at.desc()).all()
    reviews = Review.query.filter_by(user_id=user.id).all()
    
    return render_template('profile.html', user=user, bookings=bookings, reviews=reviews)

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    """Update user profile"""
    user = User.query.get(session['user_id'])
    
    user.full_name = request.form.get('full_name')
    user.phone = request.form.get('phone')
    
    db.session.commit()
    session['user_name'] = user.full_name
    flash('Profile updated successfully', 'success')
    return redirect(url_for('profile'))

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Change user password"""
    user = User.query.get(session['user_id'])
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not user.check_password(current_password):
        flash('Current password is incorrect', 'danger')
        return redirect(url_for('profile'))
    
    if new_password != confirm_password:
        flash('New passwords do not match', 'danger')
        return redirect(url_for('profile'))
    
    user.set_password(new_password)
    db.session.commit()
    
    flash('Password changed successfully', 'success')
    return redirect(url_for('profile'))

@app.route('/subscribe')
def subscribe_page():
    """Subscription plans page"""
    return render_template('subscribe.html')

# ==================== MAIN PAGE ROUTES ====================

@app.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@app.route('/teachers')
def teachers_page():
    """STEM faculty page"""
    teachers = Teacher.query.filter_by(is_active=True).all()
    return render_template('teachers.html', teachers=teachers)

@app.route('/data-analytics')
def data_analytics_page():
    """Data Analytics page"""
    services = Service.query.filter_by(category='data', is_active=True).all()
    return render_template('Data_Analytics.html', services=services)

@app.route('/research-support')
def research_support_page():
    """Research Support page"""
    services = Service.query.filter_by(category='research', is_active=True).all()
    return render_template('Research_Support.html', services=services)

# ==================== NEW PAGE ROUTES ====================

@app.route('/faq')
def faq_page():
    """Frequently Asked Questions page"""
    faqs = FAQ.query.filter_by(is_active=True).order_by(FAQ.order).all()
    
    # Group by category
    categories = {}
    for faq in faqs:
        if faq.category not in categories:
            categories[faq.category] = []
        categories[faq.category].append(faq)
    
    return render_template('faq.html', categories=categories)

@app.route('/policies/<slug>')
def policy_page(slug):
    """Policy page (terms, privacy, refund)"""
    policy = Policy.query.filter_by(slug=slug, is_active=True).first_or_404()
    return render_template('policy.html', policy=policy)

@app.route('/policies')
def policies_list():
    """List all policies"""
    policies = Policy.query.filter_by(is_active=True).all()
    return render_template('policies.html', policies=policies)

@app.route('/about')
def about_page():
    """About Us page"""
    about = AboutUs.query.first()
    if not about:
        about = AboutUs(
            content="SOLI MICROLINK is a premier educational platform dedicated to empowering students and professionals through high-quality training in data analytics, research support, and expert tutoring."
        )
    
    # Parse JSON fields
    values = []
    team = []
    stats = {}
    
    if about.values:
        try:
            values = json.loads(about.values)
        except:
            values = []
    
    if about.team_members:
        try:
            team = json.loads(about.team_members)
        except:
            team = []
    
    if about.stats:
        try:
            stats = json.loads(about.stats)
        except:
            stats = {}
    
    return render_template('about.html', about=about, values=values, team=team, stats=stats)

@app.route('/contact')
def contact_page():
    """Contact and Location page"""
    locations = Location.query.filter_by(is_primary=True).all()
    return render_template('contact.html', locations=locations) 

# ==================== BOOKING & CART ROUTES ====================

@app.route('/add-to-cart', methods=['POST'])
def add_to_cart():
    """Add item to cart with fixed error handling"""
    try:
        print("\n=== ADD TO CART DEBUG ===")
        print(f"Form data: {dict(request.form)}")
        print(f"Session: user_id={session.get('user_id')}, cart_id={session.get('cart_id')}")
        
        item_type = request.form.get('item_type')
        item_id = request.form.get('item_id')
        booking_date = request.form.get('booking_date')
        booking_time = request.form.get('booking_time')
        
        print(f"item_type: {item_type}, item_id: {item_id}")
        
        # Validation
        if not item_type or not item_id:
            return jsonify({'success': False, 'error': 'Missing item type or ID'}), 400
        
        # Convert item_id to integer
        try:
            item_id = int(item_id)
        except ValueError:
            return jsonify({'success': False, 'error': f'Invalid item ID: {item_id}'}), 400
        
        # Get or create session ID for guest users
        session_id = None
        if 'user_id' not in session:
            if 'cart_id' not in session:
                session['cart_id'] = secrets.token_hex(16)
                print(f"Created new cart_id: {session['cart_id']}")
            session_id = session['cart_id']
            print(f"Guest user, using session_id: {session_id}")
        else:
            print(f"Logged in user, user_id: {session['user_id']}")
        
        price = 0
        item_name = ""
        
        if item_type == 'service':
            # Get service
            service = Service.query.get(item_id)
            if not service:
                return jsonify({'success': False, 'error': f'Service with ID {item_id} not found'}), 404
            
            if not service.is_active:
                return jsonify({'success': False, 'error': f'Service {service.name} is not available'}), 400
            
            price = service.discounted_price or service.price
            item_name = service.name
            print(f"Found service: {item_name}, price: {price}")
            
            # Check if already in cart
            if 'user_id' in session:
                existing = CartItem.query.filter_by(
                    user_id=session['user_id'],
                    service_id=item_id,
                    item_type='service'
                ).first()
            else:
                existing = CartItem.query.filter_by(
                    session_id=session_id,
                    service_id=item_id,
                    item_type='service'
                ).first()
            
            if existing:
                print(f"Item already in cart, increasing quantity")
                existing.quantity += 1
            else:
                print(f"Adding new item to cart")
                cart_item = CartItem(
                    session_id=session_id,  # Will be None for logged-in users
                    user_id=session.get('user_id'),
                    service_id=item_id,
                    item_type='service',
                    quantity=1,
                    price=price
                )
                db.session.add(cart_item)
        
        elif item_type == 'teacher':
            # Get teacher
            teacher = Teacher.query.get(item_id)
            if not teacher:
                return jsonify({'success': False, 'error': f'Teacher with ID {item_id} not found'}), 404
            
            if not teacher.is_active:
                return jsonify({'success': False, 'error': f'Teacher {teacher.name} is not available'}), 400
            
            price = 75  # Default hourly rate for teachers
            item_name = f"Session with {teacher.name}"
            print(f"Found teacher: {teacher.name}")
            
            # Parse booking date if provided
            parsed_date = None
            if booking_date:
                try:
                    parsed_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
                except ValueError:
                    return jsonify({'success': False, 'error': f'Invalid date format: {booking_date}'}), 400
            
            cart_item = CartItem(
                session_id=session_id,  # Will be None for logged-in users
                user_id=session.get('user_id'),
                teacher_id=item_id,
                item_type='teacher_booking',
                quantity=1,
                price=price,
                booking_date=parsed_date,
                booking_time=booking_time
            )
            db.session.add(cart_item)
        
        else:
            return jsonify({'success': False, 'error': f'Invalid item type: {item_type}'}), 400
        
        # Commit changes
        db.session.commit()
        print("Database commit successful")
        
        # Get updated cart count
        if 'user_id' in session:
            cart_count = CartItem.query.filter_by(user_id=session['user_id']).count()
            print(f"Logged in user cart count: {cart_count}")
        else:
            cart_count = CartItem.query.filter_by(session_id=session_id).count()
            print(f"Guest user cart count: {cart_count}")
        
        print(f"=== END ADD TO CART - SUCCESS ===\n")
        
        return jsonify({
            'success': True,
            'message': f'Added {item_name} to cart',
            'cart_count': cart_count
        })
        
    except Exception as e:
        db.session.rollback()
        import traceback
        error_msg = str(e)
        traceback_str = traceback.format_exc()
        print(f"\n❌ ERROR in add_to_cart: {error_msg}")
        print(f"Traceback: {traceback_str}")
        return jsonify({
            'success': False, 
            'error': f'Internal server error: {error_msg}'
        }), 500

@app.route('/cart')
def view_cart():
    """View shopping cart"""
    cart_items = []
    
    if 'user_id' in session:
        # Logged in user
        cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    elif 'cart_id' in session:
        # Guest user
        cart_items = CartItem.query.filter_by(session_id=session['cart_id']).all()
    else:
        # No cart
        session['cart_id'] = secrets.token_hex(16)
    
    total = sum(item.price * item.quantity for item in cart_items)
    
    return render_template('cart.html', cart_items=cart_items, total=total)

@app.route('/update-cart/<int:item_id>', methods=['POST'])
def update_cart(item_id):
    """Update cart item quantity"""
    cart_item = CartItem.query.get_or_404(item_id)
    
    # Verify ownership
    if 'user_id' in session:
        if cart_item.user_id != session['user_id']:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    else:
        if cart_item.session_id != session.get('cart_id'):
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    action = request.form.get('action')
    if action == 'increase':
        cart_item.quantity += 1
    elif action == 'decrease':
        cart_item.quantity -= 1
        if cart_item.quantity <= 0:
            db.session.delete(cart_item)
    elif action == 'remove':
        db.session.delete(cart_item)
    
    db.session.commit()
    
    # Get updated cart count
    if 'user_id' in session:
        cart_count = CartItem.query.filter_by(user_id=session['user_id']).count()
    else:
        cart_count = CartItem.query.filter_by(session_id=session['cart_id']).count()
    
    return jsonify({'success': True, 'cart_count': cart_count})

@app.route('/cart-count')
def cart_count():
    """Get current cart count (for AJAX updates)"""
    try:
        if 'user_id' in session:
            count = CartItem.query.filter_by(user_id=session['user_id']).count()
        elif 'cart_id' in session:
            count = CartItem.query.filter_by(session_id=session['cart_id']).count()
        else:
            count = 0
    except:
        count = 0
    
    return jsonify({'count': count})

@app.route('/checkout')
def checkout():
    """Checkout page"""
    if 'user_id' in session:
        cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    elif 'cart_id' in session:
        cart_items = CartItem.query.filter_by(session_id=session['cart_id']).all()
    else:
        cart_items = []
    
    if not cart_items:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('view_cart'))
    
    total = sum(item.price * item.quantity for item in cart_items)
    
    return render_template(
        'checkout.html',
        cart_items=cart_items,
        total=total,
        stripe_publishable_key=app.config['STRIPE_PUBLIC_KEY']
    )

@app.route('/process-checkout', methods=['POST'])
def process_checkout():
    """Process checkout and create booking"""
    if 'user_id' in session:
        cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
        user = User.query.get(session['user_id'])
        customer_name = user.full_name
        customer_email = user.email
        customer_phone = user.phone
    elif 'cart_id' in session:
        cart_items = CartItem.query.filter_by(session_id=session['cart_id']).all()
        customer_name = request.form.get('customer_name')
        customer_email = request.form.get('customer_email')
        customer_phone = request.form.get('customer_phone')
    else:
        cart_items = []
    
    if not cart_items:
        flash('Your cart is empty', 'warning')
        return redirect(url_for('view_cart'))
    
    notes = request.form.get('notes', '')
    
    # Calculate total
    total = sum(item.price * item.quantity for item in cart_items)
    
    # Create booking for each cart item
    bookings = []
    for item in cart_items:
        booking_number = generate_booking_number()
        
        booking = Booking(
            booking_number=booking_number,
            user_id=session.get('user_id'),
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            service_id=item.service_id,
            teacher_id=item.teacher_id,
            booking_type=item.item_type,
            booking_date=item.booking_date or datetime.now().date(),
            booking_time=item.booking_time or '09:00',
            amount=item.price * item.quantity,
            notes=notes
        )
        db.session.add(booking)
        bookings.append(booking)
        
        # Send notification to admin
        send_booking_notification(booking)
        
        # Send confirmation to customer
        send_booking_confirmation(booking)
    
    # Clear cart
    for item in cart_items:
        db.session.delete(item)
    db.session.commit()
    
    flash('Booking confirmed! Check your email for details.', 'success')
    return redirect(url_for('booking_confirmation', booking_id=bookings[0].id))

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    """Create Stripe checkout session"""
    try:
        # Get cart items
        if 'user_id' in session:
            cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
        elif 'cart_id' in session:
            cart_items = CartItem.query.filter_by(session_id=session['cart_id']).all()
        else:
            return jsonify({'error': 'No cart found'}), 400
        
        if not cart_items:
            return jsonify({'error': 'Cart is empty'}), 400
        
        # Create line items for Stripe
        line_items = []
        for item in cart_items:
            if item.service:
                name = item.service.name
            elif item.teacher:
                name = f"Session with {item.teacher.name}"
            else:
                name = "Consultation"
            
            line_items.append({
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': name,
                    },
                    'unit_amount': int(item.price * 100),  # Stripe uses cents
                },
                'quantity': item.quantity,
            })
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=url_for('payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('checkout', _external=True),
        )
        
        return jsonify({'id': checkout_session.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/payment-success')
def payment_success():
    """Handle successful payment"""
    session_id = request.args.get('session_id')
    
    if not session_id:
        flash('Payment successful! Your booking is being processed.', 'success')
        return redirect(url_for('index'))
    
    try:
        # Retrieve the checkout session
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        
        flash('Payment successful! Your booking is confirmed.', 'success')
        return redirect(url_for('index'))
    except:
        flash('Payment successful! Your booking is being processed.', 'success')
        return redirect(url_for('index'))

@app.route('/booking-confirmation/<int:booking_id>')
def booking_confirmation(booking_id):
    """Booking confirmation page"""
    booking = Booking.query.get_or_404(booking_id)
    return render_template('booking_confirmation.html', booking=booking)

@app.route('/get-available-slots')
def get_slots():
    """API endpoint to get available time slots"""
    teacher_id = request.args.get('teacher_id')
    service_id = request.args.get('service_id')
    date_str = request.args.get('date')
    
    try:
        date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        date = datetime.now().date()
    
    slots = get_available_slots(teacher_id, service_id, date)
    return jsonify({'slots': slots})

# ==================== REVIEW ROUTES ====================

@app.route('/submit-review', methods=['POST'])
def submit_review():
    """Submit a new review"""
    try:
        service_id = request.form.get('service_id')
        teacher_id = request.form.get('teacher_id')
        customer_name = request.form.get('customer_name')
        customer_email = request.form.get('customer_email')
        rating = request.form.get('rating')
        comment = request.form.get('comment')
        
        # Validate required fields
        if not customer_name or not rating or not comment:
            return jsonify({'success': False, 'error': 'Please fill in all required fields'}), 400
        
        # Create review
        review = Review(
            user_id=session.get('user_id'),
            customer_name=customer_name,
            customer_email=customer_email,
            service_id=service_id if service_id else None,
            teacher_id=teacher_id if teacher_id else None,
            rating=int(rating),
            comment=comment,
            status='pending'
        )
        
        db.session.add(review)
        db.session.commit()
        
        # Send email notification to admin
        try:
            subject = f"New Review Submitted - Rating: {rating} stars"
            html_body = f"""
            <h2>New Review Submitted</h2>
            <p><strong>Reviewer:</strong> {customer_name}</p>
            <p><strong>Email:</strong> {customer_email or 'Not provided'}</p>
            <p><strong>Rating:</strong> {rating} stars</p>
            <p><strong>Comment:</strong> {comment}</p>
            <p><strong>Status:</strong> Pending Moderation</p>
            <hr>
            <p><a href="{app.config['BASE_URL']}/admin/reviews">View in Admin Panel</a></p>
            """
            
            msg = Message(
                subject=subject,
                recipients=[app.config['ADMIN_EMAIL']],
                html=html_body
            )
            mail.send(msg)
            print(f"✅ Review notification sent to admin")
        except Exception as e:
            print(f"❌ Email error: {e}")
        
        return jsonify({'success': True, 'message': 'Thank you for your review! It will be published after moderation.'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get-reviews', methods=['GET'])
def get_reviews():
    """Get approved reviews for a service or teacher with rating info"""
    service_id = request.args.get('service_id')
    teacher_id = request.args.get('teacher_id')
    
    query = Review.query.filter_by(status='approved')
    
    rating_info = {'average': 0, 'count': 0}
    
    if service_id:
        query = query.filter_by(service_id=service_id)
        # Get service rating info
        service = Service.query.get(service_id)
        if service:
            rating_info = {
                'average': service.rating or 0,
                'count': service.reviews_count or 0
            }
    elif teacher_id:
        query = query.filter_by(teacher_id=teacher_id)
        # Get teacher rating info
        teacher = Teacher.query.get(teacher_id)
        if teacher:
            rating_info = {
                'average': teacher.rating or 0,
                'count': teacher.reviews_count or 0
            }
    
    reviews = query.order_by(Review.created_at.desc()).limit(10).all()
    
    reviews_data = []
    for review in reviews:
        reviews_data.append({
            'id': review.id,
            'customer_name': review.customer_name,
            'rating': review.rating,
            'comment': review.comment,
            'created_at': review.created_at.strftime('%B %d, %Y')
        })
    
    return jsonify({
        'reviews': reviews_data,
        'rating_info': rating_info
    })

# ==================== NEW ADMIN ROUTES (FAQs, Policies, About, Locations) ====================

# FAQ Admin Routes
@app.route('/admin/faqs')
@admin_required
def admin_faqs():
    """Manage FAQs"""
    faqs = FAQ.query.order_by(FAQ.order).all()
    return render_template('admin/faqs.html', faqs=faqs)

@app.route('/admin/faqs/add', methods=['GET', 'POST'])
@admin_required
def admin_add_faq():
    """Add new FAQ"""
    if request.method == 'POST':
        faq = FAQ(
            question=request.form.get('question'),
            answer=request.form.get('answer'),
            category=request.form.get('category'),
            order=int(request.form.get('order', 0))
        )
        db.session.add(faq)
        db.session.commit()
        flash('FAQ added successfully', 'success')
        return redirect(url_for('admin_faqs'))
    return render_template('admin/faq_form.html')

@app.route('/admin/faqs/edit/<int:faq_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_faq(faq_id):
    """Edit FAQ"""
    faq = FAQ.query.get_or_404(faq_id)
    if request.method == 'POST':
        faq.question = request.form.get('question')
        faq.answer = request.form.get('answer')
        faq.category = request.form.get('category')
        faq.order = int(request.form.get('order', 0))
        faq.is_active = 'is_active' in request.form
        db.session.commit()
        flash('FAQ updated successfully', 'success')
        return redirect(url_for('admin_faqs'))
    return render_template('admin/faq_form.html', faq=faq)

@app.route('/admin/faqs/delete/<int:faq_id>', methods=['POST'])
@admin_required
def admin_delete_faq(faq_id):
    """Delete FAQ"""
    faq = FAQ.query.get_or_404(faq_id)
    db.session.delete(faq)
    db.session.commit()
    flash('FAQ deleted successfully', 'success')
    return redirect(url_for('admin_faqs'))

# Policy Admin Routes
@app.route('/admin/policies')
@admin_required
def admin_policies():
    """Manage policies"""
    policies = Policy.query.all()
    return render_template('admin/policies.html', policies=policies)

@app.route('/admin/policies/add', methods=['GET', 'POST'])
@admin_required
def admin_add_policy():
    """Add new policy"""
    if request.method == 'POST':
        policy = Policy(
            title=request.form.get('title'),
            slug=request.form.get('slug'),
            content=request.form.get('content'),
            version=request.form.get('version', '1.0')
        )
        db.session.add(policy)
        db.session.commit()
        flash('Policy added successfully', 'success')
        return redirect(url_for('admin_policies'))
    return render_template('admin/policy_form.html')

@app.route('/admin/policies/edit/<int:policy_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_policy(policy_id):
    """Edit policy"""
    policy = Policy.query.get_or_404(policy_id)
    if request.method == 'POST':
        policy.title = request.form.get('title')
        policy.slug = request.form.get('slug')
        policy.content = request.form.get('content')
        policy.version = request.form.get('version', '1.0')
        policy.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Policy updated successfully', 'success')
        return redirect(url_for('admin_policies'))
    return render_template('admin/policy_form.html', policy=policy)


# ==================== TRAINING PROGRAM ROUTES ====================

@app.route('/training')
def training_page():
    """Training programs overview page"""
    services = Service.query.filter_by(category='training', is_active=True).all()
    return render_template('training.html', services=services)

@app.route('/training/ai-ml')
def training_ai_ml():
    """AI & Machine Learning detail page"""
    print("\n=== DEBUG: training_ai_ml route called ===")
    
    # Try multiple ways to find the service
    service = Service.query.filter_by(name='AI & Machine Learning', is_active=True).first()
    print(f"Search by name 'AI & Machine Learning': {service is not None}")
    
    if not service:
        service = Service.query.filter_by(subcategory='ai-ml', category='training', is_active=True).first()
        print(f"Search by subcategory 'ai-ml': {service is not None}")
    
    if not service:
        # Let's see what training services exist
        all_training = Service.query.filter_by(category='training').all()
        print(f"All training services in DB: {[(s.id, s.name, s.subcategory) for s in all_training]}")
        abort(404)
    
    print(f"Found service: ID={service.id}, Name={service.name}")
    return render_template('training_detail.html', service=service)

@app.route('/training/power-platform')
def training_power_platform():
    """Microsoft Power Platform detail page"""
    print("\n=== DEBUG: training_power_platform route called ===")
    
    service = Service.query.filter_by(name='Microsoft Power Platform', is_active=True).first()
    print(f"Search by name 'Microsoft Power Platform': {service is not None}")
    
    if not service:
        service = Service.query.filter_by(subcategory='power-platform', category='training', is_active=True).first()
        print(f"Search by subcategory 'power-platform': {service is not None}")
    
    if not service:
        all_training = Service.query.filter_by(category='training').all()
        print(f"All training services in DB: {[(s.id, s.name, s.subcategory) for s in all_training]}")
        abort(404)
    
    print(f"Found service: ID={service.id}, Name={service.name}")
    return render_template('training_detail.html', service=service)

@app.route('/training/cybersecurity')
def training_cybersecurity():
    """Cybersecurity detail page"""
    print("\n=== DEBUG: training_cybersecurity route called ===")
    
    service = Service.query.filter_by(name='Cybersecurity', is_active=True).first()
    print(f"Search by name 'Cybersecurity': {service is not None}")
    
    if not service:
        service = Service.query.filter_by(subcategory='cybersecurity', category='training', is_active=True).first()
        print(f"Search by subcategory 'cybersecurity': {service is not None}")
    
    if not service:
        all_training = Service.query.filter_by(category='training').all()
        print(f"All training services in DB: {[(s.id, s.name, s.subcategory) for s in all_training]}")
        abort(404)
    
    print(f"Found service: ID={service.id}, Name={service.name}")
    return render_template('training_detail.html', service=service)

@app.route('/test-training/<int:service_id>')
def test_training(service_id):
    """Test route to directly load a training service by ID"""
    service = Service.query.get(service_id)
    if not service or service.category != 'training':
        return f"Service {service_id} not found or not training", 404
    
    return f"""
    <h1>Test Training Page</h1>
    <p>Service ID: {service.id}</p>
    <p>Name: {service.name}</p>
    <p>Category: {service.category}</p>
    <p>Subcategory: {service.subcategory}</p>
    <p>Active: {service.is_active}</p>
    <p><a href="/training/{service.subcategory}">Try regular route</a></p>
    <p><a href="/training/ai-ml">Try AI ML route</a></p>
    """

@app.route('/admin/policies/delete/<int:policy_id>', methods=['POST'])
@admin_required
def admin_delete_policy(policy_id):
    """Delete policy"""
    policy = Policy.query.get_or_404(policy_id)
    db.session.delete(policy)
    db.session.commit()
    flash('Policy deleted successfully', 'success')
    return redirect(url_for('admin_policies'))

# About Us Admin Routes
@app.route('/admin/about')
@admin_required
def admin_about():
    """Edit About Us page"""
    about = AboutUs.query.first()
    if not about:
        about = AboutUs(content='')
    return render_template('admin/about_form.html', about=about)

@app.route('/admin/about/update', methods=['POST'])
@admin_required
def admin_update_about():
    """Update About Us content"""
    about = AboutUs.query.first()
    if not about:
        about = AboutUs()
    
    about.title = request.form.get('title')
    about.content = request.form.get('content')
    about.mission = request.form.get('mission')
    about.vision = request.form.get('vision')
    
    # Handle JSON fields
    values = request.form.get('values', '').split('\n')
    about.values = json.dumps([v.strip() for v in values if v.strip()])
    
    db.session.add(about)
    db.session.commit()
    flash('About Us page updated successfully', 'success')
    return redirect(url_for('admin_about'))

# Location Admin Routes
@app.route('/admin/locations')
@admin_required
def admin_locations():
    """Manage locations"""
    locations = Location.query.all()
    return render_template('admin/locations.html', locations=locations)

@app.route('/admin/locations/add', methods=['GET', 'POST'])
@admin_required
def admin_add_location():
    """Add new location"""
    if request.method == 'POST':
        location = Location(
            name=request.form.get('name'),
            address=request.form.get('address'),
            city=request.form.get('city'),
            state=request.form.get('state'),
            country=request.form.get('country'),
            postal_code=request.form.get('postal_code'),
            latitude=float(request.form.get('latitude')) if request.form.get('latitude') else None,
            longitude=float(request.form.get('longitude')) if request.form.get('longitude') else None,
            phone=request.form.get('phone'),
            email=request.form.get('email'),
            map_embed_url=request.form.get('map_embed_url'),
            is_primary='is_primary' in request.form
        )
        
        # Handle hours
        hours = {}
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
            hours[day] = request.form.get(f'hours_{day}')
        location.hours = json.dumps(hours)
        
        db.session.add(location)
        db.session.commit()
        flash('Location added successfully', 'success')
        return redirect(url_for('admin_locations'))
    return render_template('admin/location_form.html')

@app.route('/admin/locations/edit/<int:location_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_location(location_id):
    """Edit location"""
    location = Location.query.get_or_404(location_id)
    if request.method == 'POST':
        location.name = request.form.get('name')
        location.address = request.form.get('address')
        location.city = request.form.get('city')
        location.state = request.form.get('state')
        location.country = request.form.get('country')
        location.postal_code = request.form.get('postal_code')
        location.latitude = float(request.form.get('latitude')) if request.form.get('latitude') else None
        location.longitude = float(request.form.get('longitude')) if request.form.get('longitude') else None
        location.phone = request.form.get('phone')
        location.email = request.form.get('email')
        location.map_embed_url = request.form.get('map_embed_url')
        location.is_primary = 'is_primary' in request.form
        
        # Handle hours
        hours = {}
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
            hours[day] = request.form.get(f'hours_{day}')
        location.hours = json.dumps(hours)
        
        db.session.commit()
        flash('Location updated successfully', 'success')
        return redirect(url_for('admin_locations'))
    
    # Parse hours for template
    hours_dict = json.loads(location.hours) if location.hours else {}
    return render_template('admin/location_form.html', location=location, hours=hours_dict)

@app.route('/admin/locations/delete/<int:location_id>', methods=['POST'])
@admin_required
def admin_delete_location(location_id):
    """Delete location"""
    location = Location.query.get_or_404(location_id)
    db.session.delete(location)
    db.session.commit()
    flash('Location deleted successfully', 'success')
    return redirect(url_for('admin_locations'))

# ==================== EXISTING ADMIN ROUTES ====================
# (All your original admin routes from your working app.py go here)
# Copy and paste ALL your existing admin routes from your old app.py below

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and admin.check_password(password):
            session['is_admin'] = True
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            flash('Logged in successfully', 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session.pop('is_admin', None)
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    # Get counts
    teacher_count = Teacher.query.count()
    service_count = Service.query.count()
    booking_count = Booking.query.count()
    user_count = User.query.count()
    pending_reviews = Review.query.filter_by(status='pending').count()
    
    # Recent bookings
    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(10).all()
    
    # Recent users
    recent_users = User.query.order_by(User.created_at.desc()).limit(10).all()
    
    return render_template(
        'admin/dashboard.html',
        teacher_count=teacher_count,
        service_count=service_count,
        booking_count=booking_count,
        user_count=user_count,
        pending_reviews=pending_reviews,
        recent_bookings=recent_bookings,
        recent_users=recent_users
    )

# ==================== ADMIN - USER MANAGEMENT ====================

@app.route('/admin/users')
@admin_required
def admin_users():
    """Manage users"""
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/<int:user_id>')
@admin_required
def admin_user_detail(user_id):
    """View user details"""
    user = User.query.get_or_404(user_id)
    bookings = Booking.query.filter_by(user_id=user.id).order_by(Booking.created_at.desc()).all()
    reviews = Review.query.filter_by(user_id=user.id).all()
    return render_template('admin/user_detail.html', user=user, bookings=bookings, reviews=reviews)

@app.route('/admin/users/<int:user_id>/update-status', methods=['POST'])
@admin_required
def admin_update_user_status(user_id):
    """Update user status"""
    user = User.query.get_or_404(user_id)
    action = request.form.get('action')
    
    if action == 'verify':
        user.is_verified = True
        user.verification_token = None
        flash(f'User {user.email} verified successfully', 'success')
    elif action == 'unverify':
        user.is_verified = False
        flash(f'User {user.email} unverified', 'success')
    
    db.session.commit()
    return redirect(url_for('admin_user_detail', user_id=user_id))

@app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    """Delete user"""
    user = User.query.get_or_404(user_id)
    email = user.email
    
    # Delete related records
    Booking.query.filter_by(user_id=user.id).delete()
    CartItem.query.filter_by(user_id=user.id).delete()
    Review.query.filter_by(user_id=user.id).update({Review.user_id: None})
    
    db.session.delete(user)
    db.session.commit()
    
    flash(f'User {email} deleted successfully', 'success')
    return redirect(url_for('admin_users'))

# ==================== ADMIN - TEACHER MANAGEMENT ====================

@app.route('/admin/teachers')
@admin_required
def admin_teachers():
    """Manage teachers"""
    teachers = Teacher.query.all()
    return render_template('admin/teachers.html', teachers=teachers)

@app.route('/admin/teachers/add', methods=['GET', 'POST'])
@admin_required
def admin_add_teacher():
    """Add new teacher"""
    if request.method == 'POST':
        name = request.form.get('name')
        subject = request.form.get('subject')
        department = request.form.get('department')
        bio = request.form.get('bio')
        rating = request.form.get('rating', 0.0)
        photo_url = request.form.get('photo_url')
        
        teacher = Teacher(
            name=name,
            subject=subject,
            department=department,
            bio=bio,
            rating=float(rating),
            photo_url=photo_url if photo_url else None
        )
        
        db.session.add(teacher)
        db.session.commit()
        
        flash('Teacher added successfully', 'success')
        return redirect(url_for('admin_teachers'))
    
    return render_template('admin/teacher_form.html')

@app.route('/admin/teachers/edit/<int:teacher_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_teacher(teacher_id):
    """Edit teacher"""
    teacher = Teacher.query.get_or_404(teacher_id)
    
    if request.method == 'POST':
        teacher.name = request.form.get('name')
        teacher.subject = request.form.get('subject')
        teacher.department = request.form.get('department')
        teacher.bio = request.form.get('bio')
        teacher.rating = float(request.form.get('rating', 0.0))
        teacher.photo_url = request.form.get('photo_url')
        teacher.is_active = 'is_active' in request.form
        
        db.session.commit()
        flash('Teacher updated successfully', 'success')
        return redirect(url_for('admin_teachers'))
    
    return render_template('admin/teacher_form.html', teacher=teacher)

@app.route('/admin/teachers/delete/<int:teacher_id>', methods=['POST'])
@admin_required
def admin_delete_teacher(teacher_id):
    """Delete teacher"""
    teacher = Teacher.query.get_or_404(teacher_id)
    db.session.delete(teacher)
    db.session.commit()
    flash('Teacher deleted successfully', 'success')
    return redirect(url_for('admin_teachers'))

# ==================== ADMIN - SERVICE MANAGEMENT ====================

@app.route('/admin/services')
@admin_required
def admin_services():
    """Manage services"""
    services = Service.query.all()
    return render_template('admin/services.html', services=services)

@app.route('/admin/services/add', methods=['GET', 'POST'])
@admin_required
def admin_add_service():
    """Add new service"""
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        category = request.form.get('category')
        subcategory = request.form.get('subcategory')
        price = float(request.form.get('price'))
        discounted_price = request.form.get('discounted_price')
        duration_hours = float(request.form.get('duration_hours', 1))
        
        # Process features (from textarea, one per line)
        features_text = request.form.get('features', '')
        features_list = [f.strip() for f in features_text.split('\n') if f.strip()]
        features_json = json.dumps(features_list)
        
        service = Service(
            name=name,
            description=description,
            category=category,
            subcategory=subcategory,
            price=price,
            discounted_price=float(discounted_price) if discounted_price else None,
            duration_hours=duration_hours,
            features=features_json,
            is_popular='is_popular' in request.form
        )
        
        db.session.add(service)
        db.session.commit()
        
        flash('Service added successfully', 'success')
        return redirect(url_for('admin_services'))
    
    return render_template('admin/service_form.html')

@app.route('/admin/services/edit/<int:service_id>', methods=['GET', 'POST'])
@admin_required
def admin_edit_service(service_id):
    """Edit service"""
    service = Service.query.get_or_404(service_id)
    
    if request.method == 'POST':
        service.name = request.form.get('name')
        service.description = request.form.get('description')
        service.category = request.form.get('category')
        service.subcategory = request.form.get('subcategory')
        service.price = float(request.form.get('price'))
        service.discounted_price = float(request.form.get('discounted_price')) if request.form.get('discounted_price') else None
        service.duration_hours = float(request.form.get('duration_hours', 1))
        service.is_active = 'is_active' in request.form
        service.is_popular = 'is_popular' in request.form
        
        # Process features
        features_text = request.form.get('features', '')
        features_list = [f.strip() for f in features_text.split('\n') if f.strip()]
        service.features = json.dumps(features_list)
        
        db.session.commit()
        flash('Service updated successfully', 'success')
        return redirect(url_for('admin_services'))
    
    return render_template('admin/service_form.html', service=service)

@app.route('/admin/services/delete/<int:service_id>', methods=['POST'])
@admin_required
def admin_delete_service(service_id):
    """Delete service"""
    service = Service.query.get_or_404(service_id)
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted successfully', 'success')
    return redirect(url_for('admin_services'))

# ==================== ADMIN - BOOKING MANAGEMENT ====================

@app.route('/admin/bookings')
@admin_required
def admin_bookings():
    """Manage bookings"""
    status_filter = request.args.get('status', 'all')
    
    query = Booking.query
    
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    bookings = query.order_by(Booking.booking_date.desc(), Booking.booking_time.desc()).all()
    
    return render_template('admin/bookings.html', bookings=bookings, status_filter=status_filter)

@app.route('/admin/booking/<int:booking_id>')
@admin_required
def admin_booking_detail(booking_id):
    """View booking details"""
    booking = Booking.query.get_or_404(booking_id)
    return render_template('admin/booking_detail.html', booking=booking)

@app.route('/admin/booking/<int:booking_id>/update-status', methods=['POST'])
@admin_required
def admin_update_booking_status(booking_id):
    """Update booking status"""
    booking = Booking.query.get_or_404(booking_id)
    
    status = request.form.get('status')
    payment_status = request.form.get('payment_status')
    
    if status:
        booking.status = status
    if payment_status:
        booking.payment_status = payment_status
    
    db.session.commit()
    flash('Booking updated successfully', 'success')
    return redirect(url_for('admin_booking_detail', booking_id=booking_id))

@app.route('/admin/booking/<int:booking_id>/delete', methods=['POST'])
@admin_required
def admin_delete_booking(booking_id):
    """Delete booking"""
    booking = Booking.query.get_or_404(booking_id)
    db.session.delete(booking)
    db.session.commit()
    flash('Booking deleted successfully', 'success')
    return redirect(url_for('admin_bookings'))

# ==================== ADMIN - TIME BLOCKING ====================

@app.route('/admin/time-blocks')
@admin_required
def admin_time_blocks():
    """Manage time blocks"""
    blocks = TimeBlock.query.order_by(TimeBlock.block_date.desc(), TimeBlock.start_time).all()
    teachers = Teacher.query.all()
    return render_template('admin/time_blocks.html', blocks=blocks, teachers=teachers)

@app.route('/admin/time-blocks/add', methods=['POST'])
@admin_required
def admin_add_time_block():
    """Add new time block"""
    try:
        teacher_id = request.form.get('teacher_id')
        if teacher_id == '':
            teacher_id = None
        elif teacher_id:
            teacher_id = int(teacher_id)
        
        block_date = datetime.strptime(request.form.get('block_date'), '%Y-%m-%d').date()
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        reason = request.form.get('reason', '')
        
        # Validate time format
        try:
            start = datetime.strptime(start_time, '%H:%M')
            end = datetime.strptime(end_time, '%H:%M')
        except ValueError:
            flash('Invalid time format. Please use HH:MM format.', 'danger')
            return redirect(url_for('admin_time_blocks'))
        
        # Calculate duration
        duration = (end - start).seconds / 3600
        if duration < 0:
            duration += 24
            
        # Validate 2-hour minimum
        if duration < 2:
            flash(f'Time block must be at least 2 hours. Current duration: {duration:.1f} hours', 'danger')
            return redirect(url_for('admin_time_blocks'))
        
        # Check for overlapping blocks
        query = TimeBlock.query.filter(
            TimeBlock.block_date == block_date
        )
        
        if teacher_id:
            query = query.filter(
                (TimeBlock.teacher_id == teacher_id) | (TimeBlock.teacher_id.is_(None))
            )
        
        existing_blocks = query.all()
        
        for block in existing_blocks:
            block_start = datetime.strptime(block.start_time, '%H:%M')
            block_end = datetime.strptime(block.end_time, '%H:%M')
            
            if block_end <= block_start:
                block_end += timedelta(days=1)
            
            check_start = start
            check_end = end
            if check_end <= check_start:
                check_end += timedelta(days=1)
            
            # Check for overlap
            if (check_start < block_end and check_end > block_start):
                flash('This time block overlaps with an existing block', 'danger')
                return redirect(url_for('admin_time_blocks'))
        
        # Create new time block
        block = TimeBlock(
            teacher_id=teacher_id,
            block_date=block_date,
            start_time=start_time,
            end_time=end_time,
            reason=reason,
            created_by=session.get('admin_username', 'admin')
        )
        
        db.session.add(block)
        db.session.commit()
        
        flash('Time block added successfully', 'success')
    except Exception as e:
        flash(f'Error adding time block: {str(e)}', 'danger')
    
    return redirect(url_for('admin_time_blocks'))

@app.route('/admin/time-blocks/delete/<int:block_id>', methods=['POST'])
@admin_required
def admin_delete_time_block(block_id):
    """Delete time block"""
    block = TimeBlock.query.get_or_404(block_id)
    db.session.delete(block)
    db.session.commit()
    flash('Time block removed successfully', 'success')
    return redirect(url_for('admin_time_blocks'))

# ==================== ADMIN - REVIEW MANAGEMENT ====================

def update_service_rating(service_id):
    """Update service average rating and review count"""
    service = Service.query.get(service_id)
    if service:
        approved_reviews = Review.query.filter_by(
            service_id=service_id, 
            status='approved'
        ).all()
        if approved_reviews:
            total_rating = sum(r.rating for r in approved_reviews)
            service.rating = total_rating / len(approved_reviews)
            service.reviews_count = len(approved_reviews)
        else:
            service.rating = 0
            service.reviews_count = 0
        db.session.commit()

def update_teacher_rating(teacher_id):
    """Update teacher average rating and review count"""
    teacher = Teacher.query.get(teacher_id)
    if teacher:
        approved_reviews = Review.query.filter_by(
            teacher_id=teacher_id, 
            status='approved'
        ).all()
        if approved_reviews:
            total_rating = sum(r.rating for r in approved_reviews)
            teacher.rating = total_rating / len(approved_reviews)
            teacher.reviews_count = len(approved_reviews)
        else:
            teacher.rating = 0
            teacher.reviews_count = 0
        db.session.commit()

@app.route('/admin/reviews')
@admin_required
def admin_reviews():
    """Manage reviews"""
    status_filter = request.args.get('status', 'pending')
    
    query = Review.query
    
    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    
    reviews = query.order_by(Review.created_at.desc()).all()
    
    return render_template('admin/reviews.html', reviews=reviews, status_filter=status_filter)

@app.route('/admin/review/<int:review_id>/update-status', methods=['POST'])
@admin_required
def admin_update_review_status(review_id):
    """Update review status and recalculate ratings"""
    review = Review.query.get_or_404(review_id)
    
    status = request.form.get('status')
    review.status = status
    
    db.session.commit()
    
    # Update ratings if status changed to/from approved
    if review.service_id:
        update_service_rating(review.service_id)
    elif review.teacher_id:
        update_teacher_rating(review.teacher_id)
    
    flash(f'Review {status} successfully', 'success')
    return redirect(url_for('admin_reviews'))

@app.route('/admin/review/<int:review_id>/delete', methods=['POST'])
@admin_required
def admin_delete_review(review_id):
    """Delete review and update ratings"""
    review = Review.query.get_or_404(review_id)
    
    service_id = review.service_id
    teacher_id = review.teacher_id
    
    db.session.delete(review)
    db.session.commit()
    
    # Update ratings after deletion
    if service_id:
        update_service_rating(service_id)
    elif teacher_id:
        update_teacher_rating(teacher_id)
    
    flash('Review deleted successfully', 'success')
    return redirect(url_for('admin_reviews'))

# ==================== ADMIN - SETTINGS MANAGEMENT ====================

@app.route('/admin/settings')
@admin_required
def admin_settings():
    """Manage website settings"""
    settings = Setting.query.all()
    settings_dict = {s.key: s for s in settings}
    return render_template('admin/settings.html', settings=settings_dict)

@app.route('/admin/settings/update', methods=['POST'])
@admin_required
def admin_update_settings():
    """Update website settings"""
    try:
        # Header settings
        header_settings = {
            'site_name': request.form.get('site_name', 'SOLI MICROLINK'),
            'site_tagline': request.form.get('site_tagline', ''),
            'logo_url': request.form.get('logo_url', ''),
        }
        
        # Navigation links
        nav_links = []
        for i in range(1, 7):
            name = request.form.get(f'nav_{i}_name')
            url = request.form.get(f'nav_{i}_url')
            icon = request.form.get(f'nav_{i}_icon', 'fas fa-link')
            if name and url:
                nav_links.append({'name': name, 'url': url, 'icon': icon})
        
        header_settings['nav_links'] = json.dumps(nav_links)
        
        # Portfolio links (keep empty)
        portfolio_links = []
        header_settings['portfolio_links'] = json.dumps(portfolio_links)
        
        # Footer settings
        footer_settings = {
            'footer_description': request.form.get('footer_description', ''),
            'footer_email': request.form.get('footer_email', 'info@soli-microlink.com'),
            'footer_phone': request.form.get('footer_phone', ''),
            'footer_address': request.form.get('footer_address', ''),
            'copyright_text': request.form.get('copyright_text', '© 2026 SOLI MICROLINK. All rights reserved.'),
            'footer_bg_color': request.form.get('footer_bg_color', '#1a2c3e'),
            'facebook_url': request.form.get('facebook_url', '#'),
            'twitter_url': request.form.get('twitter_url', '#'),
            'linkedin_url': request.form.get('linkedin_url', '#'),
            'instagram_url': request.form.get('instagram_url', '#'),
            'github_url': request.form.get('github_url', '#'),
        }
        
        # Footer links
        footer_links = []
        for i in range(1, 7):
            name = request.form.get(f'footer_link_{i}_name')
            url = request.form.get(f'footer_link_{i}_url')
            if name and url:
                footer_links.append({'name': name, 'url': url})
        
        footer_settings['footer_links'] = json.dumps(footer_links)
        
        # Save all settings
        all_settings = {**header_settings, **footer_settings}
        
        for key, value in all_settings.items():
            setting = Setting.query.filter_by(key=key).first()
            if setting:
                setting.value = value
            else:
                setting = Setting(key=key, value=value)
                db.session.add(setting)
        
        db.session.commit()
        flash('Settings updated successfully', 'success')
    except Exception as e:
        flash(f'Error updating settings: {str(e)}', 'danger')
    
    return redirect(url_for('admin_settings'))

# Print all registered routes for debugging
print("\n" + "="*60)
print("REGISTERED ROUTES:")
print("="*60)
for rule in app.url_map.iter_rules():
    if 'training' in str(rule):
        print(f"✅ {rule}")
    else:
        print(f"   {rule}")
print("="*60)

# ==================== RUN APPLICATION ====================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5011))
    # Use debug=False in production on Render
    app.run(debug=False, host='0.0.0.0', port=port)
