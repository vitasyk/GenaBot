from sqlalchemy.dialects import postgresql

from bot.config import Settings
from bot.database.models import Base, RefuelSession, SessionStatus

REQUIRED_ENV = (
    "BOT_TOKEN=1:x\nADMIN_IDS=[1]\nDATABASE_URL=postgresql+asyncpg://u:p@h/db\n"
    "REDIS_URL=redis://h\nWEATHER_API_KEY=k\nCITY_LAT=1\nCITY_LON=2\n"
)


def test_settings_ignore_retired_keys_in_env_file(tmp_path, monkeypatch):
    # prod .env still has SECRET_KEY and LOG_FORMAT; they must not crash startup
    for line in REQUIRED_ENV.splitlines():
        monkeypatch.delenv(line.split("=")[0], raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(REQUIRED_ENV + "SECRET_KEY=old\nLOG_FORMAT=console\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.CITY_LON == 2
    assert not hasattr(settings, "SECRET_KEY")
    assert not hasattr(settings, "LOG_FORMAT")


def test_refuel_session_status_stays_plain_varchar():
    ddl = RefuelSession.__table__.c.status.type.compile(dialect=postgresql.dialect())
    assert ddl == "VARCHAR"
    assert RefuelSession.__table__.c.status.default.arg is SessionStatus.pending


def test_session_status_formats_as_its_value():
    # handlers put s.status straight into messages
    assert f"{SessionStatus.completed}" == "completed"


def test_unused_shift_tables_are_gone():
    assert "shifts" not in Base.metadata.tables
    assert "worker_shifts" not in Base.metadata.tables
