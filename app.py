from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from square.client import Client
import pandas as pd
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import matplotlib.pyplot as plt
import io
import base64
from flask_sqlalchemy import SQLAlchemy
import uuid
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Fix database URL handling
database_url = os.getenv('DATABASE_URL')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

def get_database_url():
    """Securely construct database URL from environment variables"""
    db_type = os.getenv('DB_TYPE', 'sqlite')
    
    if db_type == 'sqlite':
        return 'sqlite:///inventory.db'
    
    # For PostgreSQL, construct URL from separate environment variables
    elif db_type == 'postgresql':
        db_user = os.getenv('DB_USER')
        db_pass = os.getenv('DB_PASS')
        db_host = os.getenv('DB_HOST')
        db_port = os.getenv('DB_PORT')
        db_name = os.getenv('DB_NAME')
        
        if all([db_user, db_pass, db_host, db_port, db_name]):
            return f'postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}'
    
    # Default to SQLite if configuration is incomplete
    return 'sqlite:///inventory.db'

# Configure database
app.config['SQLALCHEMY_DATABASE_URI'] = get_database_url()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Define database models
class InventoryItem(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    stock = db.Column(db.Float, nullable=False)
    reorder_threshold = db.Column(db.Float, nullable=False)
    reorder_quantity = db.Column(db.Float, nullable=False)
    supplier = db.Column(db.String(100), nullable=False)
    is_mix = db.Column(db.Boolean, default=False)

class SalesRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(100), db.ForeignKey('inventory_item.id'))
    quantity = db.Column(db.Float)
    total_money = db.Column(db.Float)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class SystemSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    last_assessed = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class ItemSubcomponent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.String(100), db.ForeignKey('inventory_item.id'), nullable=False)
    subcomponent_id = db.Column(db.String(100), db.ForeignKey('inventory_item.id'), nullable=False)
    quantity_required = db.Column(db.Float, nullable=False)
    
    # Update relationships to reference InventoryItem instead of Item
    item = db.relationship('InventoryItem', foreign_keys=[item_id], backref='subcomponents')
    subcomponent = db.relationship('InventoryItem', foreign_keys=[subcomponent_id])

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Initialize the Square client
client = Client(
    access_token=os.getenv("SQUARE_ACCESS_TOKEN"),
    environment=os.getenv("SQUARE_ENVIRONMENT", "production")
)

# Global variables
account_balance = 5000.00  # Example starting balance

scheduled_payments = [
    {'name': 'Rent', 'amount': 2000.00, 'due_date': '2023-11-01'},
    {'name': 'Utilities', 'amount': 500.00, 'due_date': '2023-10-25'},
    {'name': 'Debt Payment', 'amount': 750.00, 'due_date': '2023-10-30'},
]

last_assessed = '2024-03-01T00:00:00Z'  # Default starting date

# Add at the top with other globals
DEBUG = False  # Global debug flag

# After creating Flask app
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
@login_required
def index():
    search_query = request.args.get('search', '')
    low_stock_items = InventoryItem.query.filter(InventoryItem.stock <= InventoryItem.reorder_threshold)
    
    if search_query:
        low_stock_items = low_stock_items.filter(InventoryItem.name.ilike(f'%{search_query}%'))
    
    low_stock_items = low_stock_items.all()
    return render_template('index.html', low_stock_items=low_stock_items, search_query=search_query)

@app.route('/inventory')
@login_required
def inventory():
    search_query = request.args.get('search', '')
    items = InventoryItem.query

    if search_query:
        items = items.filter(InventoryItem.name.ilike(f'%{search_query}%'))
    
    items = items.all()
    return render_template('inventory.html', items=items, search_query=search_query)

@app.route('/finances')
def finances_page():
    return render_template('finances.html')

@app.route('/item/<item_id>')
def item_details(item_id):
    item = InventoryItem.query.get_or_404(item_id)
    # Add this query to get subcomponents
    subcomponents = db.session.query(
        InventoryItem,
        ItemSubcomponent.quantity_required,
    ).join(
        ItemSubcomponent,
        ItemSubcomponent.subcomponent_id == InventoryItem.id
    ).filter(
        ItemSubcomponent.item_id == item_id
    ).all()
    
    # Convert query results to a list of dicts for easier template access
    subcomponents_data = [{
        'id': sub[0].id,
        'name': sub[0].name,
        'current_stock': sub[0].stock,
        'quantity_required': sub[1]
    } for sub in subcomponents]
    
    return render_template('item_details.html', 
                         item=item, 
                         subcomponents=subcomponents_data)

