
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal

app = FastAPI(
    title="Serviço de Pagamento",
    version="1.0.0"
)

class Pagamento(BaseModel):
    id: int
    pedido_id: int
    valor: float
    metodo: Literal["PIX", "CARTAO", "BOLETO"]

# Dados locais do serviço
pagamentos = {}

@app.get("/health")
def health():
    return {"servico": "pagamento", "status": "online"}

@app.post("/pagamentos")
def registrar_pagamento(pagamento: Pagamento):
    if pagamento.id in pagamentos:
        raise HTTPException(409, "Pagamento já cadastrado")

    # Não consulta o Serviço de Pedidos.
    # O pedido_id é recebido diretamente.

    pagamentos[pagamento.id] = {
        **pagamento.model_dump(),
        "status": "APROVADO"
    }

    return {
        "mensagem": "Pagamento registrado",
        "pagamento": pagamentos[pagamento.id]
    }

@app.get("/pagamentos")
def listar_pagamentos():
    return list(pagamentos.values())

@app.get("/pagamentos/{pagamento_id}")
def consultar_pagamento(pagamento_id: int):
    if pagamento_id not in pagamentos:
        raise HTTPException(404, "Pagamento não encontrado")

    return pagamentos[pagamento_id]
