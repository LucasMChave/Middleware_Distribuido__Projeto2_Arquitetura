# Contratos de API — Middleware (Comunicação Síncrona)

- Base URL: `http://localhost:8004` · Formato: `application/json`
- OpenAPI interativo: `http://localhost:8004/docs`
- Serviços integrados (redes internas): Catálogo `catalogo:8000`, Pedidos `pedidos:8000`, Pagamento `pagamento:8000`

## Endpoints

| Método | Rota | Serviços chamados | Sucesso |
|---|---|---|---|
| GET | `/health` | Catálogo + Pedidos + Pagamento | 200 |
| POST | `/catalogo/produtos` | Catálogo | 201 |
| POST | `/pedidos` | Catálogo → Pedidos | 201 |
| POST | `/checkout` | Catálogo → Pedidos → Pagamento | 201 |
| GET | `/pedidos/{id}` | Pedidos | 200 |

## Códigos de resposta

| Código | Significado |
|---|---|
| 200 | OK |
| 201 | Criado (middleware normaliza; o serviço de origem devolve 200) |
| 400 / 422 | Payload inválido (Pydantic) |
| 404 | Recurso não existe no serviço de origem |
| 409 | `id` já cadastrado no serviço |
| 502 | Serviço interno respondeu 5xx |
| 503 | Serviço interno inacessível |
| 504 | Timeout na chamada ao serviço interno |

Erro padronizado:
```json
{ "detail": "Produto não encontrado", "servico": "catalogo" }