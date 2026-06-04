FROM python:3.10-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY audio_service /app/audio_service
EXPOSE 8020
CMD ["python", "-m", "uvicorn", "audio_service.main:app", "--host", "0.0.0.0", "--port", "8020"]

