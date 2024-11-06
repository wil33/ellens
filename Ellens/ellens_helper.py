from square.client import Client
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

# link for square developer dashboard: https://developer.squareup.com/apps/sq0idp-9MKKD0tJXYEn2Z40G9nsdw/settings

# ... rest of your code ...
# Initialize the Square client
# client = Client(
#     access_token="EAAAl0DWsRg2jeUm86gGjXBnoUsu_L_r-vkfomSvm9VSK_vvmGN-sxckZjAC3-qQ",  # Replace with your actual access token
#     environment="sandbox"  # Use 'sandbox' for testing purposes and 'production' for live data
# )

client = Client(
    access_token="EAAAlttsjfnsKbT0IZkpdbVr0j5A9RsS0vY_ERF8Z-jmeJKlnkUA0v9h5DnT6JZ1",  # Replace with your actual access token
    environment="production"  # Use 'sandbox' for testing purposes and 'production' for live data
)

# Get the current date and time
current_time = datetime.now().isoformat()

# Add this function to get your locations
def get_location_id(store_name=None):
    locations_api = client.locations
    result = locations_api.list_locations()
    
    if result.is_success():
        locations = result.body.get('locations', [])
        if locations:
            # Print all locations for reference
            print("Available locations:")
            for loc in locations:
                print(f"Name: {loc.get('name')}, ID: {loc.get('id')}")
            
            if store_name:
                # Try to find location by name
                for loc in locations:
                    if loc.get('name', '').lower() == store_name.lower():
                        return loc.get('id')
                print(f"No location found with name: {store_name}")
                return None
            else:
                # If no store name provided, return first location ID as before
                return locations[0].get('id')
    else:
        print(f"Error fetching locations: {result.errors}")
    return None

def fetch_itemized_sales(start_date = "2024-03-01", end_date = "2024-03-31", store_name = None): # start_date and end_date are strings in the format YYYY-MM-DD
    location_id = get_location_id(store_name)
    if not location_id:
        raise ValueError("Could not fetch location ID")
        
    orders_api = client.orders
    body = {
        "location_ids": [location_id],  # Now using the retrieved location ID
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
            print(f"Error fetching orders: {result.errors}")
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

# Current account balance
account_balance = 5000.00  # Example starting balance

# Scheduled payments (utilities, rent, debt)
scheduled_payments = [
    {'name': 'Rent', 'amount': 2000.00, 'due_date': '2023-11-01'},
    {'name': 'Utilities', 'amount': 500.00, 'due_date': '2023-10-25'},
    {'name': 'Debt Payment', 'amount': 750.00, 'due_date': '2023-10-30'},
]

# Add global last_assessed variable
last_assessed = '2024-03-01T00:00:00Z'  # Default starting date

# Inventory data (removed last_assessed from individual items)
inventory = {
    'ITEM_ID_PLANTS': {
        'stock': 50, 
        'reorder_threshold': 20, 
        'reorder_quantity': 50, 
        'supplier': 'PlantSupplierCo', 
        'cost': 15.00
    },
    'ITEM_ID_TEA': {'stock': 30, 'reorder_threshold': 10, 'reorder_quantity': 40, 'supplier': 'TeaSupplierCo', 'cost': 5.00},
    'ITEM_ID_FOOD': {'stock': 100, 'reorder_threshold': 50, 'reorder_quantity': 150, 'supplier': 'FoodSupplierCo', 'cost': 8.00},
}

def update_inventory_from_sales():
    global last_assessed
    current_time = datetime.now().isoformat() + 'Z'
    
    # Fetch sales since last assessment
    sales_data = fetch_itemized_sales(
        start_date=last_assessed.split('T')[0],
        end_date=current_time.split('T')[0]
    )
    
    for item_id in inventory:
        # Calculate total quantity sold for this item
        quantity_sold = sum(
            sale['quantity'] 
            for sale in sales_data 
            if sale['item_id'] == item_id
        )
        
        # Update stock 
        inventory[item_id]['stock'] -= quantity_sold
        
        # Print update message
        print(f"Updated {inventory[item_id].get('name', item_id)}:")
        print(f"  Quantity sold: {quantity_sold}")
        print(f"  Current stock: {inventory[item_id]['stock']}")
        
        # Check if reorder is needed
        if (inventory[item_id]['stock'] is not None and 
            inventory[item_id]['reorder_threshold'] is not None and 
            inventory[item_id]['stock'] <= inventory[item_id]['reorder_threshold']):
            print(f"  ⚠️ Stock below reorder threshold! Consider ordering {inventory[item_id]['reorder_quantity']} units")
    
    # Update last_assessed timestamp after processing all items
    last_assessed = current_time
    
    return inventory

def fetch_all_catalog_items():
    catalog_api = client.catalog
    all_items = []
    cursor = None  # For pagination

    try:
        while True:
            # Call the list_catalog endpoint
            result = catalog_api.list_catalog(
                cursor=cursor,
                types='ITEM'  # Fetch only items; remove this parameter to fetch all object types
            )

            if result.is_success():
                # Access the list of objects returned
                items = result.body.get('objects', [])
                all_items.extend(items)

                # Check if there is a next page
                cursor = result.body.get('cursor')
                if not cursor:
                    break  # No more pages, exit the loop
            elif result.is_error():
                print(f"Error fetching catalog: {result.errors}")
                break

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    return all_items

# Fetch all catalog items
catalog_items = fetch_all_catalog_items()

# Process and display the items
for item in catalog_items:
    item_id = item.get('id')
    item_name = item.get('item_data', {}).get('name')
    print(f"Item ID: {item_id}, Item Name: {item_name}")

def update_inventory_from_catalog():
    # Fetch catalog items
    global catalog_items
    new_items_count = 0
    
    # For each catalog item
    for item in catalog_items:
        item_id = item.get('id')
        item_name = item.get('item_data', {}).get('name')
        
        # If item not in inventory, add it with default values
        if item_id not in inventory:
            inventory[item_id] = {
                'name': item_name,
                'stock': 0,
                'reorder_threshold': None,
                'reorder_quantity': None,
                'supplier': None,
                'cost': None
            }
            new_items_count += 1
            print(f"Added new item to inventory: {item_name} (ID: {item_id})")
    
    return inventory, new_items_count

def refresh_catalog():
    """Refreshes the global catalog_items variable with latest data from Square API"""
    global catalog_items
    print("Refreshing catalog items...")
    catalog_items = fetch_all_catalog_items()
    print(f"Catalog refreshed. Found {len(catalog_items)} items.")
    
    # Update inventory with any new items and get count of new items
    _, new_items_count = update_inventory_from_catalog()
    print(f"Added {new_items_count} new items to inventory.")
    return catalog_items







