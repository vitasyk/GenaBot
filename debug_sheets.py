"""Debug script to see raw data from spreadsheet"""
from bot.services.google_sheets import GoogleSheetsService

try:
    service = GoogleSheetsService()
    service._ensure_init()
    
    # Get all values as 2D array (raw data)
    all_values = service.worksheet.get_all_values()
    
    print(f"Found {len(all_values)} rows")
    print("\nFirst 5 rows (raw):")
    for i, row in enumerate(all_values[:5]):
        print(f"Row {i+1}: {row}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
