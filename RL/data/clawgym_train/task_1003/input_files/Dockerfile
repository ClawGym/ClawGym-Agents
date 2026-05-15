FROM python:3.10-slim
ARG COMMUNITY_API_TOKEN
ENV COMMUNITY_API_TOKEN=${COMMUNITY_API_TOKEN}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-c", "print('Service app started')"]
