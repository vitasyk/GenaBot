-- Створіть типи даних (ENUM)
CREATE TYPE userrole AS ENUM ('admin', 'worker');
CREATE TYPE genstatus AS ENUM ('stopped', 'running');

-- Таблиця користувачів
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    name VARCHAR NOT NULL,
    role userrole DEFAULT 'worker'
);

-- Таблиця складу (Inventory)
CREATE TABLE IF NOT EXISTS inventory (
    id SERIAL PRIMARY KEY,
    fuel_cans INTEGER DEFAULT 0
);

-- Таблиця генераторів
CREATE TABLE IF NOT EXISTS generators (
    id SERIAL PRIMARY KEY,
    name VARCHAR UNIQUE NOT NULL,
    status genstatus DEFAULT 'stopped',
    current_run_start TIMESTAMP,
    fuel_level FLOAT DEFAULT 0.0,
    tank_capacity FLOAT DEFAULT 40.0,
    consumption_rate FLOAT DEFAULT 2.0
);

-- Таблиця логів (LogEvent)
CREATE TABLE IF NOT EXISTS logs (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    action VARCHAR NOT NULL,
    details VARCHAR,
    timestamp TIMESTAMP DEFAULT NOW()
);

-- Створення початкового запису в Inventory (щоб було хоч щось)
INSERT INTO inventory (fuel_cans) VALUES (0);

-- Створення генераторів
INSERT INTO generators (name, status) VALUES ('GEN-1 (003)', 'stopped'), ('GEN-2 (038)', 'stopped');
