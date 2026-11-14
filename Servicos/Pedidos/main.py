
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(
    title="Serviço de Pedidos",
    version="1.0.0"
)

class Pedido(BaseModel):
    id: int
    cliente_id: int
    produtos: List[int]
    valor_total: float

# Dados locais do serviço
pedidos = {}

@app.get("/health")
def health():
    return {"servico": "pedidos", "status": "online"}

@app.post("/pedidos")
def criar_pedido(pedido: Pedido):
    if pedido.id in pedidos:
        raise HTTPException(409, "Pedido já cadastrado")

    # Não consulta o Serviço de Catálogo.
    # Os IDs e valores são recebidos na requisição.

    pedidos[pedido.id] = pedido

    return {
        "mensagem": "Pedido registrado",
        "pedido": pedido
    }

@app.get("/pedidos")
def listar_pedidos():
    return list(pedidos.values())

@app.get("/pedidos/{pedido_id}")
def consultar_pedido(pedido_id: int):
    if pedido_id not in pedidos:
        raise HTTPException(404, "Pedido não encontrado")

    return pedidos[pedido_id]
