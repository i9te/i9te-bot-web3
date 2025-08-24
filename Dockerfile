# Pakai Python 3.11.9 official slim
FROM python:3.11.9-slim

# Set workdir
WORKDIR /app

# Install dependencies yang dibutuhin psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements & install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Jalankan bot
CMD ["python", "bot.py"]