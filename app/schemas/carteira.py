from pydantic import BaseModel, UUID4
from decimal import Decimal
from datetime import datetime
from typing import Optional


class CarteiraResponse(BaseModel):
    """
    Resposta da carteira do usuário
    """
    id: UUID4
    usuario_id: UUID4
    saldo_disponivel: Decimal
    saldo_bloqueado: Decimal
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class CarteiraResumo(BaseModel):
    """
    Resumo simplificado da carteira
    """
    saldo_disponivel: Decimal
    saldo_bloqueado: Decimal
    saldo_total: Decimal
    
    @classmethod
    def from_carteira(cls, carteira: dict):
        """Cria resumo a partir dos dados da carteira"""
        saldo_disp = Decimal(str(carteira.get("saldo_disponivel", 0)))
        saldo_bloq = Decimal(str(carteira.get("saldo_bloqueado", 0)))
        
        return cls(
            saldo_disponivel=saldo_disp,
            saldo_bloqueado=saldo_bloq,
            saldo_total=saldo_disp + saldo_bloq
        )