FROM python:3.8-slim
USER root
WORKDIR /app
COPY . /app
COPY .env /app/.env
RUN pip install flask pyyaml
EXPOSE 5000
CMD ["python", "src/app.py"]
