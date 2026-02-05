"""List all worksheets in the spreadsheet"""
from bot.services.google_sheets import GoogleSheetsService

try:
    service = GoogleSheetsService()
    service._ensure_init()
    
    # List all worksheet titles
    worksheets = service.spreadsheet.worksheets()
    print(f"Found {len(worksheets)} worksheets:")
    for ws in worksheets:
        print(f"  - '{ws.title}'")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
