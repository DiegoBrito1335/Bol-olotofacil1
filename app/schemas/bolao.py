from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import List, Optional


class JogoResponse(BaseModel):
    """
    Resposta de um jogo (dezenas)
    """
    id: str
    bolao_id: str
    dezenas: List[int]
    acertos: Optional[int] = None
    acertos_por_concurso: Optional[List[dict]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BolaoListItem(BaseModel):
    """
    Item da lista de bolões (resumido)
    """
    id: str  # MUDOU: UUID4 -> str
    nome: str
    descricao: Optional[str] = None
    total_cotas: int
    cotas_disponiveis: int
    valor_cota: Decimal
    concurso_numero: int
    concurso_fim: Optional[int] = None
    concursos_apurados: Optional[int] = 0
    status: str
    created_at: datetime
    
    @property
    def cotas_vendidas(self) -> int:
        """Calcula quantas cotas foram vendidas"""
        return self.total_cotas - self.cotas_disponiveis
    
    @property
    def percentual_vendido(self) -> float:
        """Calcula percentual de cotas vendidas"""
        if self.total_cotas == 0:
            return 0.0
        return (self.cotas_vendidas / self.total_cotas) * 100
    
    class Config:
        from_attributes = True


class BolaoDetalhes(BolaoListItem):
    """
    Detalhes completos de um bolão
    """
    data_fechamento: Optional[datetime] = None
    updated_at: datetime
    jogos: List[JogoResponse] = []
    resultado_dezenas: Optional[List[int]] = None

    class Config:
        from_attributes = True


class BolaoComJogos(BaseModel):
    """
    Bolão com seus jogos incluídos
    """
    bolao: BolaoDetalhes
    jogos: List[JogoResponse]


# Aliases para compatibilidade com outras partes do código
BolaoResponse = BolaoDetalhes
JogosResponse = JogosResponse = JogoResponse