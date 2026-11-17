import os
import httpx

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(
    title="Serviço de Pedidos",
    version="1.0.0"
)

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
