from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


CATALOGO_URL = os.getenv("CATALOGO_URL", "http://catalogo:8000")
PEDIDOS_URL = os.getenv("PEDIDOS_URL", "http://pedidos:8000")
PAGAMENTOS_URL = os.getenv("PAGAMENTOS_URL", "http://pagamentos:8000")

app = FastAPI(
    title="Middleware de Integração",
    description=(
        "Ponto único de entrada para coordenar Catálogo, Pedidos e Pagamentos. "
        "Os serviços não se comunicam diretamente."
    ),
    version="1.0.0",
)


class CompraRequest(BaseModel):
    cliente_id: str = Field(min_length=1)
    produto_id: int = Field(gt=0)
    quantidade: int = Field(gt=0)
    metodo_pagamento: str = "simulado"


class CriarPagamentoRequest(BaseModel):
    pedido_id: str = Field(min_length=1)
    valor: float = Field(gt=0)
    metodo: str = "simulado"


def tratar_erro_servico(servico: str, exc: httpx.HTTPStatusError) -> HTTPException:
    status = exc.response.status_code
    try:
        detalhe: Any = exc.response.json()
    except ValueError:
        detalhe = exc.response.text
    return HTTPException(
        status_code=502 if status >= 500 else status,
        detail={
            "erro": f"Falha retornada pelo serviço {servico}",
            "status_original": status,
            "resposta": detalhe,
        },
    )


async def requisitar(
    client: httpx.AsyncClient,
    servico: str,
    metodo: str,
    url: str,
    **kwargs: Any,
) -> Any:
    try:
        response = await client.request(metodo, url, **kwargs)
        response.raise_for_status()
        if response.status_code == 204 or not response.content:
            return None
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise tratar_erro_servico(servico, exc) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Não foi possível acessar o serviço {servico}: {exc}",
        ) from exc


@app.get("/health")
async def health():
    """Verifica se o middleware está ativo; não garante que os serviços estejam ativos."""
    return {"status": "online", "servicos": ["catalogo", "pedidos", "pagamentos"]}


