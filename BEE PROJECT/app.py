from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///power_consumption.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Country data with voltage, frequency, and average cost per kWh
COUNTRY_DATA = {
    "USA": {"voltage": 120, "frequency": 60, "cost_per_kwh": 0.15},
    "Canada": {"voltage": 120, "frequency": 60, "cost_per_kwh": 0.12},
    "UK": {"voltage": 230, "frequency": 50, "cost_per_kwh": 0.22},
    "Germany": {"voltage": 230, "frequency": 50, "cost_per_kwh": 0.35},
    "France": {"voltage": 230, "frequency": 50, "cost_per_kwh": 0.19},
    "Australia": {"voltage": 230, "frequency": 50, "cost_per_kwh": 0.25},
    "Japan": {"voltage": 100, "frequency": 50, "cost_per_kwh": 0.26},
    "India": {"voltage": 230, "frequency": 50, "cost_per_kwh": 0.08},
    "China": {"voltage": 220, "frequency": 50, "cost_per_kwh": 0.10},
    "Brazil": {"voltage": 127, "frequency": 60, "cost_per_kwh": 0.18}
}

# Database Models
class Appliance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    power_watts = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # CASCADE DELETE FIX ✅
    daily_consumptions = db.relationship(
        'DailyConsumption',
        backref='appliance',
        cascade="all, delete-orphan",
        lazy=True
    )

class DailyConsumption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10), nullable=False)  # YYYY-MM-DD format
    appliance_id = db.Column(db.Integer, db.ForeignKey('appliance.id'), nullable=False)
    hours_used = db.Column(db.Float, nullable=False)
    consumption_kwh = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MonthlySummary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False)  # YYYY-MM format
    country = db.Column(db.String(50), nullable=False)
    total_consumption = db.Column(db.Float, nullable=False)
    total_cost = db.Column(db.Float, nullable=False)
    carbon_footprint = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables
with app.app_context():
    db.create_all()

@app.context_processor
def inject_country_data():
    return dict(COUNTRY_DATA=COUNTRY_DATA)

@app.route('/')
def index():
    return redirect(url_for('appliance_setup'))

@app.route('/appliance-setup', methods=['GET', 'POST'])
def appliance_setup():
    if request.method == 'POST':
        name = request.form['name']
        power_watts = float(request.form['power_watts'])
        
        appliance = Appliance(name=name, power_watts=power_watts)
        db.session.add(appliance)
        db.session.commit()
        
        return redirect(url_for('appliance_setup'))
    
    appliances = Appliance.query.all()
    return render_template('appliance_setup.html', 
                         appliances=appliances, 
                         countries=COUNTRY_DATA.keys(),
                         current_month=datetime.now().strftime("%Y-%m"))

@app.route('/delete-appliance/<int:appliance_id>')
def delete_appliance(appliance_id):
    appliance = Appliance.query.get_or_404(appliance_id)
    db.session.delete(appliance)
    db.session.commit()
    return redirect(url_for('appliance_setup'))

@app.route('/daily-input', methods=['GET', 'POST'])
def daily_input():
    appliances = Appliance.query.all()
    if not appliances:
        return redirect(url_for('appliance_setup'))
    
    current_date = datetime.now()
    current_month = current_date.strftime("%Y-%m")
    current_day = current_date.day
    
    if request.method == 'POST':
        date_str = request.form['date']
        for appliance in appliances:
            hours_used = float(request.form.get(f'hours_{appliance.id}', 0))
            if hours_used > 0:
                consumption_kwh = (appliance.power_watts * hours_used) / 1000

                existing = DailyConsumption.query.filter_by(
                    date=date_str, 
                    appliance_id=appliance.id
                ).first()
                
                if existing:
                    existing.hours_used = hours_used
                    existing.consumption_kwh = consumption_kwh
                else:
                    daily_consumption = DailyConsumption(
                        date=date_str,
                        appliance_id=appliance.id,
                        hours_used=hours_used,
                        consumption_kwh=consumption_kwh
                    )
                    db.session.add(daily_consumption)
        
        db.session.commit()
        return redirect(url_for('daily_input'))
    
    days_with_data = db.session.query(DailyConsumption.date).filter(
        DailyConsumption.date.like(f"{current_month}-%")
    ).distinct().all()
    
    days_with_data = [day[0] for day in days_with_data]
    
    return render_template('daily_input.html',
                         appliances=appliances,
                         current_month=current_month,
                         current_day=current_day,
                         days_with_data=days_with_data,
                         countries=COUNTRY_DATA.keys())

