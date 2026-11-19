"""Middleware de integracao — comunicacao sincrona (REST) entre os servicos.

Fluxo: cliente -> middleware -> Catalogo -> Pedidos -> Pagamento
"""
import asyncio
import os
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

CATALOGO = os.getenv("CATALOGO_URL", "http://catalogo:8000")
PEDIDOS = os.getenv("PEDIDOS_URL", "http://pedidos:8000")
PAGAMENTO = os.getenv("PAGAMENTO_URL", "http://pagamento:8000")
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))

app = FastAPI(title="Middleware de Integracao — E-commerce", version="1.0.0")

# ------------------------------- Contratos -------------------------------
Metodo = Literal["PIX", "CARTAO", "BOLETO"]


class ProdutoRequest(BaseModel):
    id: int
    nome: str
    preco: float = Field(gt=0)
    descricao: str


class Item(BaseModel):
    produto_id: int
    quantidade: int = Field(gt=0)


class PedidoRequest(BaseModel):
    pedido_id: int
    cliente_id: int
    itens: list[Item]


class CheckoutRequest(PedidoRequest):
    pagamento_id: int
    metodo: Metodo


class Pedido(BaseModel):
    id: int
    cliente_id: int
    produtos: list[int]
    valor_total: float


class Pagamento(BaseModel):
    id: int
    pedido_id: int
    valor: float
    metodo: Metodo


# -------------------------------- Erros --------------------------------
class UpstreamError(Exception):
    def __init__(self, servico: str, status: int, detalhe: str):
        self.servico, self.status, self.detalhe = servico, status, detalhe


@app.exception_handler(UpstreamError)
async def tratar_erro(request: Request, exc: UpstreamError):
    return JSONResponse(
        status_code=exc.status, content={"detail": exc.detalhe, "servico": exc.servico}
    )


# ------------------------- Chamada REST sincrona -------------------------
async def chamar(servico: str, base: str, metodo: str, caminho: str, corpo=None):
    """Ponto unico de chamada aos servicos: traduz falhas em 502/503/504."""
    try:
        async with httpx.AsyncClient(base_url=base, timeout=TIMEOUT) as http:
            resposta = await http.request(metodo, caminho, json=corpo)
    except httpx.TimeoutException as exc:
        raise UpstreamError(servico, 504, f"timeout em {servico}") from exc
    except httpx.HTTPError as exc:
        raise UpstreamError(servico, 503, f"{servico} indisponivel") from exc

    if resposta.status_code >= 500:
        raise UpstreamError(servico, 502, f"{servico} respondeu {resposta.status_code}")
    if resposta.status_code >= 400:
        try:
            detalhe = str(resposta.json().get("detail", resposta.text))
        except ValueError:
            detalhe = resposta.text or f"HTTP {resposta.status_code}"
        raise UpstreamError(servico, resposta.status_code, detalhe)
    return resposta.json()


# ------------------------------- Endpoints -------------------------------
@app.get("/health", tags=["Saude"])
async def health():
    async def verificar(nome: str, base: str):
        try:
            await chamar(nome, base, "GET", "/health")
            return nome, "online"
        except UpstreamError as exc:
            return nome, exc.detalhe

    deps = dict(await asyncio.gather(
        verificar("catalogo", CATALOGO),
        verificar("pedidos", PEDIDOS),
        verificar("pagamento", PAGAMENTO),
    ))
    estado = "online" if all(v == "online" for v in deps.values()) else "degradado"
    return {"servico": "middleware", "status": estado, "dependencias": deps}


@app.post("/catalogo/produtos", status_code=201, tags=["Catalogo"])
async def cadastrar_produto(produto: ProdutoRequest):
    return await chamar("catalogo", CATALOGO, "POST", "/produtos", produto.model_dump())


async def montar_pedido(dados: PedidoRequest) -> Pedido:
    """Valida os itens no Catalogo e calcula o total (chamada sincrona)."""
    total = 0.0
    for item in dados.itens:
        produto = await chamar("catalogo", CATALOGO, "GET", f"/produtos/{item.produto_id}")
        total += produto["preco"] * item.quantidade
    return Pedido(
        id=dados.pedido_id,
        cliente_id=dados.cliente_id,
        produtos=[i.produto_id for i in dados.itens],
        valor_total=round(total, 2),
    )


@app.post("/pedidos", status_code=201, tags=["Pedidos"])
async def criar_pedido(dados: PedidoRequest):
    """Catalogo -> Pedidos (2 servicos)."""
    pedido = await montar_pedido(dados)
    return await chamar("pedidos", PEDIDOS, "POST", "/pedidos", pedido.model_dump())


@app.post("/checkout", status_code=201, tags=["Pedidos"])
async def checkout(dados: CheckoutRequest):
    """Catalogo -> Pedidos -> Pagamento (3 servicos)."""
    pedido = await montar_pedido(dados)
    criado = await chamar("pedidos", PEDIDOS, "POST", "/pedidos", pedido.model_dump())
    pago = await chamar(
        "pagamento", PAGAMENTO, "POST", "/pagamentos",
        Pagamento(
            id=dados.pagamento_id,
            pedido_id=pedido.id,
            valor=pedido.valor_total,
            metodo=dados.metodo,
        ).model_dump(),
    )
    return {"pedido": criado["pedido"], "pagamento": pago["pagamento"]}


@app.get("/pedidos/{pedido_id}", tags=["Pedidos"])
async def consultar_pedido(pedido_id: int):
    return await chamar("pedidos", PEDIDOS, "GET", f"/pedidos/{pedido_id}")