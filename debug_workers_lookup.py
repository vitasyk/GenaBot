"""Debug Google Sheets worker lookup for today"""
import asyncio
import logging
from datetime import date, datetime
from bot.services.google_sheets import GoogleSheetsService
from bot.config import config

# Ensure logging is visible
logging.basicConfig(level=logging.INFO)

async def debug_workers():
    service = GoogleSheetsService()
    
    # Current scenario: Feb 5, 21:00 outage
    # The user says "Created session manually" around 21:00 local time
    target_date = date(2026, 2, 5) 
    
    # Let's check a few critical hours
    # 21:00 corresponds to "Evening" shift logic in get_workers_for_outage
    test_hours = [21, 14, 9] 
    
    print(f"\n--- Debugging Worker Lookup for {target_date} ---")
    
    try:
        # 1. Test basic date column finding
        service._ensure_init()
        # Accessing private members for debug - okay for this script
        all_values = service.worksheet.get_all_values()
        col = service._find_date_column(target_date, all_values)
        print(f"Detected column index for {target_date}: {col}")
        
        if col:
             # Print values in that column for a few rows to verify
             print(f"Values in column {col} (rows 39-45):")
             for i in range(38, 45):
                 row = all_values[i]
                 val = row[col] if col < len(row) else "N/A"
                 name = row[0]
                 print(f"  Row {i+1}: {name} -> {val}")

        # 2. Test get_workers_for_outage logic
        for hour in test_hours:
            print(f"\nTesting get_workers_for_outage({hour}, {target_date})...")
            best = service.get_workers_for_outage(hour, target_date)
            if not best:
                print("  RESULT: No workers found!")
            for name, phone in best:
                print(f"  RESULT: {name} ({phone})")
            
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_workers())
