FROM python:3.12-slim
WORKDIR /app
# Copia e instala as dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copia os arquivos necessários para o Middleware
COPY main.py .
COPY broker.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
