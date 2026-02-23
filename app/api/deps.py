from fastapi import Header, HTTPException, status
from typing import Optional
from app.core.security import verify_token
import logging

logger = logging.getLogger(__name__)


def _extrair_payload(authorization: Optional[str]) -> dict:
    """
    Extrai e verifica o payload JWT do header Authorization.
    Lança HTTPException 401 em qualquer caso de falha.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autorização não fornecido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato inválido. Use: Bearer {token}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = verify_token(parts[1])
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sem identificação de usuário",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user_id(
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Verifica o JWT e retorna o user_id (campo 'sub').
    Lança 401 se o token for inválido, ausente ou expirado.
    """
    payload = _extrair_payload(authorization)
    user_id = payload["sub"]
    logger.info(f"✅ Usuário autenticado: {user_id}")
    return user_id


async def get_current_user_optional(
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Versão opcional. Retorna user_id ou None se não houver token.
    Não lança exceção.
    """
    if not authorization:
        return None
    try:
        payload = _extrair_payload(authorization)
        return payload["sub"]
    except HTTPException:
        return None


async def get_current_user(
    authorization: Optional[str] = Header(None)
) -> dict:
    """
    Retorna dict com id, email e is_admin extraídos do JWT.
    """
    payload = _extrair_payload(authorization)
    return {
        "id": payload["sub"],
        "email": payload.get("email"),
        "is_admin": payload.get("is_admin", False),
    }


async def get_admin_user(
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Verifica que o usuário é administrador (campo is_admin no JWT).
    Lança 403 se não for admin.
    """
    payload = _extrair_payload(authorization)
    if not payload.get("is_admin", False):
        logger.warning(f"Acesso admin negado para user_id={payload.get('sub')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não tem permissão de administrador",
        )
    logger.info(f"Admin autenticado: {payload.get('email')}")
    return payload["sub"]
