from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional


class ComprarCotaRequest(BaseModel):
    """
    Requisição para comprar uma cota
    """
    # Não precisa de campos - o bolao_id vem da URL
    # e o usuario_id vem do token de autenticação
    pass


class ComprarCotaResponse(BaseModel):
    """
    Resposta da compra de cota
    """
    success: bool
    message: str
    cota_id: Optional[str] = None
    valor_pago: Optional[Decimal] = None
    saldo_restante: Optional[Decimal] = None
    
    class Config:
        from_attributes = True


class CotaDetalhes(BaseModel):
    """
    Detalhes de uma cota
    """
    id: str
    bolao_id: str
    usuario_id: str
    valor_pago: Decimal
    created_at: datetime
    
    class Config:
        from_attributes = True