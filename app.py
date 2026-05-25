import os
from datetime import datetime
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Secure key to cryptographically sign session authorization cookies
app.secret_key = "cmech_parts_tracker_secure_session_key_2026"

# --- CONFIGURATION SETTINGS ---
STATIC_PASSWORD = "cmech4480"
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp'}

# --- AUTOMATED DATABASE ENVIRONMENT SWITCHING ---
if os.environ.get('VERCEL') or os.environ.get('PROD'):
    # This is the exact valid string constructed from your Supabase pooler credentials
    raw_uri = "postgresql://postgres.vtyhdivfxqsblgiyeefl:cmech%4044804480@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres?sslmode=require"
    
    if raw_uri.startswith("postgres://"):
        raw_uri = raw_uri.replace("postgres://", "postgresql://", 1)
        
    app.config['SQLALCHEMY_DATABASE_URI'] = raw_uri


else:
    # Offline Local Mode (Your Computer Fallback Storage System)
    DATA_DIR = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(DATA_DIR, 'parts_history.db')}"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Local upload system tracking folders (Fallback rules)
# --- CLOUD SAFE FOLDER CONFIGURATION ---
if os.environ.get('VERCEL'):
    # Use the only writable directory available in serverless environments
    app.config['UPLOAD_FOLDER'] = '/tmp'
    app.config['IMAGE_FOLDER'] = '/tmp'
else:
    # Keeps working perfectly offline on your PC local storage folders
    app.config['UPLOAD_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static', 'uploads')
    app.config['IMAGE_FOLDER'] = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static', 'car_photos')
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['IMAGE_FOLDER'], exist_ok=True)
# ----------------------------------------

db = SQLAlchemy(app)

# Ensure runtime directories exist securely when booting offline
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['IMAGE_FOLDER'], exist_ok=True)


# ----------------------------------------
# DATABASE RELATIONAL SCHEMA MODEL
# ----------------------------------------
class PartPriceHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_model = db.Column(db.String(150), nullable=False, index=True)
    quotation_date = db.Column(db.Date, nullable=False, index=True)
    part_name = db.Column(db.String(300), nullable=False, index=True)
    rate = db.Column(db.Float, nullable=False)
    # Stores photo file path metadata strings
    car_photo = db.Column(db.String(300), nullable=True, default='placeholder.jpg')

# Automatically provision required missing data tables safely
with app.app_context():
    db.create_all()


# Helper validation functions
def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_IMAGE_EXTENSIONS']


# ----------------------------------------
# SECURE INTERCEPTOR AUTHENTICATION GATE
# ----------------------------------------
@app.before_request
def check_authentication():
    """Intercepts incoming client routes to check security token sessions"""
    open_endpoints = ['login', 'static']
    
    if request.endpoint in open_endpoints:
        return None
        
    if not session.get('logged_in'):
        return redirect(url_for('login'))


# ----------------------------------------
# AUTHENTICATION ACCESS CONTROL ENDPOINTS
# ----------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    """The security entry point lock screen validation checkpoint"""
    if session.get('logged_in'):
        return redirect(url_for('models_gallery'))

    if request.method == 'POST':
        input_password = request.form.get('password', '')
        if input_password == STATIC_PASSWORD:
            session['logged_in'] = True
            session.permanent = True  # Preserve browser application session active
            flash("System unlocked successfully.", "success")
            return redirect(url_for('models_gallery'))
        else:
            flash("Invalid master terminal password token.", "danger")
            
    return render_template('login.html')


@app.route('/logout')
def logout():
    """Wipes session memory variables cleanly"""
    session.clear()
    flash("Secure tracking profile disconnected successfully.", "success")
    return redirect(url_for('login'))


# ----------------------------------------
# OPERATIONS TRACKING ENGINE ROUTES
# ----------------------------------------
@app.route('/', methods=['GET'])
def models_gallery():
    """Dashboard Fleet Grid View (Displays 3 unique cards in a row matrix)"""
    unique_batches = db.session.query(
        PartPriceHistory.car_model,
        PartPriceHistory.quotation_date,
        PartPriceHistory.car_photo,
        db.func.count(PartPriceHistory.id).label('total_parts')
    ).group_by(PartPriceHistory.car_model, PartPriceHistory.quotation_date).all()

    return render_template('models.html', unique_batches=unique_batches)


