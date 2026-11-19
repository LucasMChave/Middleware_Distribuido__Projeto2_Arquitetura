from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Serviço de Catálogo")
PRODUTOS = {
  1: {"id": 1, "nome": "Hyundai Hb20s 1.0 12v Flex Vision Manual", "descricao": "0KM, Direto de fabrica, com GPS imbutido", "preco": 62990.0, "estoque": 50},
  2: {"id": 2, "nome": "Ford Ka", "descricao": "Usado, Compacto, peças disponiveis separadas", "preco": 13900.0, "estoque": 20},
  3: {"id": 3, "nome": "Lente Pisca Retrovisor Cruze 2011 2012 2013 2014", "descricao": "Peças para substituição", "preco": 45.0, "estoque": 1000},
}
class Compra(BaseModel):
    quantidade: int = Field(default=1, ge=1)

@app.get("/health")
def health(): return {"servico": "catalogo", "status": "online"}

@app.get("/catalogo")
def listar_catalogo(): return list(PRODUTOS.values())

@app.get("/catalogo/{produto_id}")
def ler_item(produto_id: int):
    if produto_id not in PRODUTOS: raise HTTPException(404, "Produto não encontrado")
    return PRODUTOS[produto_id]

@app.post("/catalogo/{produto_id}/comprar")
def comprar_item(produto_id: int, compra: Compra):
    produto = PRODUTOS.get(produto_id)
    if not produto: raise HTTPException(404, "Produto não encontrado")
    if compra.quantidade > produto["estoque"]: raise HTTPException(409, "Estoque insuficiente")
    # Prepara os dados; criação efetiva do pedido será responsabilidade do Pedido via middleware.
    return {"status": "validado", "item": {"produto_id": produto_id, "nome": produto["nome"],
      "preco_unitario": produto["preco"], "quantidade": compra.quantidade,
      "subtotal": round(produto["preco"] * compra.quantidade, 2)},
      "proxima_etapa": "Middleware encaminha o item ao Serviço de Pedidos"}
