FROM python:3.9-slim
WORKDIR /app
COPY app/ app/
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt || true
CMD ["python", "-m", "app.metrics"]