@app.route('/get-day-data/<date>')
def get_day_data(date):
    daily_data = DailyConsumption.query.filter_by(date=date).all()
    data = {entry.appliance_id: {'hours_used': entry.hours_used, 'consumption_kwh': entry.consumption_kwh} for entry in daily_data}
    return jsonify(data)

@app.route('/monthly-results')
def monthly_results():
    month = request.args.get('month', datetime.now().strftime("%Y-%m"))
    country = request.args.get('country', 'USA')
    
    daily_consumptions = DailyConsumption.query.filter(
        DailyConsumption.date.like(f"{month}-%")
    ).all()
    
    monthly_totals = {}
    daily_max_consumers = {}
    
    appliances = Appliance.query.all()
    appliance_map = {app.id: app for app in appliances}
    
    for appliance in appliances:
        monthly_totals[appliance.name] = 0
    
    dates = set([dc.date for dc in daily_consumptions])
    for date in dates:
        day_consumptions = [dc for dc in daily_consumptions if dc.date == date]
        day_max_consumption = 0
        day_max_appliance = ""
        
        for dc in day_consumptions:
            appliance_name = appliance_map[dc.appliance_id].name
            monthly_totals[appliance_name] += dc.consumption_kwh
            
            if dc.consumption_kwh > day_max_consumption:
                day_max_consumption = dc.consumption_kwh
                day_max_appliance = appliance_name
        
        daily_max_consumers[date] = (day_max_appliance, day_max_consumption)
    
    total_monthly_kwh = sum(monthly_totals.values())
    cost_per_kwh = COUNTRY_DATA[country]["cost_per_kwh"]
    total_cost = total_monthly_kwh * cost_per_kwh
    carbon_footprint = total_monthly_kwh * 0.5
    
    available_months = db.session.query(DailyConsumption.date).distinct().all()
    available_months = sorted(set([date[0][:7] for date in available_months]), reverse=True)
    
    return render_template('monthly_results.html',
                         month=month,
                         country=country,
                         total_kwh=total_monthly_kwh,
                         total_cost=total_cost,
                         carbon_footprint=carbon_footprint,
                         monthly_totals=monthly_totals,
                         daily_max_consumers=daily_max_consumers,
                         available_months=available_months,
                         countries=COUNTRY_DATA.keys(),
                         COUNTRY_DATA=COUNTRY_DATA)

@app.route('/daily-analysis')
def daily_analysis():
    month = request.args.get('month', datetime.now().strftime("%Y-%m"))
    
    daily_consumptions = DailyConsumption.query.filter(
        DailyConsumption.date.like(f"{month}-%")
    ).all()
    
    appliances = Appliance.query.all()
    appliance_map = {app.id: app for app in appliances}
    daily_max_consumers = {}
    
    dates = set([dc.date for dc in daily_consumptions])
    for date in dates:
        day_consumptions = [dc for dc in daily_consumptions if dc.date == date]
        day_max_consumption = 0
        day_max_appliance = ""
        
        for dc in day_consumptions:
            appliance_name = appliance_map[dc.appliance_id].name
            if dc.consumption_kwh > day_max_consumption:
                day_max_consumption = dc.consumption_kwh
                day_max_appliance = appliance_name
        
        daily_max_consumers[date] = (day_max_appliance, day_max_consumption)
    
    appliance_days = {}
    for date, (max_appliance, _) in daily_max_consumers.items():
        appliance_days[max_appliance] = appliance_days.get(max_appliance, 0) + 1
    
    most_frequent_max = max(appliance_days.items(), key=lambda x: x[1]) if appliance_days else (None, 0)
    
    return render_template('daily_analysis.html',
                         month=month,
                         daily_max_consumers=daily_max_consumers,
                         appliance_days=appliance_days,
                         most_frequent_max=most_frequent_max,
                         total_days=len(daily_max_consumers))

if __name__ == '__main__':
    app.run(debug=True)
