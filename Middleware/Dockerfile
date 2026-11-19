FROM python:3.11-slim

WORKDIR /app

COPY Middleware/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY Middleware/ /app/Middleware/

CMD ["uvicorn", "Middleware.main:app", "--host", "0.0.0.0", "--port", "8000"]