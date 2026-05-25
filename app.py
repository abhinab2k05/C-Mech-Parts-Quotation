import os
from datetime import datetime
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "car_parts_tracker_secret_key"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///parts_history.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Separate folders for temporary sheets vs permanent image uploads
app.config['UPLOAD_FOLDER'] = './uploads'
app.config['IMAGE_FOLDER'] = os.path.join('static', 'car_photos')
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp'}

db = SQLAlchemy(app)

# Ensure required runtime storage directories exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['IMAGE_FOLDER'], exist_ok=True)

# ----------------------------------------
# 1. UPDATED DATABASE SCHEMA MODEL
# ----------------------------------------
class PartPriceHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    car_model = db.Column(db.String(150), nullable=False, index=True)
    quotation_date = db.Column(db.Date, nullable=False, index=True)
    part_name = db.Column(db.String(300), nullable=False, index=True)
    rate = db.Column(db.Float, nullable=False)
    car_photo = db.Column(db.String(300), nullable=True, default='placeholder.jpg') # Stores photo filename

with app.app_context():
    db.create_all()

# Helper to check image types
def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_IMAGE_EXTENSIONS']

# ----------------------------------------
# 2. ROUTES & LOGIC
# ----------------------------------------

@app.route('/', methods=['GET'])
def index():
    """Primary parts engine list with multi-parameter filter cards"""
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


@app.route('/models', methods=['GET'])
def models_gallery():
    """NEW ROUTE: Distinct unique Car Models grouped with images and counts"""
    # Group results by Car Model and take the most recent image profile path assignment
    unique_cars = db.session.query(
        PartPriceHistory.car_model,
        PartPriceHistory.car_photo,
        db.func.count(PartPriceHistory.id).label('total_parts')
    ).group_by(PartPriceHistory.car_model).all()

    return render_template('models.html', unique_cars=unique_cars)


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """Enhanced to accept an optional Car Profile Image attachment alongside the sheet"""
    if request.method == 'POST':
        car_model = request.form.get('car_model', '').strip()
        quote_date_str = request.form.get('quotation_date', '').strip()
        file = request.files.get('excel_file')
        image_file = request.files.get('car_photo')

        if not car_model or not quote_date_str or not file or file.filename == '':
            flash("Car Model, Date, and Excel File are mandatory fields!", "danger")
            return redirect(request.url)

        try:
            quotation_date = datetime.strptime(quote_date_str, '%Y-%m-%d').date()
            
            # Default fallback image filename
            saved_image_name = 'placeholder.jpg'

            # Process image if provided by user
            if image_file and image_file.filename != '':
                if allowed_image(image_file.filename):
                    image_ext = image_file.filename.rsplit('.', 1)[1].lower()
                    # Secure filename combining car model string naming rules safely
                    safe_car_name = secure_filename(car_model).lower()
                    saved_image_name = f"{safe_car_name}_{int(datetime.timestamp(datetime.now()))}.{image_ext}"
                    image_file.save(os.path.join(app.config['IMAGE_FOLDER'], saved_image_name))
                else:
                    flash("Invalid image type! Allowed formats: png, jpg, jpeg, webp.", "danger")
                    return redirect(request.url)

            # Process Excel/CSV Spreadsheet ingestion
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            if filename.endswith('.csv'):
                df = pd.read_csv(filepath)
            else:
                df = pd.read_excel(filepath)

            df.columns = [str(col).strip().lower() for col in df.columns]

            if 'part' not in df.columns or 'rate' not in df.columns:
                flash("Error: Spreadsheets must contain exactly 'Part' and 'Rate' column headers.", "danger")
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
                    car_photo=saved_image_name # Set photo across rows linked to this entry batch
                )
                records_to_add.append(record)
            
            db.session.bulk_save_objects(records_to_add)
            db.session.commit()
            os.remove(filepath)
            
            flash(f"Successfully processed {len(records_to_add)} parts for '{car_model}'!", "success")
            return redirect(url_for('models_gallery'))

        except Exception as e:
            db.session.rollback()
            flash(f"System extraction error: {str(e)}", "danger")
            return redirect(request.url)

    return render_template('upload.html')

if __name__ == '__main__':
    app.run(debug=True)