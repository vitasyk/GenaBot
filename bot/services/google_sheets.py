import logging
import re
from datetime import date, timedelta
from typing import List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials

from bot.config import config
from bot.utils.clock import now_kyiv

# Only sheet rows 39-60 take part in refueling (0-based indexes 38..59)
ROSTER_FIRST_ROW = 38
ROSTER_END_ROW = 60


class GoogleSheetsService:
    """Reads the worker shift roster from Google Sheets (one worksheet per month, named MM'YY).

    gspread is blocking: call the public methods through asyncio.to_thread.
    """

    def __init__(self):
        self.client: gspread.Client | None = None
        self._worksheets: dict[str, gspread.Worksheet] = {}
        try:
            creds = Credentials.from_service_account_file(
                config.GOOGLE_CREDENTIALS_PATH,
                scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
            )
            self.client = gspread.authorize(creds)
        except Exception:
            logging.warning("Google Sheets init failed", exc_info=True)

    def _get_worksheet(self, target_date: date) -> gspread.Worksheet:
        """Worksheet of the month that contains target_date (not of the current month)."""
        if self.client is None or not config.SCHEDULE_SPREADSHEET_ID:
            raise RuntimeError("Google Sheets is not configured")

        worksheet_name = target_date.strftime("%m'%y")
        if worksheet_name not in self._worksheets:
            spreadsheet = self.client.open_by_key(config.SCHEDULE_SPREADSHEET_ID)
            self._worksheets[worksheet_name] = spreadsheet.worksheet(worksheet_name)
            logging.info(f"✅ Google Sheets connected to worksheet: {worksheet_name}")
        return self._worksheets[worksheet_name]

    def _find_date_column(self, target_date: date, all_values: List[List[str]]) -> Optional[int]:
        """Column index (0-based) whose header in the first rows is the day of month, or None."""
        day_num = str(target_date.day)
        for row in all_values[:3]:
            for col_idx, cell in enumerate(row):
                if cell.strip() == day_num:
                    return col_idx
        return None

    def get_workers_for_time(self, target_date: date, start_hour: int) -> List[Tuple[str, str]]:
        """
        Get workers who start work at specific hour on specific date
        Returns: [(name, phone), ...]
        """
        all_values = self._get_worksheet(target_date).get_all_values()

        date_col = self._find_date_column(target_date, all_values)
        if date_col is None:
            logging.warning(f"Could not find column for date {target_date}")
            return []

        workers = []
        for row in all_values[ROSTER_FIRST_ROW:ROSTER_END_ROW]:
            if len(row) <= date_col:
                continue

            # Column 0: name, column 1: phone, date column: shift start ("09:00", "9:00", "9")
            worker_name = row[0].strip()
            phone = row[1].strip() if len(row) > 1 else ""
            shift_value = row[date_col].strip()

            if shift_value:
                cleaned = re.sub(r'[^0-9:]', '', shift_value).split(':')[0]
                if cleaned and cleaned.lstrip('0') == str(start_hour):
                    workers.append((worker_name, phone))

        return workers

    def get_workers_for_outage(self, outage_start_hour: int, target_date: date | None = None) -> List[Tuple[str, str]]:
        """
        Get best 2 workers based on outage start time
        Logic:
        - Outage < 08:00 (Night/Morning) -> Workers starting at 20:00 ON PREVIOUS DAY
        - Outage 08:00 - 18:00 (Day) -> Workers starting at 09:00, 11:00, 13:00 on target_date
        - Outage >= 18:00 (Evening)  -> Workers starting at 13:00, 20:00 on target_date
        """
        if target_date is None:
            target_date = now_kyiv().date()

        if outage_start_hour < 8:
            lookup_date = target_date - timedelta(days=1)
            preferred_hours = [20]
            logging.info(f"Early morning outage ({outage_start_hour}:00), checking 20:00 shift on {lookup_date}")
        elif outage_start_hour < 18:
            lookup_date = target_date
            preferred_hours = [9, 11, 13]
        else:
            lookup_date = target_date
            preferred_hours = [13, 20]

        unique_candidates = []
        seen_names = set()
        for hour in preferred_hours:
            for worker in self.get_workers_for_time(lookup_date, hour):
                if worker[0] not in seen_names:
                    unique_candidates.append(worker)
                    seen_names.add(worker[0])

        return unique_candidates[:2]
