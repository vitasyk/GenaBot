ALTER TABLE refuel_sessions ADD COLUMN worker3_id INTEGER REFERENCES users(id);
ALTER TABLE worker_shifts ADD COLUMN worker3_id INTEGER REFERENCES users(id);
