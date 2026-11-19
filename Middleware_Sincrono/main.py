
"""
Middleware de integracao — comunicacao sincrona (REST) entre os servicos.

Fluxo: cliente -> middleware -> Catalogo -> Pedidos -> Pagamentos
"""

import asyncio
import os
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


# ------------------------------- Configuracoes -------------------------------

CATALOGO = os.getenv("CATALOGO_URL", "http://catalogo:8000")
PEDIDOS = os.getenv("PEDIDOS_URL", "http://pedidos:8000")
PAGAMENTO = os.getenv("PAGAMENTO_URL", "http://pagamentos:8000")

TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "5"))

app = FastAPI(
    title="Middleware de Integracao — E-commerce",
    version="1.0.0"
)


# ------------------------------- Contratos -------------------------------

Metodo = Literal["PIX", "CARTAO", "BOLETO"]


class Item(BaseModel):
    produto_id: int
    quantidade: int = Field(gt=0)


class PedidoRequest(BaseModel):
    cliente_id: str
    itens: list[Item]


class CheckoutRequest(PedidoRequest):
    metodo: Metodo


# ------------------------------- Erros -------------------------------

class UpstreamError(Exception):
    def __init__(self, servico: str, status: int, detalhe: str):
        self.servico = servico
        self.status = status
        self.detalhe = detalhe


@app.exception_handler(UpstreamError)
async def tratar_erro(request: Request, exc: UpstreamError):
    return JSONResponse(
        status_code=exc.status,
        content={
            "detail": exc.detalhe,
            "servico": exc.servico
        }
    )


# ------------------------- Chamada REST sincrona -------------------------

async def chamar(
    servico: str,
    base: str,
    metodo: str,
    caminho: str,
    corpo=None
):
    """
    Centraliza as chamadas REST e traduz falhas em 502, 503 ou 504.
    """

    try:
        async with httpx.AsyncClient(
            base_url=base,
            timeout=TIMEOUT
        ) as http:

            resposta = await http.request(
                metodo,
                caminho,
                json=corpo
            )

    except httpx.TimeoutException as exc:
        raise UpstreamError(
            servico,
            504,
            f"Timeout em {servico}"
        ) from exc

    except httpx.HTTPError as exc:
        raise UpstreamError(
            servico,
            503,
            f"{servico} indisponivel"
        ) from exc

    if resposta.status_code >= 500:
        raise UpstreamError(
            servico,
            502,
            f"{servico} respondeu {resposta.status_code}"
        )

    if resposta.status_code >= 400:
        try:
            detalhe = str(
                resposta.json().get("detail", resposta.text)
            )
        except ValueError:
            detalhe = resposta.text or f"HTTP {resposta.status_code}"

        raise UpstreamError(
            servico,
            resposta.status_code,
            detalhe
        )

    return resposta.json()


# ------------------------------- Health Check -------------------------------

@app.get("/health", tags=["Saude"])
async def health():

    async def verificar(nome: str, base: str):
        try:
            await chamar(
                nome,
                base,
                "GET",
                "/health"
            )

            return nome, "online"

        except UpstreamError as exc:
            return nome, exc.detalhe

    deps = dict(
        await asyncio.gather(
            verificar("catalogo", CATALOGO),
            verificar("pedidos", PEDIDOS),
            verificar("pagamento", PAGAMENTO)
        )
    )

    estado = (
        "online"
        if all(v == "online" for v in deps.values())
        else "degradado"
    )

    return {
        "servico": "middleware",
        "status": estado,
        "dependencias": deps
    }


# ------------------------------- Catalogo -------------------------------

@app.get("/catalogo/produtos", tags=["Catalogo"])
async def listar_produtos():
    """
    Consulta os produtos cadastrados no Catalogo.
    """

    return await chamar(
        "catalogo",
        CATALOGO,
        "GET",
        "/catalogo"
    )


