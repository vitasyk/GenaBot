
from bot.services.google_sheets import GoogleSheetsService
from datetime import date, datetime

def test_workers():
    service = GoogleSheetsService()
    service._ensure_init()
    
    # 2026-02-04
    d4 = date(2026, 2, 4)
    # 2026-02-05
    d5 = date(2026, 2, 5)
    
    # Hour 11 as per log outage block start
    hour = 11
    
    print(f"Testing for Hour {hour}")
    
    workers4 = service.get_workers_for_outage(hour, target_date=d4)
    print(f"Workers for Feb 4: {workers4}")
    
    workers5 = service.get_workers_for_outage(hour, target_date=d5)
    print(f"Workers for Feb 5: {workers5}")

if __name__ == "__main__":
    test_workers()
