"""
Observabilidade dos serviços.

O que este módulo adiciona a um app FastAPI:

1. Logs estruturados em JSON: uma linha JSON por evento, no stdout
   (o formato que Docker, Loki, ELK etc. leem).
2. Correlation ID: lido do cabeçalho ``X-Correlation-ID`` da requisição, ou
   gerado (UUID4) se não vier. Ele vai em todo log da requisição e volta no
   cabeçalho da resposta.
3. Métricas básicas no formato Prometheus, em ``GET /metrics``.

Uso no main.py:

    from observabilidade import configurar_observabilidade

    app = FastAPI(...)
    logger = configurar_observabilidade(app, "pedidos")
    logger.info("pedido_registrado", extra={"pedido_id": 1})

Ao chamar outro serviço, repasse o mesmo ID:

    from observabilidade import cabecalhos_de_propagacao
    httpx.get(url, headers=cabecalhos_de_propagacao())
"""

import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

CABECALHO_CORRELATION_ID = "X-Correlation-ID"

# Só aceita IDs "limpos" vindos de fora, para ninguém injetar texto nos logs.
_ID_VALIDO = re.compile(r"[A-Za-z0-9._-]{1,128}")

_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def obter_correlation_id() -> Optional[str]:
    """Correlation ID da requisição atual (None fora de uma requisição)."""
    return _correlation_id.get()


def cabecalhos_de_propagacao() -> dict:
    """Cabeçalhos para repassar o Correlation ID ao chamar outro serviço."""
    cid = _correlation_id.get()
    return {CABECALHO_CORRELATION_ID: cid} if cid else {}


# --------------------------------------------------------------------------
# Logs estruturados (JSON)
# --------------------------------------------------------------------------

# Atributos que todo LogRecord já tem; o resto veio de ``extra=`` e vai pro JSON.
_ATRIBUTOS_PADRAO = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "taskName",
    "color_message",  # o uvicorn manda a mensagem com cores do terminal aqui
}


class FormatadorJSON(logging.Formatter):
    def __init__(self, servico: str):
        super().__init__()
        self.servico = servico

    def format(self, record: logging.LogRecord) -> str:
        entrada = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "servico": self.servico,
            "logger": record.name,
            "mensagem": record.getMessage(),
            "correlation_id": _correlation_id.get(),
        }
        for chave, valor in record.__dict__.items():
            if chave not in _ATRIBUTOS_PADRAO and not chave.startswith("_"):
                entrada[chave] = valor
        if record.exc_info:
            entrada["excecao"] = self.formatException(record.exc_info)
        return json.dumps(entrada, ensure_ascii=False, default=str)


def _configurar_logs(servico: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatadorJSON(servico))

    raiz = logging.getLogger()
    raiz.handlers = [handler]
    raiz.setLevel(logging.INFO)

    # O uvicorn configura seus loggers em texto antes de importar o app;
    # aqui eles passam a sair pelo handler JSON.
    for nome in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(nome)
        lg.handlers = []
        lg.propagate = True

    # O access log do uvicorn é trocado pelo log "requisicao_concluida",
    # que já traz correlation_id, rota, status e duração.
    logging.getLogger("uvicorn.access").disabled = True


# --------------------------------------------------------------------------
# Métricas básicas (Prometheus)
# --------------------------------------------------------------------------

REQUISICOES = Counter(
    "http_requisicoes_total",
    "Total de requisicoes HTTP recebidas",
    ["servico", "metodo", "rota", "status"],
)
DURACAO = Histogram(
    "http_requisicao_duracao_segundos",
    "Tempo de resposta das requisicoes HTTP, em segundos",
    ["servico", "metodo", "rota"],
)
EM_ANDAMENTO = Gauge(
    "http_requisicoes_em_andamento",
    "Requisicoes sendo processadas neste momento",
    ["servico"],
)


def _rota_da_requisicao(request: Request) -> str:
    # Usa o molde da rota (/pedidos/{pedido_id}) e não o caminho real
    # (/pedidos/42), para não criar uma série de métrica por ID.
    rota = request.scope.get("route")
    return getattr(rota, "path", None) or "rota_desconhecida"


# --------------------------------------------------------------------------
# Ligando tudo no app
# --------------------------------------------------------------------------

def configurar_observabilidade(app: FastAPI, servico: str) -> logging.Logger:
    """Ativa logs JSON, Correlation ID e /metrics no app. Devolve o logger do serviço."""
    _configurar_logs(servico)
    logger_http = logging.getLogger(f"{servico}.http")

    @app.middleware("http")
    async def observar_requisicao(request: Request, call_next):
        recebido = request.headers.get(CABECALHO_CORRELATION_ID, "")
        cid = recebido if _ID_VALIDO.fullmatch(recebido) else str(uuid.uuid4())
        token = _correlation_id.set(cid)

        EM_ANDAMENTO.labels(servico).inc()
        inicio = time.perf_counter()
        status = 500
        try:
            resposta = await call_next(request)
            status = resposta.status_code
        except Exception:
            logger_http.exception("erro_nao_tratado", extra={"caminho": request.url.path})
            resposta = JSONResponse(
                {"detail": "Erro interno", "correlation_id": cid}, status_code=500
            )
        finally:
            duracao = time.perf_counter() - inicio
            rota = _rota_da_requisicao(request)
            EM_ANDAMENTO.labels(servico).dec()
            REQUISICOES.labels(servico, request.method, rota, str(status)).inc()
            DURACAO.labels(servico, request.method, rota).observe(duracao)

            if rota != "/metrics":
                nivel = (
                    logging.ERROR if status >= 500
                    else logging.WARNING if status >= 400
                    else logging.INFO
                )
                logger_http.log(
                    nivel,
                    "requisicao_concluida",
                    extra={
                        "metodo_http": request.method,
                        "rota": rota,
                        "caminho": request.url.path,
                        "status": status,
                        "duracao_ms": round(duracao * 1000, 2),
                    },
                )
            _correlation_id.reset(token)

        resposta.headers[CABECALHO_CORRELATION_ID] = cid
        return resposta

    @app.get("/metrics", include_in_schema=False)
    def metricas():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return logging.getLogger(servico)
