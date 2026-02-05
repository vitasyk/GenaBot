
import asyncio
import logging
from datetime import datetime, date, timedelta, time
from unittest.mock import AsyncMock, MagicMock, patch

# Configure logging
logging.basicConfig(level=logging.INFO)

# Import services
from bot.services.session_service import SessionService
from bot.database.models import User

async def run_test():
    print("🚀 Starting Midnight Logic Verification Test...")
    
    # 1. Setup Mocks
    mock_session = AsyncMock()
    mock_bot = AsyncMock()
    
    service = SessionService(mock_session, bot=mock_bot)
    
    # Mock Parser Timeline
    today = date(2026, 2, 4)
    tomorrow = date(2026, 2, 5)
    
    # Case: Continuous outage from 23:00 today to 02:00 tomorrow
    mock_timeline = [
        datetime.combine(today, time(23, 0)),
        datetime.combine(tomorrow, time(0, 0)),
        datetime.combine(tomorrow, time(1, 0)),
    ]
    
    service.parser.get_outage_timeline = AsyncMock(return_value=mock_timeline)
    
    # Mock Google Sheets Workers
    # For a block starting at 23:00 (Evening Shift), expect workers starting at 13:00 or 20:00 today
    def mock_get_workers(outage_start_hour, target_date):
        print(f"DEBUG: Sheets lookup for {outage_start_hour}:00 on {target_date}")
        if target_date == today and outage_start_hour == 23:
            return [("Worker Evening 1", "phone1"), ("Worker Evening 2", "phone2")]
        return []

    service.sheets_service.get_workers_for_outage = MagicMock(side_effect=mock_get_workers)
    
    # Mock User Repository
    async def mock_get_user(name):
        return User(id=123, name=name)
    service.user_repo.get_by_sheet_name = AsyncMock(side_effect=mock_get_user)
    
    # Mock Session Repo
    service.repo.get_active_session = AsyncMock(return_value=None)
    service.repo.create_session = AsyncMock()
    
    # 2. Run check_power_outage at T-45m (Should NOT create session)
    with patch('bot.services.session_service.datetime') as mock_dt:
        mock_dt.now.return_value = datetime.combine(today, time(22, 15)) # 45m before 23:00
        mock_dt.combine = datetime.combine
        
        print("\n--- Test Case: T-45m (Should NOT create session) ---")
        await service.check_power_outage()
        service.repo.create_session.assert_not_called()
        print("Success: No session created too early.")

    # 3. Run check_power_outage at T-25m (Should create session)
    service.repo.create_session.reset_mock()
    with patch('bot.services.session_service.datetime') as mock_dt:
        mock_dt.now.return_value = datetime.combine(today, time(22, 35)) # 25m before 23:00
        mock_dt.combine = datetime.combine
        
        print("\n--- Test Case: T-25m (Should create session) ---")
        await service.check_power_outage()
        service.repo.create_session.assert_called_once()
        print("Success: Session created within 30m window.")
        
    # 4. Run check_power_outage at Deadline (Should trigger restoration alert)
    print("\n--- Test Case: Power Restoration Alert ---")
    active_session_mock = MagicMock()
    active_session_mock.id = 999
    active_session_mock.deadline = datetime.combine(tomorrow, time(2, 0))
    active_session_mock.status = "in_progress"
    active_session_mock.worker1_id = 123
    active_session_mock.worker2_id = 456
    
    service.repo.get_active_session = AsyncMock(return_value=active_session_mock)
    service.repo.update_status = AsyncMock()
    service.notifier.notify_user = AsyncMock()
    
    with patch('bot.services.session_service.datetime') as mock_dt:
        # Time is 02:00 AM (deadline reached)
        mock_dt.now.return_value = datetime.combine(tomorrow, time(2, 0))
        mock_dt.combine = datetime.combine
        
        await service.check_power_outage()
        
        # Verify notifications sent
        assert service.notifier.notify_user.call_count >= 1
        service.repo.update_status.assert_called_with(999, "completed")
        print("Success: Restoration alert sent and session marked completed.")

    print("\n✅ All Timing & Restoration tests passed!")

if __name__ == "__main__":
    asyncio.run(run_test())
