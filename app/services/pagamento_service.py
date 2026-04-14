from typing import Optional, Dict, Any
import httpx
import hmac
import hashlib
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
    def verificar_assinatura_mp(x_signature: str, x_request_id: str, payment_id: str) -> bool:
        """
        Verifica a assinatura HMAC do webhook do Mercado Pago.
        Formato do header x-signature: "ts=TIMESTAMP,v1=HMAC_HEX"
        Manifesto: "id:{payment_id};request-id:{x_request_id};ts:{ts};"

        Retorna True se MERCADOPAGO_WEBHOOK_SECRET não estiver configurado (modo dev).
        Em produção, configure MERCADOPAGO_WEBHOOK_SECRET no dashboard do MP.
        """
        secret = settings.MERCADOPAGO_WEBHOOK_SECRET
        if not secret:
            logger.warning("MERCADOPAGO_WEBHOOK_SECRET não configurado — verificação de assinatura desabilitada")
            return True

        try:
            parts = dict(p.split("=", 1) for p in x_signature.split(",") if "=" in p)
            ts = parts.get("ts", "")
            v1 = parts.get("v1", "")
            if not ts or not v1:
                logger.warning("Assinatura MP malformada: campos ts ou v1 ausentes")
                return False

            manifest = f"id:{payment_id};request-id:{x_request_id};ts:{ts};"
            expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
            valid = hmac.compare_digest(expected, v1)
            if not valid:
                logger.warning(f"Assinatura MP inválida para payment_id={payment_id}")
            return valid
        except Exception as e:
            logger.error(f"Erro ao verificar assinatura MP: {e}")
            return False

    @staticmethod
    async def criar_pagamento_pix(usuario_id: str, valor: float, descricao: str, email: str = None) -> Optional[Dict[str, Any]]:
        """
        Cria um pagamento Pix

        MODO DESENVOLVIMENTO: Gera Pix simulado sem chamar Mercado Pago
        MODO PRODUÇÃO: Integra com Mercado Pago real
        """
        
        if settings.ENVIRONMENT == "production":
            if not settings.MERCADOPAGO_ACCESS_TOKEN:
                logger.error("ERRO CRÍTICO: Tentativa de gerar pagamento em produção sem MERCADOPAGO_ACCESS_TOKEN.")
                return None
            return await PagamentoService._criar_pix_mercadopago(usuario_id, valor, descricao, email)

        if not settings.MERCADOPAGO_ACCESS_TOKEN or settings.MERCADOPAGO_ENV == "sandbox" or settings.ENVIRONMENT == "development":
            if not settings.MERCADOPAGO_ACCESS_TOKEN:
                logger.warning("MERCADOPAGO_ACCESS_TOKEN não configurado - usando modo simulado")
            return await PagamentoService._criar_pix_simulado(usuario_id, valor, descricao)

        return await PagamentoService._criar_pix_mercadopago(usuario_id, valor, descricao, email)

    @staticmethod
    async def _criar_pix_simulado(usuario_id: str, valor: float, descricao: str) -> Dict[str, Any]:
        """
        Cria um Pix SIMULADO para desenvolvimento
        """
        try:
            logger.info(f"🧪 MODO DEV: Criando Pix SIMULADO - Usuário: {usuario_id}, Valor: R$ {valor}")

            payment_id = str(uuid.uuid4())
            external_id = f"SIM-{int(datetime.now().timestamp())}"

            qr_code = f"00020126580014br.gov.bcb.pix0136{external_id}520400005303986540{valor:.2f}5802BR5913Bolao Lotofacil6009SAO PAULO62070503***6304"
            qr_code_base64 = base64.b64encode(qr_code.encode()).decode()
            expira_em = datetime.now() + timedelta(minutes=30)

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

            result = await supabase.table("pagamentos_pix").insert(pagamento_db).execute()

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
    async def _criar_pix_mercadopago(usuario_id: str, valor: float, descricao: str, email: str = None) -> Optional[Dict[str, Any]]:
        """
        Cria um Pix REAL no Mercado Pago (produção)
        """
        try:
            payload = {
                "transaction_amount": float(valor),
                "description": descricao,
                "payment_method_id": "pix",
                "payer": {
                    "email": email or "contato@boloeslotofacil.com",
                    "first_name": "Usuario",
                    "last_name": "Lotofacil"
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

            result = await supabase.table("pagamentos_pix").insert(pagamento_db).execute()

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
    async def processar_webhook_pagamento(payment_id: str) -> bool:
        """
        Processa notificação de pagamento aprovado do Mercado Pago.

        Correções de segurança:
        - C6: Verifica se o pagamento já foi processado (idempotência via lock otimista)
        - C7: Consulta valor real na API do MP e compara com o registrado
        """
        try:
            logger.info(f"Processando webhook: payment_id={payment_id}")

            # C7 — Verificar status e valor real na API do Mercado Pago
            valor_pago_mp = None
            status_mp = None

            if settings.MERCADOPAGO_ACCESS_TOKEN:
                try:
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(
                            f"{PagamentoService.BASE_URL}/payments/{payment_id}",
                            headers={"Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}"},
                            timeout=15.0
                        )
                    if resp.status_code == 200:
                        mp_data = resp.json()
                        status_mp = mp_data.get("status")
                        valor_pago_mp = float(mp_data.get("transaction_amount", 0))
                        logger.info(f"MP API: status={status_mp}, valor=R${valor_pago_mp}")
                    else:
                        logger.warning(f"MP API retornou {resp.status_code} para payment {payment_id}")
                except Exception as e:
                    logger.warning(f"Não foi possível consultar MP API: {e}")

            # Se conseguiu verificar e o pagamento não está aprovado, ignora
            if status_mp and status_mp != "approved":
                logger.info(f"Pagamento {payment_id} com status '{status_mp}' — não aprovado, ignorando")
                return False

            # Busca o registro interno pelo external_id
            pag_result = await supabase.table("pagamentos_pix")\
                .select("*")\
                .eq("external_id", str(payment_id))\
                .execute()

            if not pag_result.data:
                logger.warning(f"Pagamento {payment_id} não encontrado no banco")
                return False

            pagamento = pag_result.data[0]

            # C6 — Idempotência: não processar duas vezes
            if pagamento["status"] != "pendente":
                logger.info(f"Pagamento {payment_id} já processado (status={pagamento['status']}), ignorando")
                return True

            usuario_id = pagamento["usuario_id"]
            valor_registrado = float(pagamento["valor"])

            # C7 — Verificar valor pago vs registrado (tolerância de R$ 0,01)
            if valor_pago_mp is not None and abs(valor_pago_mp - valor_registrado) > 0.01:
                logger.error(
                    f"Divergência de valor! Esperado R${valor_registrado}, pago R${valor_pago_mp}. "
                    f"Pagamento {payment_id} suspenso para revisão manual."
                )
                await supabase.table("pagamentos_pix")\
                    .update({"status": "divergencia_valor", "webhook_recebido": True})\
                    .eq("external_id", str(payment_id))\
                    .execute()
                return False

            valor = valor_registrado

            # Lock otimista: só atualiza se status ainda for "pendente"
            # Se outro worker já processou, update retorna lista vazia e abortamos
            update_pag = await supabase.table("pagamentos_pix")\
                .update({
                    "status": "pago",
                    "webhook_recebido": True,
                    "pago_em": datetime.now().isoformat()
                })\
                .eq("external_id", str(payment_id))\
                .eq("status", "pendente")\
                .execute()

            if not update_pag.data:
                logger.warning(f"Pagamento {payment_id} não atualizável — já processado por outro worker")
                return True

            # C5 — Creditar via RPC atômico (UPDATE carteira + INSERT transacao em uma transação SQL)
            rpc_result = await supabase.rpc("creditar_carteira", {
                "p_usuario_id": usuario_id,
                "p_valor": valor,
                "p_origem": "pix",
                "p_referencia_id": str(payment_id),
                "p_descricao": f"Depósito via Pix - ID {payment_id}",
            }).execute()

            if rpc_result.error:
                logger.error(f"Erro no RPC creditar_carteira para {payment_id}: {rpc_result.error}")
                return False

            logger.info(f"✅ Pagamento {payment_id} processado. R${valor} creditado para {usuario_id}")
            return True

        except Exception as e:
            logger.error(f"Erro ao processar webhook {payment_id}: {str(e)}")
            return False

    @staticmethod
    async def simular_confirmacao_pagamento(external_id: str) -> bool:
        """
        APENAS PARA TESTES: Simula confirmação de um pagamento
        """
        if settings.ENVIRONMENT == "production":
            logger.error("ERRO CRITICO: Tentativa de simular confirmacao em ambiente de producao.")
            return False
            
        try:
            logger.info(f"🧪 Simulando confirmação do pagamento: {external_id}")

            pag_result = await supabase.table("pagamentos_pix")\
                .select("*")\
                .eq("external_id", external_id)\
                .execute()

            if not pag_result.data:
                logger.error("Pagamento não encontrado")
                return False

            pagamento = pag_result.data[0]

            # Idempotência
            if pagamento["status"] != "pendente":
                logger.info(f"Pagamento {external_id} já processado (status={pagamento['status']}), ignorando")
                return True

            usuario_id = pagamento["usuario_id"]
            valor = float(pagamento["valor"])

            # Lock otimista
            update_pag = await supabase.table("pagamentos_pix")\
                .update({
                    "status": "pago",
                    "webhook_recebido": True,
                    "pago_em": datetime.now().isoformat()
                })\
                .eq("external_id", external_id)\
                .eq("status", "pendente")\
                .execute()

            if not update_pag.data:
                logger.warning(f"Pagamento {external_id} já processado por outro processo")
                return True

            # C5 — Creditar via RPC atômico
            rpc_result = await supabase.rpc("creditar_carteira", {
                "p_usuario_id": usuario_id,
                "p_valor": valor,
                "p_origem": "pix",
                "p_referencia_id": external_id,
                "p_descricao": f"Depósito via Pix (SIMULADO) - ID {external_id}",
            }).execute()

            if rpc_result.error:
                logger.error(f"Erro no RPC creditar_carteira para {external_id}: {rpc_result.error}")
                return False

            logger.info(f"✅ Pagamento SIMULADO confirmado! R${valor} creditado para {usuario_id}")
            return True

        except Exception as e:
            logger.error(f"Erro ao simular confirmação: {str(e)}")
            return False
