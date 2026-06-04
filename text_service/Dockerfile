FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common /app/common
COPY text_service /app/text_service
EXPOSE 8010
CMD ["python", "-m", "uvicorn", "text_service.main:app", "--host", "0.0.0.0", "--port", "8010"]

