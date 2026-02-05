import urllib.parse

# User provided inputs
RAW_DB_URL = "postgresql://postgres.oyyrwscugbypkcmjdhxg:RDHJjgqlRDs4fot4@aws-1-eu-west-1.pooler.supabase.com:6543/postgres"
RAW_REDIS_URL = "rediss://default:AUXjAAIncDJkOGFmZDc3ZGRkOWE0ZDE4YWE1MzMyZGI5NjliMTI4OHAyMTc4OTE@safe-hornet-17891.upstash.io:6379"
WEATHER_KEY = "337ac84102d3fa26f948c731ad975e13"

def process_db_url(url):
    # Remove prefix
    url = url.replace("postgresql://", "")
    
    # Split user:rest
    if "@" in url:
        user_pass, host_rest = url.split("@", 1)
        if ":" in user_pass:
            user, password = user_pass.split(":", 1)
            # URL Encode password
            encoded_password = urllib.parse.quote_plus(password)
            
            # Reassemble with async driver
            return f"postgresql+asyncpg://{user}:{encoded_password}@{host_rest}"
    
    return url

def create_env_file():
    final_db_url = process_db_url(RAW_DB_URL)
    
    env_content = f"""# === BOT Configuration ===
BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
ADMIN_IDS=[123456789]

# === SUPERBASE (Database) ===
DATABASE_URL={final_db_url}

# === UPSTASH (Redis) ===
REDIS_URL={RAW_REDIS_URL}

# === OPENWEATHERMAP (Weather) ===
WEATHER_API_KEY={WEATHER_KEY}
CITY_LAT=50.45
CITY_LON=30.52

# === SECURITY ===
SECRET_KEY=temp_secret_key_123

# === LOGGING ===
LOG_LEVEL=INFO
"""
    
    with open(".env", "w", encoding="utf-8") as f:
        f.write(env_content)
    
    print("Successfully created .env with encoded DB password.")
    print(f"Original DB URL: {RAW_DB_URL}")
    print(f"Encoded DB URL:  {final_db_url}")

if __name__ == "__main__":
    create_env_file()
