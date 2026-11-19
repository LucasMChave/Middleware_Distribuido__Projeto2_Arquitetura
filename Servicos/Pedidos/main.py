from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List
from uuid import uuid4

app = FastAPI(title="Serviço de Pedidos")
PEDIDOS = {}
class Item(BaseModel):
    produto_id: int
    nome: str
    preco_unitario: float = Field(gt=0)
    quantidade: int = Field(ge=1)
class NovoPedido(BaseModel):
    cliente_id: str
    itens: List[Item] = Field(min_length=1)

@app.get("/health")
def health(): return {"servico": "pedidos", "status": "online"}

@app.post("/pedidos", status_code=201)
def criar_pedido(dados: NovoPedido):
    itens = [x.model_dump() for x in dados.itens]
    pid = str(uuid4())
    total = round(sum(x["preco_unitario"] * x["quantidade"] for x in itens), 2)
    PEDIDOS[pid] = {"pedido_id": pid, "cliente_id": dados.cliente_id,
      "itens": itens, "preco_total": total, "status": "ABERTO"}
    return PEDIDOS[pid]

@app.get("/pedidos/{pedido_id}/itens")
def listar_itens(pedido_id: str):
    p = PEDIDOS.get(pedido_id)
    if not p: raise HTTPException(404, "Pedido não encontrado")
    return p["itens"]

@app.get("/pedidos/{pedido_id}/preco")
def preco_total(pedido_id: str):
    p = PEDIDOS.get(pedido_id)
    if not p: raise HTTPException(404, "Pedido não encontrado")
    return {"pedido_id": pedido_id, "preco_total": p["preco_total"]}

@app.post("/pedidos/{pedido_id}/finalizar")
def finalizar_pedido(pedido_id: str):
    p = PEDIDOS.get(pedido_id)
    if not p: raise HTTPException(404, "Pedido não encontrado")
    if p["status"] != "ABERTO": raise HTTPException(409, f"Pedido está {p['status']}")
    # Finalização local; não efetua pagamento.
    p["status"] = "AGUARDANDO_PAGAMENTO"
    return {"pedido_id": pedido_id, "status": p["status"],
      "valor": p["preco_total"], "proxima_etapa": "Middleware solicita pagamento"}