@app.get("/catalogo/produtos/{produto_id}", tags=["Catalogo"])
async def consultar_produto(produto_id: int):
    """
    Consulta um produto especifico no Catalogo.
    """

    return await chamar(
        "catalogo",
        CATALOGO,
        "GET",
        f"/catalogo/{produto_id}"
    )


# ------------------------------- Montagem do Pedido -------------------------------

async def montar_pedido(dados: PedidoRequest):
    """
    Consulta os produtos no Catalogo e monta os itens
    no formato esperado pelo Servico de Pedidos.
    """

    itens_pedido = []

    for item in dados.itens:

        produto = await chamar(
            "catalogo",
            CATALOGO,
            "GET",
            f"/catalogo/{item.produto_id}"
        )

        itens_pedido.append({
            "produto_id": item.produto_id,
            "nome": produto["nome"],
            "preco_unitario": produto["preco"],
            "quantidade": item.quantidade
        })

    return {
        "cliente_id": dados.cliente_id,
        "itens": itens_pedido
    }


# ------------------------------- Pedidos -------------------------------

@app.post("/pedidos", status_code=201, tags=["Pedidos"])
async def criar_pedido(dados: PedidoRequest):
    """
    Catalogo -> Pedidos.

    Consulta os produtos, monta os itens e encaminha
    os dados para o Servico de Pedidos.
    """

    pedido = await montar_pedido(dados)

    return await chamar(
        "pedidos",
        PEDIDOS,
        "POST",
        "/pedidos",
        pedido
    )


@app.get("/pedidos/{pedido_id}", tags=["Pedidos"])
async def consultar_pedido(pedido_id: str):
    """
    Consulta os itens e o preco total de um pedido.
    """

    itens, preco = await asyncio.gather(
        chamar(
            "pedidos",
            PEDIDOS,
            "GET",
            f"/pedidos/{pedido_id}/itens"
        ),
        chamar(
            "pedidos",
            PEDIDOS,
            "GET",
            f"/pedidos/{pedido_id}/preco"
        )
    )

    return {
        "pedido_id": pedido_id,
        "itens": itens,
        "preco_total": preco["preco_total"]
    }


# ------------------------------- Checkout -------------------------------

@app.post("/checkout", status_code=201, tags=["Pedidos"])
async def checkout(dados: CheckoutRequest):
    """
    Fluxo completo:
    Catalogo -> Pedidos -> Pagamentos.

    1. Consulta os produtos no Catalogo.
    2. Cria o pedido.
    3. Coloca o pedido em aguardando pagamento.
    4. Registra o pagamento.
    5. Finaliza o pagamento.
    6. Confirma o pagamento no pedido.
    """

    # 1. Consulta os produtos e monta o pedido
    pedido = await montar_pedido(dados)

    # 2. Cria o pedido
    criado = await chamar(
        "pedidos",
        PEDIDOS,
        "POST",
        "/pedidos",
        pedido
    )

    # 3. Coloca o pedido em aguardando pagamento
    await chamar(
        "pedidos",
        PEDIDOS,
        "POST",
        f"/pedidos/{criado['pedido_id']}/finalizar"
    )

    # 4. Prepara os dados do pagamento
    pagamento = {
        "pedido_id": criado["pedido_id"],
        "valor": criado["preco_total"],
        "metodo": dados.metodo
    }

    # 5. Registra o pagamento
    pago = await chamar(
        "pagamento",
        PAGAMENTO,
        "POST",
        "/pagamentos",
        pagamento
    )

    # 6. Finaliza o pagamento
    pagamento_finalizado = await chamar(
        "pagamento",
        PAGAMENTO,
        "POST",
        f"/pagamentos/{pago['pagamento_id']}/finalizar"
    )

    # 7. Confirma o pagamento no pedido
    pedido_confirmado = await chamar(
        "pedidos",
        PEDIDOS,
        "POST",
        f"/pedidos/{criado['pedido_id']}/confirmar-pagamento"
    )

    return {
        "pedido": pedido_confirmado,
        "pagamento": pagamento_finalizado
    }
