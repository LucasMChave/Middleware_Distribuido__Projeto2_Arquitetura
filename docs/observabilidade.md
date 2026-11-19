# Observabilidade

Os três serviços (Catálogo, Pedidos e Pagamentos) têm:

- **Logs estruturados em JSON**, uma linha por evento no stdout.
- **Correlation ID** em toda requisição, no cabeçalho `X-Correlation-ID`.
- **Métricas básicas** no formato Prometheus, em `GET /metrics`.

Tudo está em `observabilidade.py`, um arquivo igual em cada pasta de serviço.
Ele fica repetido porque cada Dockerfile só enxerga a pasta do próprio serviço.
Se mudar um, copie para os outros dois.

## Como ativar num serviço

```python
from observabilidade import configurar_observabilidade

app = FastAPI(title="Serviço de Pedidos")
logger = configurar_observabilidade(app, "pedidos")

logger.info("pedido_registrado", extra={"pedido_id": 1, "valor_total": 99.9})
```

Tudo o que vai em `extra=` vira um campo do JSON.

## Logs estruturados

Cada log é uma linha JSON com os campos fixos `timestamp` (UTC), `nivel`, `servico`,
`logger`, `mensagem` e `correlation_id`, mais os campos de `extra`.

Toda requisição gera um log `requisicao_concluida`, com nível INFO para 2xx/3xx,
WARNING para 4xx e ERROR para 5xx:

```json
{"timestamp": "2026-11-18T14:03:12.418+00:00", "nivel": "INFO", "servico": "pedidos", "logger": "pedidos.http", "mensagem": "requisicao_concluida", "correlation_id": "teste-123", "metodo_http": "POST", "rota": "/pedidos", "caminho": "/pedidos", "status": 201, "duracao_ms": 3.41}
```

Logs de negócio, emitidos quando a operação dá certo. Os erros (404, 409) aparecem no
`requisicao_concluida` com nível WARNING.

| Serviço    | Eventos                                                         |
|------------|-----------------------------------------------------------------|
| Catálogo   | `compra_validada`                                               |
| Pedidos    | `pedido_criado`, `pedido_finalizado`                            |
| Pagamentos | `pagamento_criado`, `pagamento_aprovado`, `pagamento_cancelado` |

Os logs do próprio uvicorn também saem em JSON. O access log padrão dele foi
desligado, porque o `requisicao_concluida` já traz a mesma informação e ainda
inclui o Correlation ID.

## Correlation ID

1. Se a requisição traz `X-Correlation-ID`, o serviço usa esse valor.
   Só são aceitos letras, números, `.`, `_` e `-`, com até 128 caracteres.
2. Se não traz, ou se o valor é inválido, o serviço gera um UUID4.
3. O ID aparece em todos os logs daquela requisição e volta no cabeçalho
   `X-Correlation-ID` da resposta.
4. Em um erro 500 não tratado, a resposta também traz o ID no corpo:
   `{"detail": "Erro interno", "correlation_id": "..."}`.

**Para o Middleware:** ele ainda não repassa esse cabeçalho, então hoje cada serviço gera
o próprio ID. Ao chamar um serviço, o Middleware deve enviar o mesmo cabeçalho. Assim, uma chamada que passa por vários serviços aparece com o mesmo ID
em todos os logs.

```python
from observabilidade import cabecalhos_de_propagacao

httpx.post(f"{URL_PAGAMENTO}/pagamentos", json=dados, headers=cabecalhos_de_propagacao())
```

Fora de um serviço FastAPI, basta ler `X-Correlation-ID` da requisição que chegou
(ou gerar um UUID) e enviar o mesmo valor nas chamadas seguintes.

## Métricas

`GET /metrics` em cada serviço, no formato de texto do Prometheus:

| Métrica                            | Tipo      | Labels                                | Para quê                     |
|------------------------------------|-----------|---------------------------------------|------------------------------|
| `http_requisicoes_total`           | Counter   | `servico`, `metodo`, `rota`, `status` | Volume e taxa de erro        |
| `http_requisicao_duracao_segundos` | Histogram | `servico`, `metodo`, `rota`           | Latência (média, p95, p99)   |
| `http_requisicoes_em_andamento`    | Gauge     | `servico`                             | Carga no momento             |

O label `rota` usa o molde da rota (`/pedidos/{pedido_id}`), não o caminho real,
para não criar uma série por ID. Caminhos que não existem aparecem como
`rota_desconhecida`.

Também saem as métricas padrão do processo Python (`process_*`, `python_gc_*`),
que o `prometheus-client` gera sozinho.

Exemplos de consulta no Prometheus:

```promql
# requisições por segundo, por serviço
sum by (servico) (rate(http_requisicoes_total[1m]))

# porcentagem de respostas 5xx
sum(rate(http_requisicoes_total{status=~"5.."}[5m])) / sum(rate(http_requisicoes_total[5m]))

# latência p95 por rota
histogram_quantile(0.95, sum by (le, rota) (rate(http_requisicao_duracao_segundos_bucket[5m])))
```

## Testando

Com um serviço rodando (exemplo: Pedidos em `localhost:8002`):

```bash
# Envia um Correlation ID e confere que ele volta no cabeçalho da resposta
curl -i -X POST http://localhost:8002/pedidos \
  -H "Content-Type: application/json" \
  -H "X-Correlation-ID: teste-123" \
  -d '{"cliente_id": "c1", "itens": [{"produto_id": 2, "nome": "Ford Ka", "preco_unitario": 13900.0, "quantidade": 1}]}'

# Logs em JSON
docker logs servico_pedidos

# Métricas
curl http://localhost:8002/metrics
```
