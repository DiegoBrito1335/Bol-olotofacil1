from typing import Optional, Dict, Any
import httpx
from datetime import datetime, timedelta
from app.config import settings
from app.core.supabase import supabase_admin as supabase
import logging
import uuid
import base64

logger = logging.getLogger(__name__)


class PagamentoService:
    """
    Serviço para integração com Mercado Pago (Pix)
    """
    
    BASE_URL = "https://api.mercadopago.com/v1"
    
    @staticmethod
    async def criar_pagamento_pix(usuario_id: str, valor: float, descricao: str) -> Optional[Dict[str, Any]]:
        """
        Cria um pagamento Pix
        
        MODO DESENVOLVIMENTO: Gera Pix simulado sem chamar Mercado Pago
        MODO PRODUÇÃO: Integra com Mercado Pago real
        
        Args:
            usuario_id: UUID do usuário
            valor: Valor em reais
            descricao: Descrição do pagamento
            
        Returns:
            Dict com dados do pagamento ou None em caso de erro
        """
        
        # Se não tem token do Mercado Pago ou está em dev/sandbox, usa simulado
        if not settings.MERCADOPAGO_ACCESS_TOKEN or settings.MERCADOPAGO_ENV == "sandbox" or settings.ENVIRONMENT == "development":
            if not settings.MERCADOPAGO_ACCESS_TOKEN:
                logger.warning("MERCADOPAGO_ACCESS_TOKEN não configurado - usando modo simulado")
            return await PagamentoService._criar_pix_simulado(usuario_id, valor, descricao)

        # MODO PRODUÇÃO com token real: Usar Mercado Pago
        return await PagamentoService._criar_pix_mercadopago(usuario_id, valor, descricao)
    
    @staticmethod
    async def _criar_pix_simulado(usuario_id: str, valor: float, descricao: str) -> Dict[str, Any]:
        """
        Cria um Pix SIMULADO para desenvolvimento
        """
        try:
            logger.info(f"🧪 MODO DEV: Criando Pix SIMULADO - Usuário: {usuario_id}, Valor: R$ {valor}")
            
            # Gera IDs simulados
            payment_id = str(uuid.uuid4())
            external_id = f"SIM-{int(datetime.now().timestamp())}"
            
            # QR Code simulado (string aleatória que parece um Pix real)
            qr_code = f"00020126580014br.gov.bcb.pix0136{external_id}520400005303986540{valor:.2f}5802BR5913Bolao Lotofacil6009SAO PAULO62070503***6304"
            
            # QR Code em base64 (simulado - apenas texto)
            qr_code_base64 = base64.b64encode(qr_code.encode()).decode()
            
            # Expira em 30 minutos
            expira_em = datetime.now() + timedelta(minutes=30)
            
            # Salva no banco
            pagamento_db = {
                "usuario_id": usuario_id,
                "valor": valor,
                "status": "pendente",
                "gateway": "mercadopago",
                "external_id": external_id,
                "qr_code": qr_code,
                "qr_code_base64": qr_code_base64,
                "expira_em": expira_em.isoformat(),
                "webhook_data": {"mode": "simulated", "note": "Pix simulado para desenvolvimento"}
            }
            
            result = supabase.table("pagamentos_pix").insert(pagamento_db).execute()

            if result.error:
                logger.error(f"Erro ao salvar pagamento no banco: {result.error}")
                return None
            
            logger.info(f"✅ Pix SIMULADO criado com sucesso: {external_id}")
            logger.warning("⚠️  ATENÇÃO: Este é um Pix SIMULADO para testes. Não use em produção!")
            
            return {
                "id": result.data[0]["id"],
                "external_id": external_id,
                "status": "pendente",
                "valor": valor,
                "qr_code": qr_code,
                "qr_code_base64": qr_code_base64,
                "expira_em": expira_em
            }
            
        except Exception as e:
            logger.error(f"Exceção ao criar Pix simulado: {str(e)}")
            return None
    
    @staticmethod
    async def _criar_pix_mercadopago(usuario_id: str, valor: float, descricao: str) -> Optional[Dict[str, Any]]:
        """
        Cria um Pix REAL no Mercado Pago (produção)
        """
        try:
            payload = {
                "transaction_amount": float(valor),
                "description": descricao,
                "payment_method_id": "pix",
                "payer": {
                    "email": "test_user@test.com",
                    "first_name": "Test",
                    "last_name": "User"
                },
                "external_reference": usuario_id
            }
            
            headers = {
                "Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}",
                "Content-Type": "application/json",
                "X-Idempotency-Key": f"{usuario_id}-{int(datetime.now().timestamp())}"
            }
            
            logger.info(f"Criando pagamento Pix REAL - Usuário: {usuario_id}, Valor: R$ {valor}")
            
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{PagamentoService.BASE_URL}/payments",
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
            
            if response.status_code != 201:
                logger.error(f"Erro ao criar pagamento: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            pix_data = data.get("point_of_interaction", {}).get("transaction_data", {})
            expira_em = datetime.now() + timedelta(minutes=30)
            
            pagamento_db = {
                "usuario_id": usuario_id,
                "valor": valor,
                "status": "pendente",
                "gateway": "mercadopago",
                "external_id": str(data.get("id")),
                "qr_code": pix_data.get("qr_code"),
                "qr_code_base64": pix_data.get("qr_code_base64"),
                "expira_em": expira_em.isoformat()
            }
            
            result = supabase.table("pagamentos_pix").insert(pagamento_db).execute()
            
            if result.error:
                logger.error(f"Erro ao salvar pagamento no banco: {result.error}")
                return None
            
            return {
                "id": result.data[0]["id"],
                "external_id": data.get("id"),
                "status": "pendente",
                "valor": valor,
                "qr_code": pix_data.get("qr_code"),
                "qr_code_base64": pix_data.get("qr_code_base64"),
                "expira_em": expira_em
            }
            
        except Exception as e:
            logger.error(f"Exceção ao criar pagamento Pix: {str(e)}")
            return None
    
    @staticmethod
    async def simular_confirmacao_pagamento(external_id: str) -> bool:
        """
        APENAS PARA TESTES: Simula confirmação de um pagamento
        """
        try:
            logger.info(f"🧪 Simulando confirmação do pagamento: {external_id}")
            
            # Busca o pagamento
            pag_result = supabase.table("pagamentos_pix")\
                .select("*")\
                .eq("external_id", external_id)\
                .execute()
            
            if not pag_result.data:
                logger.error("Pagamento não encontrado")
                return False
            
            pagamento = pag_result.data[0]
            usuario_id = pagamento["usuario_id"]
            valor = float(pagamento["valor"])
            
            # Atualiza status
            supabase.table("pagamentos_pix")\
                .update({
                    "status": "pago",
                    "webhook_recebido": True,
                    "pago_em": datetime.now().isoformat()
                })\
                .eq("external_id", external_id)\
                .execute()
            
            # Busca carteira
            cart_result = supabase.table("carteira")\
                .select("*")\
                .eq("usuario_id", usuario_id)\
                .execute()
            
            if not cart_result.data:
                logger.error("Carteira não encontrada")
                return False
            
            carteira = cart_result.data[0]
            saldo_anterior = float(carteira["saldo_disponivel"])
            saldo_posterior = saldo_anterior + valor
            
            # Atualiza saldo
            supabase.table("carteira")\
                .update({"saldo_disponivel": saldo_posterior})\
                .eq("usuario_id", usuario_id)\
                .execute()
            
            # Registra transação
            supabase.table("transacoes").insert({
                "usuario_id": usuario_id,
                "tipo": "credito",
                "valor": valor,
                "origem": "pix",
                "referencia_id": external_id,
                "descricao": f"Depósito via Pix (SIMULADO) - ID {external_id}",
                "saldo_anterior": saldo_anterior,
                "saldo_posterior": saldo_posterior,
                "status": "confirmado"
            }).execute()
            
            logger.info(f"✅ Pagamento SIMULADO confirmado! Saldo: R$ {saldo_anterior} → R$ {saldo_posterior}")
            
            return True
            
        except Exception as e:
            logger.error(f"Erro ao simular confirmação: {str(e)}")
            return False