import hmac
import hashlib
import os
import json
from datetime import datetime
from fastapi import Request, HTTPException

SECRET_KEY = os.getenv("MIDDLEWARE_SECRET", "segredo-concessionaria-2026").encode()

def _log_security_event(service: str, corr_id: str, action: str, status: str):
    record = {
        "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "correlation_id": corr_id,
        "service": service,
        "mode": "SEGURANCA",
        "action": action,
        "status": status
    }
    print(json.dumps(record, ensure_ascii=False), flush=True)

def generate_api_hash(actor: str, role: str) -> str:
    message = f"{actor}:{role}".encode()
    return hmac.new(SECRET_KEY, message, hashlib.sha256).hexdigest()

def verify_api_hash(request: Request, allowed_roles: list[str]) -> dict:
    service_name = os.getenv("SERVICE_NAME", "unknown-service")
    corr_id = request.headers.get("X-Correlation-ID", "N/A")

    received_hash = request.headers.get("X-API-Hash")
    actor = request.headers.get("X-Actor")
    role = request.headers.get("X-Role")

    if not received_hash or not actor or not role:
        _log_security_event(service_name, corr_id, "Headers de autenticação ausentes", "401_UNAUTHORIZED")
        raise HTTPException(
            status_code=401,
            detail="Autenticação obrigatória: envie X-API-Hash, X-Actor e X-Role."
        )

    expected_hash = generate_api_hash(actor, role)
    if not hmac.compare_digest(received_hash, expected_hash):
        _log_security_event(service_name, corr_id, f"APIHash inválido para '{actor}'", "401_UNAUTHORIZED")
        raise HTTPException(
            status_code=401,
            detail="APIHash inválido: falha na verificação de autenticidade."
        )

    if role not in allowed_roles:
        _log_security_event(
            service_name, corr_id,
            f"Acesso negado para '{actor}' (papel='{role}'). Exigido: {allowed_roles}",
            "403_FORBIDDEN"
        )
        raise HTTPException(
            status_code=403,
            detail=f"Papel '{role}' não autorizado para acessar este recurso."
        )

    _log_security_event(service_name, corr_id, f"Acesso autorizado para '{actor}' ({role})", "200_AUTHORIZED")
    return {"actor": actor, "role": role}