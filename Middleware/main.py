from __future__ import annotations

import os
from typing import Any

import httpx 
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import asyncio
from uuid import uuid4
from contextlib import asynccontextmanager, suppress

from broker import (
    conectar_broker,
    desconectar_broker,
    publicar_mensagem,
    consumir_mensagens
)

CATALOGO_URL = os.getenv("CATALOGO_URL", "http://catalogo:8000")
PEDIDOS_URL = os.getenv("PEDIDOS_URL", "http://pedidos:8000")
PAGAMENTOS_URL = os.getenv("PAGAMENTOS_URL", "http://pagamentos:8000")

BROKER_URL = os.getenv(
    "BROKER_URL",
    "amqp://app:senha_dev_123@rabbitmq:5672/"
)

FILA_COMPRAS = "fila.compras"

# Armazenamento temporário dos resultados das compras
COMPRAS = {}



@asynccontextmanager
async def lifespan(app: FastAPI):

    await conectar_broker(BROKER_URL)

    # Inicia o consumidor em segundo plano
    app.state.tarefa_consumidor = asyncio.create_task(
        consumir_mensagens(
            FILA_COMPRAS,
            processar_mensagem_compra
        )
    )

    print("Middleware iniciado.")
    print("Consumidor de compras ativo.")

    yield

    # Encerra o consumidor antes de fechar a conexão
    app.state.tarefa_consumidor.cancel()

    with suppress(asyncio.CancelledError):
        await app.state.tarefa_consumidor

    await desconectar_broker()

app = FastAPI(
    title="Middleware de Integração",
    description=(
        "Ponto único de entrada para coordenar Catálogo, Pedidos e Pagamentos. "
        "Os serviços não se comunicam diretamente."
    ),
    version="1.0.0",
    lifespan=lifespan
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

# ---------------------- RABBITMQ (Teste Broker) -----------------------

@app.post("/teste/broker")
async def testar_broker():

    mensagem = {
        "evento": "teste",
        "origem": "middleware",
        "mensagem": "Comunicação com RabbitMQ funcionando!"
    }

    await publicar_mensagem(
        "fila.teste",
        mensagem
    )

    return {
        "status": "mensagem_publicada",
        "fila": "fila.teste",
        "dados": mensagem
    }

# ---------------------- FLUXO DE COMPRA COMPLETO ----------------------


async def processar_compra(dados: CompraRequest):
    """
    Executa o fluxo HTTP existente entre os microsserviços.
    Esta função será chamada pelo consumidor RabbitMQ.
    """

    async with httpx.AsyncClient(timeout=15.0) as client:

        # 1. Validar produto no Catálogo
        item_validado = await requisitar(
            client,
            "Catálogo",
            "POST",
            f"{CATALOGO_URL}/catalogo/{dados.produto_id}/comprar",
            json={"quantidade": dados.quantidade},
        )

        item = item_validado.get("item")

        if not item:
            raise HTTPException(
                status_code=502,
                detail="O Catálogo não retornou os dados do item."
            )

        # 2. Criar pedido
        pedido = await requisitar(
            client,
            "Pedidos",
            "POST",
            f"{PEDIDOS_URL}/pedidos",
            json={
                "cliente_id": dados.cliente_id,
                "itens": [item],
            },
        )

        pedido_id = pedido.get("pedido_id") or pedido.get("id")

        if not pedido_id:
            raise HTTPException(
                status_code=502,
                detail="Pedidos não retornou o identificador."
            )

        # 3. Finalizar pedido
        pedido_finalizado = await requisitar(
            client,
            "Pedidos",
            "POST",
            f"{PEDIDOS_URL}/pedidos/{pedido_id}/finalizar",
        )

        # 4. Consultar preço
        preco = await requisitar(
            client,
            "Pedidos",
            "GET",
            f"{PEDIDOS_URL}/pedidos/{pedido_id}/preco",
        )

        valor = preco.get(
            "total",
            preco.get("preco_total", preco.get("valor"))
        )

        if valor is None:
            raise HTTPException(
                status_code=502,
                detail="Não foi possível identificar o preço total."
            )

        # 5. Criar pagamento
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

        pagamento_id = (
            pagamento.get("pagamento_id")
            or pagamento.get("id")
        )

        if not pagamento_id:
            raise HTTPException(
                status_code=502,
                detail="Pagamentos não retornou o identificador."
            )

        # 6. Finalizar pagamento
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

async def processar_mensagem_compra(mensagem: dict):
    compra_id = mensagem["compra_id"]

    print(f"[CONSUMIDOR] Processando compra: {compra_id}")

    COMPRAS[compra_id]["status"] = "PROCESSANDO"

    try:
        dados = CompraRequest(**mensagem["dados"])

        resultado = await processar_compra(dados)

        COMPRAS[compra_id] = {
            "status": "CONCLUIDA",
            "resultado": resultado
        }

        print(f"[CONSUMIDOR] Compra concluída: {compra_id}")

    except Exception as exc:

        detalhe = (
            exc.detail if isinstance(exc, HTTPException)
            else str(exc)
        )

        COMPRAS[compra_id] = {
            "status": "FALHOU",
            "erro": detalhe
        }

        print(f"[CONSUMIDOR] Compra falhou: {compra_id} - {detalhe}")

    
@app.post("/comprar", status_code=202)
async def comprar(dados: CompraRequest):
    """
    PRODUTOR:
    Recebe a solicitação e publica uma mensagem.
    Não executa diretamente a compra.
    """

    compra_id = str(uuid4())

    mensagem = {
        "compra_id": compra_id,
        "dados": dados.model_dump()
    }

    COMPRAS[compra_id] = {
        "status": "AGUARDANDO_PROCESSAMENTO"
    }

    try:
        await publicar_mensagem(
            FILA_COMPRAS,
            mensagem,
            correlation_id=compra_id
        )

    except Exception as exc:
        COMPRAS[compra_id] = {
            "status": "FALHA_PUBLICACAO",
            "erro": str(exc)
        }

        raise HTTPException(
            status_code=503,
            detail="Não foi possível enviar a compra ao RabbitMQ."
        ) from exc

    return {
        "mensagem": "Compra enviada para processamento.",
        "compra_id": compra_id,
        "status": "AGUARDANDO_PROCESSAMENTO"
    }


@app.get("/compras/{compra_id}")
async def consultar_compra(compra_id: str):

    compra = COMPRAS.get(compra_id)

    if compra is None:
        raise HTTPException(
            status_code=404,
            detail="Compra não encontrada."
        )

    return {
        "compra_id": compra_id,
        **compra
    }
