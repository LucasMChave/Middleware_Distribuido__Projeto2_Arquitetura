import os
import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List
from uuid import uuid4
from observabilidade import configurar_observabilidade

app = FastAPI(title="Serviço de Pedidos")
logger = configurar_observabilidade(app, "pedidos")
PEDIDOS = {}


CATALOGO_URL = os.getenv(
    "CATALOGO_URL",
    "http://catalogo:8000"
)

CATALOGO_TIMEOUT_SECONDS = float(
    os.getenv("CATALOGO_TIMEOUT_SECONDS", "3.0")
)


class Pedido(BaseModel):
    id: int
    cliente_id: int
    produtos: List[int]
    valor_total: float

pedidos = {}


class Item(BaseModel):
    produto_id: int
    nome: str
    preco_unitario: float = Field(gt=0)
    quantidade: int = Field(ge=1)


class NovoPedido(BaseModel):
    cliente_id: str
    itens: List[Item] = Field(min_length=1)




@app.get("/health")
def health():
    return {"servico": "pedidos", "status": "online"}



def validar_produtos_no_catalogo(produtos: List[int]):
    """Consulta o catálogo respeitando o limite de tempo configurado."""

    try:
        with httpx.Client(
            timeout=CATALOGO_TIMEOUT_SECONDS
        ) as client:

            for produto_id in produtos:
                resposta = client.get(
                    f"{CATALOGO_URL}/produtos/{produto_id}"
                )

                if resposta.status_code == 404:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Produto {produto_id} não existe no catálogo"
                    )

                resposta.raise_for_status()

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=(
                "Timeout ao consultar o Serviço de Catálogo. "
                f"Limite: {CATALOGO_TIMEOUT_SECONDS} segundos."
            )
        )

    except httpx.HTTPStatusError:
        raise HTTPException(
            status_code=502,
            detail="O Serviço de Catálogo retornou uma resposta inválida."
        )

    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="Não foi possível conectar ao Serviço de Catálogo."
        )


@app.post("/pedidos")
def criar_pedido(pedido: Pedido):

    if pedido.id in pedidos:
        raise HTTPException(409, "Pedido já cadastrado")

    validar_produtos_no_catalogo(pedido.produtos)


@app.post("/pedidos", status_code=201)
def criar_pedido(dados: NovoPedido):
    itens = [x.model_dump() for x in dados.itens]
    pid = str(uuid4())

    total = round(
        sum(x["preco_unitario"] * x["quantidade"] for x in itens), 2
    )

    PEDIDOS[pid] = {
        "pedido_id": pid,
        "cliente_id": dados.cliente_id,
        "itens": itens,
        "preco_total": total,
        "status": "ABERTO"
    }

    logger.info(
        "pedido_criado",
        extra={
            "pedido_id": pid,
            "cliente_id": dados.cliente_id,
            "qtd_itens": len(itens),
            "preco_total": total
        }
    )

    return PEDIDOS[pid]


@app.get("/pedidos/{pedido_id}/itens")
def listar_itens(pedido_id: str):
    p = PEDIDOS.get(pedido_id)

    if not p:
        raise HTTPException(404, "Pedido não encontrado")

    return p["itens"]


@app.get("/pedidos/{pedido_id}/preco")
def preco_total(pedido_id: str):
    p = PEDIDOS.get(pedido_id)

    if not p:
        raise HTTPException(404, "Pedido não encontrado")

    return {
        "pedido_id": pedido_id,
        "preco_total": p["preco_total"]
    }


@app.post("/pedidos/{pedido_id}/finalizar")
def finalizar_pedido(pedido_id: str):
    p = PEDIDOS.get(pedido_id)

    if not p:
        raise HTTPException(404, "Pedido não encontrado")


    if p["status"] != "ABERTO":
        raise HTTPException(409, f"Pedido está {p['status']}")

    # Finalização local; não efetua pagamento.
    p["status"] = "AGUARDANDO_PAGAMENTO"

    logger.info(
        "pedido_finalizado",
        extra={
            "pedido_id": pedido_id,
            "valor": p["preco_total"]
        }
    )

    return {
        "pedido_id": pedido_id,
        "status": p["status"],
        "valor": p["preco_total"],
        "proxima_etapa": "Middleware solicita pagamento"
    }



@app.get("/pedidos")
def listar_pedidos():
    return list(pedidos.values())


@app.get("/pedidos/{pedido_id}")
def consultar_pedido(pedido_id: int):

    if pedido_id not in pedidos:

@app.post("/pedidos/{pedido_id}/confirmar-pagamento")
def confirmar_pagamento(pedido_id: str):
    p = PEDIDOS.get(pedido_id)

    if not p:

        raise HTTPException(404, "Pedido não encontrado")

    if p["status"] != "AGUARDANDO_PAGAMENTO":
        raise HTTPException(409, f"Pedido está {p['status']}")

    p["status"] = "PAGO"

    logger.info(
        "pagamento_confirmado",
        extra={
            "pedido_id": pedido_id,
            "valor": p["preco_total"]
        }
    )

    return {
        "pedido_id": pedido_id,
        "status": p["status"],
        "valor": p["preco_total"]
    }
