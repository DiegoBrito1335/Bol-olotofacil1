from typing import Optional, Dict, Any
from app.core.supabase import supabase_admin as supabase
import logging

logger = logging.getLogger(__name__)


class CarteiraService:
    """
    Serviço de lógica de negócio para Carteira
    """
    
    @staticmethod
    async def get_carteira_by_usuario_id(usuario_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca a carteira de um usuário pelo ID
        
        Args:
            usuario_id: UUID do usuário
            
        Returns:
            Dict com dados da carteira ou None se não encontrar
        """
        try:
            response = supabase.table("carteira")\
                .select("*")\
                .eq("usuario_id", usuario_id)\
                .execute()
            
            if response.error:
                logger.error(f"Erro ao buscar carteira: {response.error}")
                return None
            
            if not response.data or len(response.data) == 0:
                logger.warning(f"Carteira não encontrada para usuário {usuario_id}")
                return None
            
            return response.data[0]
            
        except Exception as e:
            logger.error(f"Exceção ao buscar carteira: {str(e)}")
            return None
    
    @staticmethod
    async def verificar_saldo_suficiente(usuario_id: str, valor: float) -> bool:
        """
        Verifica se o usuário tem saldo disponível suficiente
        
        Args:
            usuario_id: UUID do usuário
            valor: Valor a ser verificado
            
        Returns:
            True se tem saldo suficiente, False caso contrário
        """
        carteira = await CarteiraService.get_carteira_by_usuario_id(usuario_id)
        
        if not carteira:
            return False
        
        saldo_disponivel = float(carteira.get("saldo_disponivel", 0))
        return saldo_disponivel >= valor