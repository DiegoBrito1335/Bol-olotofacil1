"""
Schemas para rotas administrativas
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from decimal import Decimal


# ===================================
# SCHEMAS DE CRIAÇÃO/ATUALIZAÇÃO
# ===================================

class BolaoCreateAdmin(BaseModel):
    """Schema para criar bolão (admin)"""
    nome: str = Field(..., min_length=3, max_length=100)
    descricao: Optional[str] = None
    concurso_numero: int = Field(..., gt=0)
    total_cotas: int = Field(..., gt=0, le=1000)
    valor_cota: Decimal = Field(..., gt=0)
    status: str = Field(default="aberto", pattern="^(aberto|fechado|apurado|cancelado)$")
    data_fechamento: Optional[datetime] = None


class BolaoUpdateAdmin(BaseModel):
    """Schema para atualizar bolão (admin)"""
    nome: Optional[str] = Field(None, min_length=3, max_length=100)
    descricao: Optional[str] = None
    concurso_numero: Optional[int] = Field(None, gt=0)
    total_cotas: Optional[int] = Field(None, gt=0, le=1000)
    valor_cota: Optional[Decimal] = Field(None, gt=0)
    status: Optional[str] = Field(None, pattern="^(aberto|fechado|apurado|cancelado)$")
    data_fechamento: Optional[datetime] = None