"""
Schemas para rotas administrativas
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
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
    concurso_fim: Optional[int] = Field(None, gt=0)
    total_cotas: int = Field(..., gt=0, le=1000)
    valor_cota: Decimal = Field(..., gt=0)
    status: str = Field(default="aberto", pattern="^(aberto|fechado|apurado|cancelado)$")
    data_fechamento: Optional[datetime] = None
    tipo: Literal['lotofacil', 'megasena'] = 'lotofacil'

    @field_validator('concurso_fim')
    @classmethod
    def validate_concurso_fim(cls, v, info):
        if v is not None:
            concurso_numero = info.data.get('concurso_numero')
            if concurso_numero and v <= concurso_numero:
                raise ValueError('concurso_fim deve ser maior que concurso_numero')
            if concurso_numero and (v - concurso_numero + 1) > 999:
                raise ValueError('Teimosinha suporta no máximo 999 concursos')
        return v


class BolaoUpdateAdmin(BaseModel):
    """Schema para atualizar bolão (admin)"""
    nome: Optional[str] = Field(None, min_length=3, max_length=100)
    descricao: Optional[str] = None
    concurso_numero: Optional[int] = Field(None, gt=0)
    concurso_fim: Optional[int] = Field(None, gt=0)
    total_cotas: Optional[int] = Field(None, gt=0, le=1000)
    valor_cota: Optional[Decimal] = Field(None, gt=0)
    status: Optional[str] = Field(None, pattern="^(aberto|fechado|apurado|cancelado)$")
    data_fechamento: Optional[datetime] = None


# ===================================
# SCHEMAS DE JOGOS
# ===================================

class JogoCreateAdmin(BaseModel):
    """Schema para adicionar um jogo a um bolão"""
    dezenas: List[int] = Field(..., min_length=6, max_length=20)

    @field_validator('dezenas')
    @classmethod
    def validate_dezenas(cls, v):
        # Validação de range/count feita no route baseado no tipo do bolão
        if len(set(v)) != len(v):
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
    dezenas: List[int] = Field(..., min_length=6, max_length=15)
    concurso_numero: Optional[int] = None

    @field_validator('dezenas')
    @classmethod
    def validate_dezenas(cls, v):
        # Validação de count (6 ou 15) e range (1-60 ou 1-25) feita no route baseado no tipo
        if len(set(v)) != len(v):
            raise ValueError('Números devem ser únicos')
        return sorted(v)