@app.get("/health/servicos")
async def health_servicos():
    """Consulta a disponibilidade dos três serviços."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resultados = {}
        for nome, url in (
            ("catalogo", CATALOGO_URL),
            ("pedidos", PEDIDOS_URL),
            ("pagamentos", PAGAMENTOS_URL),
        ):
            try:
                response = await client.get(f"{url}/health")
                resultados[nome] = {
                    "status": "online" if response.is_success else "erro",
                    "http_status": response.status_code,
                }
            except httpx.RequestError:
                resultados[nome] = {"status": "offline"}
    return resultados


# --------------------------- CATÁLOGO ---------------------------

@app.get("/catalogo")
async def listar_catalogo():
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(client, "Catálogo", "GET", f"{CATALOGO_URL}/catalogo")


@app.get("/catalogo/{produto_id}")
async def consultar_produto(produto_id: int):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client, "Catálogo", "GET", f"{CATALOGO_URL}/catalogo/{produto_id}"
        )


# ---------------------------- PEDIDOS ----------------------------

@app.get("/pedidos/{pedido_id}/itens")
async def listar_itens_pedido(pedido_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client, "Pedidos", "GET", f"{PEDIDOS_URL}/pedidos/{pedido_id}/itens"
        )


@app.get("/pedidos/{pedido_id}/preco")
async def consultar_preco_pedido(pedido_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client, "Pedidos", "GET", f"{PEDIDOS_URL}/pedidos/{pedido_id}/preco"
        )


@app.post("/pedidos/{pedido_id}/finalizar")
async def finalizar_pedido(pedido_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client, "Pedidos", "POST", f"{PEDIDOS_URL}/pedidos/{pedido_id}/finalizar"
        )


# --------------------------- PAGAMENTOS --------------------------

@app.post("/pagamentos")
async def criar_pagamento(dados: CriarPagamentoRequest):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client,
            "Pagamentos",
            "POST",
            f"{PAGAMENTOS_URL}/pagamentos",
            json=dados.model_dump(),
        )


@app.post("/pagamentos/{pagamento_id}/finalizar")
async def finalizar_pagamento(pagamento_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client,
            "Pagamentos",
            "POST",
            f"{PAGAMENTOS_URL}/pagamentos/{pagamento_id}/finalizar",
        )


@app.post("/pagamentos/{pagamento_id}/cancelar")
async def cancelar_pagamento(pagamento_id: str):
    async with httpx.AsyncClient(timeout=10.0) as client:
        return await requisitar(
            client,
            "Pagamentos",
            "POST",
            f"{PAGAMENTOS_URL}/pagamentos/{pagamento_id}/cancelar",
        )


# ---------------------- FLUXO DE COMPRA COMPLETO ----------------------

@app.post("/comprar")
async def comprar(dados: CompraRequest):
    """
    Orquestra a compra:
      1. valida produto/estoque no Catálogo;
      2. cria o pedido em Pedidos;
      3. finaliza o pedido;
      4. cria o pagamento;
      5. finaliza o pagamento.

    Este fluxo é síncrono e demonstrativo. Não implementa transação distribuída
    nem garantia de compensação em caso de falha após uma etapa já concluída.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Catálogo valida produto, quantidade e estoque.
        item_validado = await requisitar(
            client,
            "Catálogo",
            "POST",
            f"{CATALOGO_URL}/catalogo/{dados.produto_id}/comprar",
            json={"quantidade": dados.quantidade},
        )

        # 2. Middleware envia o snapshot do item para criação do pedido.
        pedido = await requisitar(
            client,
            "Pedidos",
            "POST",
            f"{PEDIDOS_URL}/pedidos",
            json={
                "cliente_id": dados.cliente_id,
                "itens": [item_validado],
            },
        )

        pedido_id = pedido.get("pedido_id") or pedido.get("id")
        if not pedido_id:
            raise HTTPException(
                status_code=502,
                detail={
                    "erro": "O serviço Pedidos não retornou o identificador do pedido.",
                    "resposta": pedido,
                },
            )

        # 3. Finaliza a etapa do pedido antes do pagamento.
        pedido_finalizado = await requisitar(
            client,
            "Pedidos",
            "POST",
            f"{PEDIDOS_URL}/pedidos/{pedido_id}/finalizar",
        )

        # 4. Usa o total calculado pelo serviço Pedidos, não um valor enviado pelo cliente.
        preco = await requisitar(
            client,
            "Pedidos",
            "GET",
            f"{PEDIDOS_URL}/pedidos/{pedido_id}/preco",
        )
        valor = preco.get("total", preco.get("preco_total", preco.get("valor")))
        if valor is None:
            raise HTTPException(
                status_code=502,
                detail={
                    "erro": "Não foi possível identificar o total retornado por Pedidos.",
                    "resposta": preco,
                    "pedido_id": pedido_id,
                },
            )

        # 5. Cria e aprova o pagamento simulado.
        pagamento = await requisitar(
            client,
            "Pagamentos",
            "POST",
            f"{PAGAMENTOS_URL}/pagamentos",
            json={
                "pedido_id": str(pedido_id),
                "valor": valor,
                "metodo": dados.metodo_pagamento,
            },
        )

        pagamento_id = pagamento.get("pagamento_id") or pagamento.get("id")
        if not pagamento_id:
            raise HTTPException(
                status_code=502,
                detail={
                    "erro": "O serviço Pagamentos não retornou o identificador do pagamento.",
                    "resposta": pagamento,
                    "pedido_id": pedido_id,
                },
            )

        pagamento_finalizado = await requisitar(
            client,
            "Pagamentos",
            "POST",
            f"{PAGAMENTOS_URL}/pagamentos/{pagamento_id}/finalizar",
        )

        return {
            "mensagem": "Fluxo de compra executado.",
            "produto_validado": item_validado,
            "pedido": pedido,
            "pedido_finalizado": pedido_finalizado,
            "valor_cobrado": valor,
            "pagamento": pagamento,
            "pagamento_finalizado": pagamento_finalizado,
        }
