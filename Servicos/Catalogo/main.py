
import os
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field



class Produto(BaseModel):
    id: int
    nome: str
    preco: float
    descricao: str


# Dados locais do serviço
produtos = {}

from observabilidade import configurar_observabilidade

app = FastAPI(title="Serviço de Catálogo")
logger = configurar_observabilidade(app, "catalogo")
PRODUTOS = {
  1: {"id": 1, "nome": "Hyundai Hb20s 1.0 12v Flex Vision Manual", "descricao": "0KM, Direto de fabrica, com GPS imbutido", "preco": 62990.0, "estoque": 50},
  2: {"id": 2, "nome": "Ford Ka", "descricao": "Usado, Compacto, peças disponiveis separadas", "preco": 13900.0, "estoque": 20},
  3: {"id": 3, "nome": "Lente Pisca Retrovisor Cruze 2011 2012 2013 2014", "descricao": "Peças para substituição", "preco": 45.0, "estoque": 1000},
}
class Compra(BaseModel):
    quantidade: int = Field(default=1, ge=1)



@app.get("/health")

def health():
    return {"servico": "catalogo", "status": "online"}


@app.post("/produtos")
def cadastrar_produto(produto: Produto):

    if produto.id in produtos:
        raise HTTPException(409, "Produto já cadastrado")

    produtos[produto.id] = produto

    return {
        "mensagem": "Produto cadastrado",
        "produto": produto
    }


@app.get("/produtos")
def listar_produtos():
    return list(produtos.values())


@app.get("/produtos/{produto_id}")
def consultar_produto(produto_id: int):

    #simular um delay pra testar o timeout
    atraso = float(os.getenv("CATALOGO_DELAY_SECONDS", "0"))

    if atraso > 0:
        time.sleep(atraso)

    if produto_id not in produtos:
        raise HTTPException(404, "Produto não encontrado")

    return produtos[produto_id]

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
    logger.info("compra_validada", extra={"produto_id": produto_id,
      "quantidade": compra.quantidade, "estoque": produto["estoque"]})
    return {"status": "validado", "item": {"produto_id": produto_id, "nome": produto["nome"],
      "preco_unitario": produto["preco"], "quantidade": compra.quantidade,
      "subtotal": round(produto["preco"] * compra.quantidade, 2)},
      "proxima_etapa": "Middleware encaminha o item ao Serviço de Pedidos"}

