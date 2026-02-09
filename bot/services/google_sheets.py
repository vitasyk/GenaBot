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
        
        day_num = target_date.day
        
        # Search in first few rows for date indicators
        for row_idx in range(min(3, len(all_values))):
            row = all_values[row_idx]
            for col_idx, cell in enumerate(row):
                cell_value = cell.strip()
                
                # Try multiple patterns:
                # 1. Exact match: "6"
                if cell_value == str(day_num):
                    logging.info(f"Found date column {col_idx} for {target_date} (exact match: '{cell_value}')")
                    return col_idx
                
                # 2. Day + number: "Чт 6", "Пн 3"
                if ' ' in cell_value:
                    parts = cell_value.split()
                    if len(parts) >= 2 and parts[-1].strip() == str(day_num):
                        logging.info(f"Found date column {col_idx} for {target_date} (pattern match: '{cell_value}')")
                        return col_idx
                
                # 3. Zero-padded: "06"
                if cell_value == f"{day_num:02d}":
                    logging.info(f"Found date column {col_idx} for {target_date} (zero-padded: '{cell_value}')")
                    return col_idx
        
        logging.warning(f"Could not find column for date {target_date}, using fallback")
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
        - Outage < 07:00 (Night/Morning) -> Workers starting at 20:00 ON PREVIOUS DAY
        - Outage 07:00 - 18:59 (Day) -> Workers whose shift started BEFORE outage (within 6h)
        - Outage >= 19:00 (Evening)  -> Workers starting at 13:00, 15:00, 17:00, 20:00 on target_date
        """
        if target_date is None:
            target_date = datetime.now().date()
        
        # Map outage time to preferred shift start times
        if outage_start_hour < 7:  # Early morning outage (e.g. 02:00)
            # The worker covering this started at 20:00 YESTERDAY
            lookup_date = target_date - timedelta(days=1)
            preferred_hours = [20]
            logging.info(f"Early morning outage ({outage_start_hour}:00), checking 20:00 shift on {lookup_date}")
        elif outage_start_hour < 19:  # Day outage
            lookup_date = target_date
            all_day_hours = [7, 8, 9, 11, 13, 15, 17]
            
            # Filter: only shifts that started BEFORE outage (within 8 hours)
            # Workers have 8-hour shifts, so include all shifts still in progress
            preferred_hours = [h for h in all_day_hours 
                               if h <= outage_start_hour 
                               and outage_start_hour - h <= 8]
            
            # Fallback: if no shifts match criteria, take earliest shift
            if not preferred_hours:
                preferred_hours = [min(all_day_hours)]
            
            logging.info(f"Day outage ({outage_start_hour}:00), checking shifts started at: {preferred_hours}")
        else:  # Evening/night outage (e.g. 19:00+)
            lookup_date = target_date
            preferred_hours = [13, 15, 17, 20]  # Evening and night shifts
            logging.info(f"Evening outage ({outage_start_hour}:00), checking shifts: {preferred_hours}")
        
        all_candidates = []
        
        # Reverse order to prioritize LATER/CLOSER shifts
        # (workers who are more likely still working)
        for hour in reversed(preferred_hours):
            workers = self.get_workers_for_time(lookup_date, hour)
            all_candidates.extend(workers)
        
        # Return unique candidates only (preserving order)
        unique_candidates = []
        seen_names = set()
        for worker in all_candidates:
            if worker[0] not in seen_names:
                unique_candidates.append(worker)
                seen_names.add(worker[0])
        
        return unique_candidates[:3]  # Return top 3 workers

    def get_all_worker_names(self) -> List[str]:
        """
        Extract unique worker names from rows 39-60 of the first column.
        """
        self._ensure_init()
        try:
            # We only need the first column of the specified rows
            # Rows 39-60 (index 38-59)
            all_values = self.worksheet.get_all_values()
            
            names = set()
            start_row_idx = 38
            end_row_idx = 60
            
            for row_idx in range(start_row_idx, min(end_row_idx, len(all_values))):
                row = all_values[row_idx]
                if row and row[0].strip():
                    name = row[0].strip()
                    # Skip some obvious headers if any (optional, based on sheet structure)
                    # "Прізвище та ім'я" or similar
                    if name.lower() not in ["прізвище", "імя", "прізвище та ім'я", "worker", "name"]:
                        names.add(name)
            
            return sorted(list(names))
        except Exception as e:
            logging.error(f"Failed to get all worker names: {e}")
            return []