@app.route('/parts', methods=['GET'])
def index():
    """The full multi-parameter inventory table index database engine search page"""
    car_model_query = request.args.get('car_model', '').strip()
    part_query = request.args.get('part_name', '').strip()
    start_date_str = request.args.get('start_date', '').strip()
    end_date_str = request.args.get('end_date', '').strip()

    query = PartPriceHistory.query

    if car_model_query:
        query = query.filter(PartPriceHistory.car_model.ilike(f"%{car_model_query}%"))
    if part_query:
        query = query.filter(PartPriceHistory.part_name.ilike(f"%{part_query}%"))
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            query = query.filter(PartPriceHistory.quotation_date >= start_date)
        except ValueError:
            pass
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            query = query.filter(PartPriceHistory.quotation_date <= end_date)
        except ValueError:
            pass

    results = query.order_by(PartPriceHistory.quotation_date.desc()).all()
    return render_template('index.html', results=results, car_model=car_model_query, 
                           part_name=part_query, start_date=start_date_str, end_date=end_date_str)


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """Ingests form payload packages containing quotation sheets and vehicle graphics"""
    if request.method == 'POST':
        car_model = request.form.get('car_model', '').strip()
        quote_date_str = request.form.get('quotation_date', '').strip()
        file = request.files.get('excel_file')
        image_file = request.files.get('car_photo')

        if not car_model or not quote_date_str or not file or file.filename == '':
            flash("Car Model, Date, and Excel File inputs are mandatory fields!", "danger")
            return redirect(request.url)

        try:
            quotation_date = datetime.strptime(quote_date_str, '%Y-%m-%d').date()
            saved_image_name = 'placeholder.jpg'

            # Save car model graphic if supplied
            if image_file and image_file.filename != '':
                if allowed_image(image_file.filename):
                    image_ext = image_file.filename.rsplit('.', 1)[1].lower()
                    safe_car_name = secure_filename(car_model).lower()
                    saved_image_name = f"{safe_car_name}_{int(datetime.timestamp(datetime.now()))}.{image_ext}"
                    image_file.save(os.path.join(app.config['IMAGE_FOLDER'], saved_image_name))
                else:
                    flash("Invalid format extension. Permitted types: png, jpg, jpeg, webp.", "danger")
                    return redirect(request.url)

            # Ingest data spreadsheet file
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            if filename.endswith('.csv'):
                df = pd.read_csv(filepath)
            else:
                df = pd.read_excel(filepath)

            df.columns = [str(col).strip().lower() for col in df.columns]

            if 'part' not in df.columns or 'rate' not in df.columns:
                flash("Error: Missing column header mapping indicators ('Part' & 'Rate').", "danger")
                os.remove(filepath)
                return redirect(request.url)

            df = df.dropna(subset=['part', 'rate'])

            records_to_add = []
            for _, row in df.iterrows():
                try:
                    rate_val = float(row['rate'])
                except (ValueError, TypeError):
                    continue

                record = PartPriceHistory(
                    car_model=car_model,
                    quotation_date=quotation_date,
                    part_name=str(row['part']).strip(),
                    rate=rate_val,
                    car_photo=saved_image_name
                )
                records_to_add.append(record)
            
            db.session.bulk_save_objects(records_to_add)
            db.session.commit()
            
            if os.path.exists(filepath):
                os.remove(filepath)
            
            flash(f"Successfully processed {len(records_to_add)} parts items linked to '{car_model}'!", "success")
            return redirect(url_for('models_gallery'))

        except Exception as e:
            db.session.rollback()
            flash(f"Extraction pipeline failure: {str(e)}", "danger")
            return redirect(request.url)

    return render_template('upload.html')


# Vercel looks for the global 'app' object. We expose it directly here.
app = app

if __name__ == '__main__':
    # This only runs when you execute 'python app.py' locally on your PC
    app.run(debug=True)