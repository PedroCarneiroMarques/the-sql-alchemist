FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py main.py ./
COPY src ./src
COPY data ./data

EXPOSE 8501

CMD ["streamlit", "run", "src/app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--server.headless", "true"]
