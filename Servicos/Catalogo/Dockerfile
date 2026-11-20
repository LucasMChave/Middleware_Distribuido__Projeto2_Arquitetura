
FROM python:3.11-slim

WORKDIR /app

COPY Servicos/Catalogo/requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt

COPY Servicos/Catalogo/main.py ./
COPY Servicos/Catalogo/observabilidade.py ./

RUN mkdir -p Middleware

COPY Middleware/api_hash.py ./Middleware/api_hash.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
