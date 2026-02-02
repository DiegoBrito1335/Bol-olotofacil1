"""
Schemas para rotas administrativas
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
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


# ===================================
# SCHEMAS DE JOGOS
# ===================================

class JogoCreateAdmin(BaseModel):
    """Schema para adicionar um jogo a um bolão"""
    dezenas: List[int] = Field(..., min_length=15, max_length=15)

    @field_validator('dezenas')
    @classmethod
    def validate_dezenas(cls, v):
        if len(v) != 15:
            raise ValueError('Lotofácil requer exatamente 15 números')
        if any(d < 1 or d > 25 for d in v):
            raise ValueError('Números devem estar entre 1 e 25')
        if len(set(v)) != 15:
            raise ValueError('Números devem ser únicos')
        return sorted(v)


class JogosCreateBatchAdmin(BaseModel):
    """Schema para adicionar múltiplos jogos de uma vez"""
    jogos: List[JogoCreateAdmin] = Field(..., min_length=1)


# ===================================
# SCHEMAS DE APURAÇÃO
# ===================================

class ResultadoInput(BaseModel):
    """Schema para input manual de resultado"""
    dezenas: List[int] = Field(..., min_length=15, max_length=15)

    @field_validator('dezenas')
    @classmethod
    def validate_dezenas(cls, v):
        if len(v) != 15:
            raise ValueError('Resultado deve ter exatamente 15 números')
        if any(d < 1 or d > 25 for d in v):
            raise ValueError('Números devem estar entre 1 e 25')
        if len(set(v)) != 15:
            raise ValueError('Números devem ser únicos')
        return sorted(v)