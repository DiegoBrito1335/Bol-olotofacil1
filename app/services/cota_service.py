from typing import Optional, Dict, Any
from app.core.supabase import supabase_admin as supabase
import logging
import json

logger = logging.getLogger(__name__)


class CotaService:
    """
    Serviço de lógica de negócio para Cotas
    """
    
    @staticmethod
    async def comprar_cota(usuario_id: str, bolao_id: str) -> Dict[str, Any]:
        """
        Compra uma cota de um bolão usando a função SQL.
        
        Esta função chama a função PostgreSQL comprar_cota() que:
        - Verifica saldo
        - Debita da carteira
        - Cria a cota
        - Atualiza cotas disponíveis
        - Registra transação
        
        Tudo isso de forma ATÔMICA (ou tudo funciona ou nada acontece)
        
        Args:
            usuario_id: UUID do usuário
            bolao_id: UUID do bolão
            
        Returns:
            Dict com resultado da operação
        """
        try:
            logger.info(f"Iniciando compra de cota - Usuário: {usuario_id}, Bolão: {bolao_id}")
            
            # Chama a função SQL comprar_cota via RPC
            response = supabase.rpc(
                'comprar_cota',
                {
                    'p_usuario_id': usuario_id,
                    'p_bolao_id': bolao_id
                }
            ).execute()
            
            if response.error:
                logger.error(f"Erro ao comprar cota: {response.error}")
                return {
                    "success": False,
                    "error": str(response.error)
                }
            
            # A função SQL retorna um JSON
            result = response.data
            
            logger.info(f"Resultado da compra: {result}")
            
            # Se a resposta for uma string JSON, parsear
            if isinstance(result, str):
                result = json.loads(result)
            elif isinstance(result, list) and len(result) > 0:
                result = result[0]
            
            return result
            
        except Exception as e:
            logger.error(f"Exceção ao comprar cota: {str(e)}")
            return {
                "success": False,
                "error": f"Erro interno: {str(e)}"
            }
    
    @staticmethod
    async def get_minhas_cotas(usuario_id: str):
        """
        Busca todas as cotas de um usuário
        
        Args:
            usuario_id: UUID do usuário
            
        Returns:
            Lista de cotas do usuário
        """
        try:
            response = supabase.table("cotas")\
                .select("*, boloes(*)")\
                .eq("usuario_id", usuario_id)\
                .order("created_at", desc=True)\
                .execute()
            
            if response.error:
                logger.error(f"Erro ao buscar cotas: {response.error}")
                return []
            
            return response.data or []
            
        except Exception as e:
            logger.error(f"Exceção ao buscar cotas: {str(e)}")
            return []