@app.route('/add_item', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        try:
            # Generate a unique ID (you can use UUID or another method)
            item_id = str(uuid.uuid4())
            
            # Get form data with stripped whitespace
            name = request.form.get('name', '').strip()
            stock = request.form.get('stock', '').strip()
            reorder_threshold = request.form.get('reorder_threshold', '').strip()
            reorder_quantity = request.form.get('reorder_quantity', '').strip()
            supplier = request.form.get('supplier', '').strip()

            # Print the processed data for debugging
            print(f"Processed data: name={name}, stock={stock}, threshold={reorder_threshold}, quantity={reorder_quantity}, supplier={supplier}")

            # Validate name
            if not name:
                raise ValueError("Item name cannot be empty")
            
            # Validate and convert numeric fields
            try:
                stock = float(stock) if stock else 0.0
                print(f"Converted stock: {stock}")
            except ValueError:
                raise ValueError("Stock must be a valid number")

            try:
                reorder_threshold = float(reorder_threshold) if reorder_threshold else 0.0
                print(f"Converted threshold: {reorder_threshold}")
            except ValueError:
                raise ValueError("Reorder threshold must be a valid number")

            try:
                reorder_quantity = float(reorder_quantity) if reorder_quantity else 0.0
                print(f"Converted quantity: {reorder_quantity}")
            except ValueError:
                raise ValueError("Reorder quantity must be a valid number")

            # Validate supplier
            if not supplier:
                raise ValueError("Supplier name cannot be empty")

            # Create and add new item with ID
            new_item = InventoryItem(
                id=item_id,  # Add the generated ID
                name=name,
                stock=stock,
                reorder_threshold=reorder_threshold,
                reorder_quantity=reorder_quantity,
                supplier=supplier
            )
            
            print("Attempting to add item to database...")
            db.session.add(new_item)
            db.session.commit()
            print("Item added successfully!")
            
            flash(f'Item "{name}" added successfully!', 'success')
            return redirect(url_for('inventory'))

        except Exception as e:
            # Log the full error details
            import traceback
            print("Error details:")
            print(traceback.format_exc())
            
            # Rollback the session
            db.session.rollback()
            
            # Flash the actual error message
            error_message = str(e)
            print(f"Error message: {error_message}")
            flash(f'Error: {error_message}', 'error')
            
            return redirect(url_for('add_item'))
    
    return render_template('add_item.html')

@app.route('/delete_item/<item_id>', methods=['POST'])
def delete_item(item_id):
    try:
        item = InventoryItem.query.get(item_id)
        if item:
            item_name = item.name  # Store name before deletion for flash message
            db.session.delete(item)
            db.session.commit()
            flash(f'Successfully deleted {item_name}', 'success')
        else:
            flash('Item not found', 'error')
    except Exception as e:
        flash(f'Error deleting item: {str(e)}', 'error')
        
    return redirect(url_for('inventory'))

@app.route('/update_item/<item_id>', methods=['POST'])
def update_item(item_id):
    try:
        item = InventoryItem.query.get(item_id)
        if not item:
            flash('Item not found', 'error')
            return redirect(url_for('inventory'))

        # Update is_mix status
        item.is_mix = request.form.get('is_mix') == 'on'
        
        # Get current and new stock values
        current_stock = item.stock
        new_stock = float(request.form.get('stock', 0))
        stock_increase = new_stock - current_stock

        # If stock was increased and it's a mix
        if stock_increase > 0 and item.is_mix:
            subcomponents = ItemSubcomponent.query.filter_by(item_id=item_id).all()
            for subcomponent in subcomponents:
                # Check if this subcomponent should be used
                if request.form.get(f'use_subcomponent_{subcomponent.subcomponent_id}') == 'on':
                    sub_item = InventoryItem.query.get(subcomponent.subcomponent_id)
                    if sub_item:
                        required_quantity = stock_increase * subcomponent.quantity_required
                        if required_quantity > sub_item.stock:
                            flash(f'Not enough {sub_item.name} in stock', 'error')
                            return redirect(url_for('item_details', item_id=item_id))
                        
                        # Add debug prints
                        print(f"Adjusting {sub_item.name} stock:")
                        print(f"  Before: {sub_item.stock}")
                        
                        # Deduct from subcomponent stock
                        sub_item.stock -= required_quantity
                        
                        print(f"  After: {sub_item.stock}")

        # Get form data
        item.name = request.form.get('name', '').strip()
        item.reorder_threshold = float(request.form.get('reorder_threshold', 0))
        item.reorder_quantity = float(request.form.get('reorder_quantity', 0))
        item.supplier = request.form.get('supplier', '').strip()

        # Validate basic data
        if not item.name:
            raise ValueError("Name cannot be empty")
        if new_stock < 0:
            raise ValueError("Stock cannot be negative")
        if item.reorder_threshold < 0:
            raise ValueError("Reorder threshold cannot be negative")
        if item.reorder_quantity < 0:
            raise ValueError("Reorder quantity cannot be negative")
        if not item.supplier:
            raise ValueError("Supplier cannot be empty")

        # Only update the stock if all checks passed
        item.stock = new_stock
        db.session.commit()
        flash('Item updated successfully', 'success')
        
    except ValueError as e:
        flash(f'Validation error: {str(e)}', 'error')
        db.session.rollback()
    except Exception as e:
        flash(f'Error updating item: {str(e)}', 'error')
        db.session.rollback()
    
    return redirect(url_for('item_details', item_id=item_id))

# Add your functions here...

def get_location_id(store_name=None, debug=DEBUG):
    locations_api = client.locations
    result = locations_api.list_locations()
    
    if result.is_success():
        locations = result.body.get('locations', [])
        if locations:
            if store_name:
                # Try to find location by name
                for loc in locations:
                    if loc.get('name', '').lower() == store_name.lower():
                        return loc.get('id')
                if debug: print(f"No location found with name: {store_name}")
                return None
            else:
                # If no store name provided, return first location ID
                return locations[0].get('id')
    else:
        if debug: print(f"Error fetching locations: {result.errors}")
    return None

def fetch_itemized_sales(start_date=None, end_date=None, store_name=None, debug=DEBUG):
    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')

    location_id = get_location_id(store_name)
    if not location_id:
        raise ValueError("Could not fetch location ID")
        
    orders_api = client.orders
    body = {
        "location_ids": [location_id],
        "query": {
            "filter": {
                "date_time_filter": {
                    "created_at": {
                        "start_at": f"{start_date}T00:00:00Z",
                        "end_at": f"{end_date}T23:59:59Z"
                    }
                }
            }
        }
    }

    orders = []
    cursor = None

    while True:
        if cursor:
            body['cursor'] = cursor

        result = orders_api.search_orders(body)

        if result.is_success():
            result_orders = result.body.get('orders', [])
            orders.extend(result_orders)
            cursor = result.body.get('cursor', None)
            if not cursor:
                break
        else:
            if debug: print(f"Error fetching orders: {result.errors}")
            break

    # Process orders to extract itemized sales data
    sales_data = []
    for order in orders:
        for line_item in order.get('line_items', []):
            sale = {
                'item_id': line_item.get('catalog_object_id'),
                'item_name': line_item.get('name'),
                'quantity': float(line_item.get('quantity')),
                'total_money': int(line_item['total_money']['amount']) / 100,
                'date': order['created_at']
            }
            sales_data.append(sale)

    return sales_data

def fetch_all_catalog_items(debug=DEBUG):
    catalog_api = client.catalog
    all_items = []
    cursor = None

    try:
        while True:
            result = catalog_api.list_catalog(
                cursor=cursor,
                types='ITEM'
            )

            if result.is_success():
                items = result.body.get('objects', [])
                all_items.extend(items)

                cursor = result.body.get('cursor')
                if not cursor:
                    break
            elif result.is_error():
                if debug: print(f"Error fetching catalog: {result.errors}")
                break

    except Exception as e:
        if debug: print(f"An unexpected error occurred: {e}")

    return all_items

def update_inventory_from_catalog(debug=DEBUG):
    catalog_items = fetch_all_catalog_items(debug)
    new_items_count = 0

    for item in catalog_items:
        item_id = item.get('id')
        item_name = item.get('item_data', {}).get('name')
        
        # Check if item exists in database
        inv_item = InventoryItem.query.get(item_id)
        if not inv_item:
            inv_item = InventoryItem(
                id=item_id,
                name=item_name,
                stock=0,
                reorder_threshold=10,
                reorder_quantity=20,
                supplier='Unknown'
            )
            db.session.add(inv_item)
            new_items_count += 1
            if debug: print(f"Added new item to inventory: {item_name} (ID: {item_id})")
    
    db.session.commit()
    return new_items_count

def update_inventory_from_sales():
    # Get the last assessed time from database
    settings = SystemSettings.query.first()
    if not settings:
        settings = SystemSettings(last_assessed=datetime.utcnow())
        db.session.add(settings)
        db.session.commit()
    
    current_time = datetime.utcnow()
    sales_data = fetch_itemized_sales(
        start_date=settings.last_assessed.strftime('%Y-%m-%d'),
        end_date=current_time.strftime('%Y-%m-%d')
    )

    for sale in sales_data:
        item_id = sale['item_id']
        item = InventoryItem.query.get(item_id)
        if item:
            # Update main item stock
            item.stock -= sale['quantity']
            if item.stock < 0:
                item.stock = 0
            
            # Update subcomponents stock
            subcomponents = ItemSubcomponent.query.filter_by(item_id=item_id).all()
            for subcomponent in subcomponents:
                sub_item = InventoryItem.query.get(subcomponent.subcomponent_id)
                if sub_item:
                    # Calculate how many subcomponents were used
                    sub_quantity_used = sale['quantity'] * subcomponent.quantity_required
                    sub_item.stock -= sub_quantity_used
                    if sub_item.stock < 0:
                        sub_item.stock = 0
                        flash(f'Warning: {sub_item.name} stock went negative', 'warning')
            
            # Record the sale
            sale_record = SalesRecord(
                item_id=item_id,
                quantity=sale['quantity'],
                total_money=sale['total_money'],
                date=datetime.strptime(sale['date'], '%Y-%m-%dT%H:%M:%SZ')
            )
            db.session.add(sale_record)
    
    # Update the last assessed time
    settings.last_assessed = current_time
    db.session.commit()

def generate_sales_plot(sales_data):
    df = pd.DataFrame(sales_data)
    df['date'] = pd.to_datetime(df['date']).dt.date
    daily_sales = df.groupby('date')['total_money'].sum()

    plt.figure(figsize=(10, 5))
    daily_sales.plot(kind='bar')
    plt.title('Daily Sales')
    plt.xlabel('Date')
    plt.ylabel('Total Sales Amount')

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png')
    buf.seek(0)
    plt.close()

    # Encode the image to base64 to send it to the template
    img_base64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return img_base64

# Add new route for manual inventory update
@app.route('/update_inventory', methods=['POST'])
def update_inventory():
    try:
        update_inventory_from_catalog()
        update_inventory_from_sales()
        flash('Inventory updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating inventory: {str(e)}', 'error')
    return redirect(url_for('index'))

# Initialize database
with app.app_context():
    db.create_all()

@app.route('/search_items')
def search_items():
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify([])
    
    # Search for items excluding the current item
    items = InventoryItem.query.filter(
        InventoryItem.name.ilike(f'%{q}%'),
        InventoryItem.id != request.args.get('current_item_id', 0)
    ).all()
    
    return jsonify([{
        'id': item.id,
        'name': item.name,
        'stock': item.stock
    } for item in items])

@app.route('/item/<item_id>/add_subcomponent', methods=['POST'])
def add_subcomponent(item_id):
    try:
        subcomponent_id = request.form.get('subcomponent_id')
        quantity = float(request.form.get('quantity', 0))

        # Validate inputs
        if not subcomponent_id or quantity <= 0:
            flash('Invalid subcomponent or quantity', 'error')
            return redirect(url_for('item_details', item_id=item_id))

        # Check if this subcomponent relationship already exists
        existing = ItemSubcomponent.query.filter_by(
            item_id=item_id,
            subcomponent_id=subcomponent_id
        ).first()

        if existing:
            flash('This subcomponent is already added', 'error')
        else:
            # Create new subcomponent relationship
            new_subcomponent = ItemSubcomponent(
                item_id=item_id,
                subcomponent_id=subcomponent_id,
                quantity_required=quantity
            )
            db.session.add(new_subcomponent)
            db.session.commit()
            flash('Subcomponent added successfully', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error adding subcomponent: {str(e)}', 'error')
        print(f"Error in add_subcomponent: {str(e)}")  # For debugging

    return redirect(url_for('item_details', item_id=item_id))

@app.route('/item/<item_id>/remove_subcomponent/<subcomponent_id>', methods=['POST'])
def remove_subcomponent(item_id, subcomponent_id):
    try:
        subcomponent = ItemSubcomponent.query.filter_by(
            item_id=item_id,
            subcomponent_id=subcomponent_id
        ).first()
        
        if subcomponent:
            db.session.delete(subcomponent)
            db.session.commit()
            flash('Subcomponent removed successfully', 'success')
        else:
            flash('Subcomponent not found', 'error')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Error removing subcomponent: {str(e)}', 'error')
        print(f"Error in remove_subcomponent: {str(e)}")  # For debugging
        
    return redirect(url_for('item_details', item_id=item_id))

# Add this debugging route to check what's in the database
@app.route('/debug/subcomponents/<item_id>')
def debug_subcomponents(item_id):
    if not app.debug:
        return "Debug mode is off"
        
    try:
        # Query all subcomponents for this item
        subcomponents = ItemSubcomponent.query.filter_by(item_id=item_id).all()
        
        # Format the results
        results = []
        for sub in subcomponents:
            item = InventoryItem.query.get(sub.subcomponent_id)
            results.append({
                'subcomponent_id': sub.subcomponent_id,
                'name': item.name if item else 'Unknown',
                'quantity_required': sub.quantity_required
            })
            
        return jsonify({
            'item_id': item_id,
            'subcomponents': results,
            'count': len(results)
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e)
        })

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists', 'error')
            return redirect(url_for('register'))
        
        user = User(username=username)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

def create_admin():
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin')
            admin.set_password('your-admin-password')
            db.session.add(admin)
            db.session.commit()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        update_inventory_from_catalog()
        update_inventory_from_sales()
        create_admin()  # Create admin user
    app.run(debug=True)
