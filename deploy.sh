#!/bin/bash

# Configuration
BOT_NAME="gena_bot"

echo "🚀 Starting GenaBot Deployment..."

# 1. Check for .env
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found. Please create it first."
    exit 1
fi

# 2. Start Containers
echo "📦 Building and starting containers..."
docker-compose up -d --build

# 3. Wait for DB to be healthy
echo "⏳ Waiting for database to be ready..."
until docker-compose exec db pg_isready -U postgres > /dev/null 2>&1; do
  sleep 1
done

# 4. Initialize Schema (Alembic)
echo "🏗️ Running database migrations (Alembic)..."
docker-compose exec bot alembic upgrade head

# 5. Migration Prompt
read -p "❓ Do you want to migrate data from Supabase? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🔄 Running migration script..."
    docker-compose exec bot python migrate_db.py
fi

echo "✅ Deployment finished successfully!"
echo "📡 Monitoring logs: docker-compose logs -f bot"
