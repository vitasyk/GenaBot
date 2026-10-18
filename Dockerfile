# Use official lightweight Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and install (all dependencies ship as wheels, no system packages needed)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Create directory for credentials if it doesn't exist
RUN mkdir -p credentials

# Run the bot
CMD ["python", "-m", "bot"]
