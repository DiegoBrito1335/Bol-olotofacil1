from fastapi import Header, HTTPException, status
from typing import Optional
import logging

logger = logging.getLogger(__name__)


async def get_current_user_id(
    authorization: Optional[str] = Header(None)
) -> str:
    """
    Extrai o ID do usuário do token de autorização.

    MODO DE TESTE: Aceita qualquer UUID no formato Bearer {UUID}
    """

    if not authorization:
        logger.error("Authorization header não fornecido")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autorização não fornecido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        parts = authorization.split()

        if len(parts) != 2 or parts[0].lower() != "bearer":
            logger.error(f"Formato inválido: {authorization}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Formato de token inválido. Use: Bearer {UUID}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = parts[1].strip()

        if not user_id:
            logger.error("Token vazio")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token vazio",
                headers={"WWW-Authenticate": "Bearer"},
            )

        logger.info(f"✅ Usuário autenticado: {user_id}")
        return user_id

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Erro ao processar token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Erro ao processar token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_optional(
    authorization: Optional[str] = Header(None)
) -> Optional[str]:
    """
    Versão opcional do get_current_user_id.
    Retorna o ID do usuário se autenticado, ou None se não estiver.
    Não lança exceção se não houver token.
    """

    if not authorization:
        return None

    try:
        parts = authorization.split()

        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        user_id = parts[1].strip()

        if not user_id:
            return None

        logger.info(f"✅ Usuário autenticado (opcional): {user_id}")
        return user_id

    except Exception as e:
        logger.warning(f"⚠️ Erro ao processar token opcional: {str(e)}")
        return None


async def get_current_user(
    authorization: Optional[str] = Header(None)
) -> dict:
    """
    Retorna informações completas do usuário autenticado.
    Dependency obrigatória.
    """
    user_id = await get_current_user_id(authorization)
    return {"id": user_id}

