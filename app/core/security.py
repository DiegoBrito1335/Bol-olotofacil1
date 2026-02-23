"""
Utilitários de segurança: criação e verificação de JWT.
Usa PyJWT com o algoritmo HS256 e SECRET_KEY configurado em .env.
"""

import jwt
from datetime import datetime, timedelta, timezone
from app.config import settings


def create_access_token(user_id: str, email: str, is_admin: bool) -> str:
    """
    Cria um JWT assinado com user_id, email e is_admin.
    Expira em ACCESS_TOKEN_EXPIRE_MINUTES (padrão: 12h).
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,      # subject = user_id
        "email": email,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> dict:
    """
    Verifica e decodifica um JWT.
    Lança ValueError com mensagem legível em caso de erro.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Sessão expirada. Faça login novamente.")
    except jwt.InvalidTokenError:
        raise ValueError("Token inválido. Faça login novamente.")
