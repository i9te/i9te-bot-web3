# Gunakan Python 3.11.9 official image
FROM python:3.11.9-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Jalankan bot/web server
CMD ["python", "bot.py"]