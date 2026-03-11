from fastapi import Cookie, HTTPException, Request, status
from typing import Optional
from app.core.security import verify_token
import logging

logger = logging.getLogger(__name__)


def _get_token(request: Request, auth_token: Optional[str]) -> Optional[str]:
    """Extrai token do cookie ou do header Authorization: Bearer (fallback para mobile/Safari)."""
    if auth_token:
        return auth_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def _extrair_payload(token: Optional[str]) -> dict:
    """
    Extrai e verifica o payload JWT.
    Lança HTTPException 401 em qualquer caso de falha.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
        )

    try:
        payload = verify_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sem identificação de usuário",
        )

    return payload


async def get_current_user_id(
    request: Request,
    auth_token: Optional[str] = Cookie(None),
) -> str:
    """
    Verifica o JWT do cookie ou header Bearer e retorna o user_id (campo 'sub').
    Lança 401 se o token for inválido, ausente ou expirado.
    """
    token = _get_token(request, auth_token)
    payload = _extrair_payload(token)
    user_id = payload["sub"]
    logger.info(f"✅ Usuário autenticado: {user_id}")
    return user_id


async def get_current_user_optional(
    request: Request,
    auth_token: Optional[str] = Cookie(None),
) -> Optional[str]:
    """
    Versão opcional. Retorna user_id ou None se não houver token.
    Não lança exceção.
    """
    token = _get_token(request, auth_token)
    if not token:
        return None
    try:
        payload = _extrair_payload(token)
        return payload["sub"]
    except HTTPException:
        return None


async def get_current_user(
    request: Request,
    auth_token: Optional[str] = Cookie(None),
) -> dict:
    """
    Retorna dict com id, email e is_admin extraídos do JWT.
    """
    token = _get_token(request, auth_token)
    payload = _extrair_payload(token)
    return {
        "id": payload["sub"],
        "email": payload.get("email"),
        "is_admin": payload.get("is_admin", False),
    }


async def get_admin_user(
    request: Request,
    auth_token: Optional[str] = Cookie(None),
) -> str:
    """
    Verifica que o usuário é administrador (campo is_admin no JWT).
    Lança 403 se não for admin.
    """
    token = _get_token(request, auth_token)
    payload = _extrair_payload(token)
    if not payload.get("is_admin", False):
        logger.warning(f"Acesso admin negado para user_id={payload.get('sub')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não tem permissão de administrador",
        )
    logger.info(f"Admin autenticado: {payload.get('email')}")
    return payload["sub"]
