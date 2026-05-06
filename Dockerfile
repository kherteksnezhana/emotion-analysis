FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей (нужно для transformers)
RUN apt-get update && apt-get install -y gcc g++ && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Убедитесь, что main.py существует в корне
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]