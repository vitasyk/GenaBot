import gspread
from google.oauth2.service_account import Credentials
from bot.config import config
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Tuple
import logging
import re

class GoogleSheetsService:
    """Service for reading worker shift schedule from Google Sheets (calendar format)"""
    
    def __init__(self):
        try:
            self.creds = Credentials.from_service_account_file(
                config.GOOGLE_CREDENTIALS_PATH,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            self.client = gspread.authorize(self.creds)
            self.spreadsheet = None
            self.worksheet = None
            self._initialized = False
        except Exception as e:
            logging.warning(f"Google Sheets init failed: {e}. Will try on first use.")
            self._initialized = False
    
    def _ensure_init(self):
        """Lazy initialization of spreadsheet connection"""
        if not self._initialized and config.SCHEDULE_SPREADSHEET_ID:
            try:
                self.spreadsheet = self.client.open_by_key(config.SCHEDULE_SPREADSHEET_ID)
                
                # Dynamic worksheet name based on current month
                # Format: MM'YY (e.g., "02'26" for Feb 2026)
                now = datetime.now()
                worksheet_name = now.strftime("%m'%y")
                
                self.worksheet = self.spreadsheet.worksheet(worksheet_name)
                self._initialized = True
                logging.info(f"✅ Google Sheets connected to worksheet: {worksheet_name}")
            except Exception as e:
                logging.error(f"Failed to connect to Google Sheets: {e}")
                raise
    
    def _find_date_column(self, target_date: date, all_values: List[List[str]]) -> Optional[int]:
        """
        Find column index for specific date
        Returns column index (0-based) or None
        """
        if not all_values or len(all_values) < 2:
            return None
        
        # Row 1 has day names: Нд, Пн, Вт, ...
        # Look for pattern matching the day of month
        day_num = target_date.day
        
        # Search in first few rows for date indicators
        for row_idx in range(min(3, len(all_values))):
            row = all_values[row_idx]
            for col_idx, cell in enumerate(row):
                # Look for day number (e.g., "3" for 3rd day)
                if cell.strip() == str(day_num):
                    return col_idx
        
        # Fallback: estimate based on day of month
        # Assuming columns start from column 2 (after name and phone)
        # and cycle through weeks
        return 2 + (day_num - 1)  # Rough estimate
    
    def get_workers_for_time(self, target_date: date, start_hour: int) -> List[Tuple[str, str]]:
        """
        Get workers who start work at specific hour on specific date
        Returns: [(name, phone), ...]
        """
        self._ensure_init()
        
        all_values = self.worksheet.get_all_values()
        
        # Find column for this date
        date_col = self._find_date_column(target_date, all_values)
        if date_col is None:
            logging.warning(f"Could not find column for date {target_date}")
            return []
        
        workers = []
        
        # Skip header rows (first 2-3 rows), start from actual data
        # User requested restriction: Only rows 39-60 participate in refueling
        # Row 39 is index 38. Row 60 is index 59.
        start_row_idx = 38
        end_row_idx = 60 # Check up to row 60 (index 59)
        
        for row_idx in range(start_row_idx, min(end_row_idx, len(all_values))):
            row = all_values[row_idx]
            
            if len(row) <= date_col:
                continue
            
            # Column 0: Worker name
            # Column 1: Phone
            # Column date_col: Shift start time
            worker_name = row[0].strip()
            phone = row[1].strip() if len(row) > 1 else ""
            shift_value = row[date_col].strip() if date_col < len(row) else ""
            
            # Check if shift_value matches our target hour (e.g., "09:00", "9:00", "9")
            match = False
            if shift_value:
                # Try to extract leading digits
                cleaned = re.sub(r'[^0-9:]', '', shift_value).split(':')[0]
                if cleaned and cleaned.lstrip('0') == str(start_hour):
                    match = True
            
            if match:
                workers.append((worker_name, phone))
        
        return workers
    
    def get_workers_for_outage(self, outage_start_hour: int, target_date: date = None) -> List[Tuple[str, str]]:
        """
        Get best 2 workers based on outage start time
        Logic:
        - Outage < 08:00 (Night/Morning) -> Workers starting at 20:00 ON PREVIOUS DAY
        - Outage 08:00 - 18:00 (Day) -> Workers starting at 09:00, 11:00, 13:00 on target_date
        - Outage >= 18:00 (Evening)  -> Workers starting at 13:00, 20:00 on target_date
        """
        if target_date is None:
            target_date = datetime.now().date()
        
        # Map outage time to preferred shift start times
        if outage_start_hour < 8:  # Early morning outage (e.g. 02:00)
            # The worker covering this started at 20:00 YESTERDAY
            lookup_date = target_date - timedelta(days=1)
            preferred_hours = [20]
            logging.info(f"Early morning outage ({outage_start_hour}:00), checking 20:00 shift on {lookup_date}")
        elif outage_start_hour < 18:  # Day outage
            lookup_date = target_date
            preferred_hours = [9, 11, 13]
        else:  # Evening/night outage (e.g. 22:00)
            lookup_date = target_date
            preferred_hours = [13, 20]  # Per user request
        
        all_candidates = []
        
        for hour in preferred_hours:
            workers = self.get_workers_for_time(lookup_date, hour)
            all_candidates.extend(workers)
        
        # Return unique candidates only (preserving order)
        unique_candidates = []
        seen_names = set()
        for worker in all_candidates:
            if worker[0] not in seen_names:
                unique_candidates.append(worker)
                seen_names.add(worker[0])
        
        return unique_candidates[:2]

