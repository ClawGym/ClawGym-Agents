FROM python:3.11-slim
WORKDIR /app
COPY app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
# Copy only app code here (tests and data mounted/used externally)
COPY app/ /app/
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
# NOTE: Adjust this if module path is wrong relative to WORKDIR
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
