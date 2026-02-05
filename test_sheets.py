"""Test the updated Google Sheets calendar parser"""
from bot.services.google_sheets import GoogleSheetsService
from datetime import date

try:
    service = GoogleSheetsService()
    
    # Test 1: Get workers who start at 9:00 today
    print("=== Workers starting at 9:00 on 03.02 ===")
    workers_9 = service.get_workers_for_time(date(2026, 2, 3), 9)
    for name, phone in workers_9:
        print(f"  {name} - {phone}")
    
    print("\n=== Workers starting at 20:00 on 03.02 ===")
    workers_20 = service.get_workers_for_time(date(2026, 2, 3), 20)
    for name, phone in workers_20:
        print(f"  {name} - {phone}")
    
    # Test 2: Get best workers for early morning outage (05:00)
    print("\n=== Best 2 workers for outage at 05:00 ===")
    best = service.get_workers_for_outage(5, date(2026, 2, 3))
    for name, phone in best:
        print(f"  {name} - {phone}")
    
    # Test 3: Get best workers for afternoon outage (14:00)
    print("\n=== Best 2 workers for outage at 14:00 ===")
    best = service.get_workers_for_outage(14, date(2026, 2, 3))
    for name, phone in best:
        print(f"  {name} - {phone}")

    # Test 4: Get best workers for evening outage (22:00)
    print("\n=== Best 2 workers for outage at 22:00 (Expect starts at 13 & 20) ===")
    best = service.get_workers_for_outage(22, date(2026, 2, 3))
    for name, phone in best:
        print(f"  {name} - {phone}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
