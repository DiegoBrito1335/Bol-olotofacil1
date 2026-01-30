from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.carteira import CarteiraResumo, CarteiraResponse
from app.services.carteira_service import CarteiraService
from app.api.deps import get_current_user_id
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=CarteiraResumo)
async def get_minha_carteira(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Retorna o saldo da carteira do usuário autenticado
    
    Returns:
        CarteiraResumo: Resumo com saldo disponível, bloqueado e total
    """
    logger.info(f"Buscando carteira do usuário: {current_user_id}")
    
    carteira = await CarteiraService.get_carteira_by_usuario_id(current_user_id)
    
    if not carteira:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Carteira não encontrada. O usuário pode não existir."
        )
    
    return CarteiraResumo.from_carteira(carteira)


@router.get("/detalhes", response_model=CarteiraResponse)
async def get_carteira_detalhes(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Retorna os detalhes completos da carteira do usuário
    
    Returns:
        CarteiraResponse: Dados completos da carteira
    """
    logger.info(f"Buscando detalhes da carteira do usuário: {current_user_id}")
    
    carteira = await CarteiraService.get_carteira_by_usuario_id(current_user_id)
    
    if not carteira:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Carteira não encontrada"
        )
    
    return carteira