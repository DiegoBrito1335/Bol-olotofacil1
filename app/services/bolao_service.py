from typing import Optional, List, Dict, Any
from app.core.supabase import supabase_admin as supabase
import logging

logger = logging.getLogger(__name__)


class BolaoService:
    """
    Serviço de lógica de negócio para Bolões
    """
    
    @staticmethod
    async def listar_boloes_abertos() -> List[Dict[str, Any]]:
        """
        Lista todos os bolões com status 'aberto'
        
        Returns:
            Lista de bolões abertos
        """
        try:
            response = supabase.table("boloes")\
                .select("*")\
                .eq("status", "aberto")\
                .order("created_at", desc=True)\
                .execute()
            
            if response.error:
                logger.error(f"Erro ao listar bolões: {response.error}")
                return []
            
            return response.data or []
            
        except Exception as e:
            logger.error(f"Exceção ao listar bolões: {str(e)}")
            return []
    
    @staticmethod
    async def get_bolao_by_id(bolao_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca um bolão específico pelo ID
        
        Args:
            bolao_id: UUID do bolão
            
        Returns:
            Dict com dados do bolão ou None
        """
        try:
            response = supabase.table("boloes")\
                .select("*")\
                .eq("id", bolao_id)\
                .execute()
            
            if response.error:
                logger.error(f"Erro ao buscar bolão: {response.error}")
                return None
            
            if not response.data or len(response.data) == 0:
                logger.warning(f"Bolão {bolao_id} não encontrado")
                return None
            
            return response.data[0]
            
        except Exception as e:
            logger.error(f"Exceção ao buscar bolão: {str(e)}")
            return None
    
    @staticmethod
    async def get_jogos_by_bolao_id(bolao_id: str) -> List[Dict[str, Any]]:
        """
        Busca todos os jogos de um bolão
        
        Args:
            bolao_id: UUID do bolão
            
        Returns:
            Lista de jogos do bolão
        """
        try:
            response = supabase.table("jogos_bolao")\
                .select("*")\
                .eq("bolao_id", bolao_id)\
                .execute()
            
            if response.error:
                logger.error(f"Erro ao buscar jogos: {response.error}")
                return []
            
            return response.data or []
            
        except Exception as e:
            logger.error(f"Exceção ao buscar jogos: {str(e)}")
            return []
    
    @staticmethod
    async def verificar_bolao_aberto(bolao_id: str) -> bool:
        """
        Verifica se um bolão está aberto para compras
        
        Args:
            bolao_id: UUID do bolão
            
        Returns:
            True se está aberto, False caso contrário
        """
        bolao = await BolaoService.get_bolao_by_id(bolao_id)
        
        if not bolao:
            return False
        
        return bolao.get("status") == "aberto" and bolao.get("cotas_disponiveis", 0) > 0

    @staticmethod
    def is_teimosinha(bolao: Dict[str, Any]) -> bool:
        """Verifica se o bolão é teimosinha (múltiplos concursos)"""
        return bolao.get("concurso_fim") is not None and bolao["concurso_fim"] > bolao["concurso_numero"]

    @staticmethod
    def total_concursos(bolao: Dict[str, Any]) -> int:
        """Retorna o total de concursos do bolão"""
        if bolao.get("concurso_fim") and bolao["concurso_fim"] > bolao["concurso_numero"]:
            return bolao["concurso_fim"] - bolao["concurso_numero"] + 1
        return 1

    @staticmethod
    def concursos_list(bolao: Dict[str, Any]) -> List[int]:
        """Retorna lista de todos os concursos do bolão"""
        if bolao.get("concurso_fim") and bolao["concurso_fim"] > bolao["concurso_numero"]:
            return list(range(bolao["concurso_numero"], bolao["concurso_fim"] + 1))
        return [bolao["concurso_numero"]]