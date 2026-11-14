
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(
    title="Serviço de Catálogo",
    version="1.0.0"
)

class Produto(BaseModel):
    id: int
    nome: str
    preco: float
    descricao: str

# Dados locais do serviço
produtos = {}

@app.get("/health")
def health():
    return {"servico": "catalogo", "status": "online"}

@app.post("/produtos")
def cadastrar_produto(produto: Produto):
    if produto.id in produtos:
        raise HTTPException(409, "Produto já cadastrado")

    produtos[produto.id] = produto
    return {"mensagem": "Produto cadastrado", "produto": produto}

@app.get("/produtos")
def listar_produtos():
    return list(produtos.values())

@app.get("/produtos/{produto_id}")
def consultar_produto(produto_id: int):
    if produto_id not in produtos:
        raise HTTPException(404, "Produto não encontrado")

    return produtos[produto_id]
