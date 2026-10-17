from datetime import date
from unittest.mock import MagicMock

from bot.services.google_sheets import ROSTER_FIRST_ROW, GoogleSheetsService


def _sheet(day: int, workers: list[tuple[str, str]]) -> list[list[str]]:
    """Header row with day numbers in columns 2.., roster rows starting at ROSTER_FIRST_ROW."""
    header = ["Ім'я", "Телефон"] + [str(d) for d in range(1, 32)]
    rows = [header] + [[""] * len(header) for _ in range(ROSTER_FIRST_ROW - 1)]
    for name, shift in workers:
        row = [name, "phone"] + [""] * 31
        row[2 + day - 1] = shift
        rows.append(row)
    return rows


def _service(worksheets: dict[str, list[list[str]]]) -> GoogleSheetsService:
    service = GoogleSheetsService()
    spreadsheet = MagicMock()
    spreadsheet.worksheet.side_effect = lambda name: MagicMock(get_all_values=MagicMock(return_value=worksheets[name]))
    service.client = MagicMock(open_by_key=MagicMock(return_value=spreadsheet))
    return service


def test_night_outage_on_first_day_reads_previous_month_sheet():
    # Regression: the sheet was picked by the current month, so 31.10 was searched in the November sheet
    service = _service({
        "10'26": _sheet(31, [("Петро О.", "20:00"), ("Витя С.", "09:00")]),
        "11'26": _sheet(1, [("Інший", "20:00")]),
    })

    workers = service.get_workers_for_outage(outage_start_hour=1, target_date=date(2026, 11, 1))

    assert workers == [("Петро О.", "phone")]


def test_missing_date_column_returns_nobody_instead_of_guessing():
    sheet = _sheet(5, [("Петро О.", "13:00")])
    sheet[0] = ["Ім'я", "Телефон"] + ["x"] * 31  # no day numbers in the header
    service = _service({"10'26": sheet})

    assert service.get_workers_for_time(date(2026, 10, 5), 13) == []
