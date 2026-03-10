from fastapi import Cookie, HTTPException, status
from typing import Optional
from app.core.security import verify_token
import logging

logger = logging.getLogger(__name__)


def _extrair_payload(auth_token: Optional[str]) -> dict:
    """
    Extrai e verifica o payload JWT do cookie auth_token.
    Lança HTTPException 401 em qualquer caso de falha.
    """
    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Não autenticado",
        )

    try:
        payload = verify_token(auth_token)
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
    auth_token: Optional[str] = Cookie(None)
) -> str:
    """
    Verifica o JWT do cookie e retorna o user_id (campo 'sub').
    Lança 401 se o token for inválido, ausente ou expirado.
    """
    payload = _extrair_payload(auth_token)
    user_id = payload["sub"]
    logger.info(f"✅ Usuário autenticado: {user_id}")
    return user_id


async def get_current_user_optional(
    auth_token: Optional[str] = Cookie(None)
) -> Optional[str]:
    """
    Versão opcional. Retorna user_id ou None se não houver token.
    Não lança exceção.
    """
    if not auth_token:
        return None
    try:
        payload = _extrair_payload(auth_token)
        return payload["sub"]
    except HTTPException:
        return None


async def get_current_user(
    auth_token: Optional[str] = Cookie(None)
) -> dict:
    """
    Retorna dict com id, email e is_admin extraídos do JWT do cookie.
    """
    payload = _extrair_payload(auth_token)
    return {
        "id": payload["sub"],
        "email": payload.get("email"),
        "is_admin": payload.get("is_admin", False),
    }


async def get_admin_user(
    auth_token: Optional[str] = Cookie(None)
) -> str:
    """
    Verifica que o usuário é administrador (campo is_admin no JWT).
    Lança 403 se não for admin.
    """
    payload = _extrair_payload(auth_token)
    if not payload.get("is_admin", False):
        logger.warning(f"Acesso admin negado para user_id={payload.get('sub')}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso negado: você não tem permissão de administrador",
        )
    logger.info(f"Admin autenticado: {payload.get('email')}")
    return payload["sub"]
