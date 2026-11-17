from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4

app = FastAPI(title="Serviço de Pagamentos")
PAGAMENTOS = {}
class NovoPagamento(BaseModel):
    pedido_id: str
    valor: float = Field(gt=0)
    metodo: str = "simulado"

@app.get("/health")
def health(): return {"servico": "pagamentos", "status": "online"}

@app.post("/pagamentos", status_code=201)
def criar_pagamento(dados: NovoPagamento):
    pid = str(uuid4())
    PAGAMENTOS[pid] = {"pagamento_id": pid, "pedido_id": dados.pedido_id,
      "valor": round(dados.valor, 2), "metodo": dados.metodo, "status": "PENDENTE"}
    return PAGAMENTOS[pid]

@app.post("/pagamentos/{pagamento_id}/finalizar")
def finalizar_pagamento(pagamento_id: str):
    p = PAGAMENTOS.get(pagamento_id)
    if not p: raise HTTPException(404, "Pagamento não encontrado")
    if p["status"] != "PENDENTE": raise HTTPException(409, f"Pagamento está {p['status']}")
    # Aprovação simulada, sem gateway bancário.
    p["status"] = "APROVADO"
    return p

@app.post("/pagamentos/{pagamento_id}/cancelar")
def cancelar_pagamento(pagamento_id: str):
    p = PAGAMENTOS.get(pagamento_id)
    if not p: raise HTTPException(404, "Pagamento não encontrado")
    if p["status"] == "PENDENTE": p["status"] = "CANCELADO"
    elif p["status"] == "APROVADO": p["status"] = "ESTORNO_SOLICITADO"
    elif p["status"] not in ("CANCELADO", "ESTORNO_SOLICITADO"):
        raise HTTPException(409, f"Pagamento está {p['status']}")
    return p
