"""Hash de API compartilhado entre os servicos (HMAC-SHA256)."""
import hashlib
import hmac
import os

API_HASH_SECRET = os.getenv("API_HASH_SECRET", "dev-secret")


def _payload(actor: str, role: str) -> bytes:
    return f"{actor}:{role}".encode("utf-8")


def generate_api_hash(actor: str, role: str) -> str:
    """Gera o hash do ator+papel. Todos os containers usam o mesmo segredo."""
    return hmac.new(
        API_HASH_SECRET.encode("utf-8"), _payload(actor, role), hashlib.sha256
    ).hexdigest()


def verify_api_hash(actor: str, role: str, api_hash: str) -> bool:
    """Compara em tempo constante (evita timing attack)."""
    if not api_hash:
        return False
    return hmac.compare_digest(generate_api_hash(actor, role), api_hash)