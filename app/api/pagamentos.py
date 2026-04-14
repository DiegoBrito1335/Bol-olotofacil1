from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks
from app.schemas.pagamento import CriarPagamentoPixRequest, PagamentoPixResponse
from app.services.pagamento_service import PagamentoService
from app.api.deps import get_current_user_id, get_current_user
from app.core.limiter import limiter
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/criar-pix", response_model=PagamentoPixResponse)
async def criar_pagamento_pix(
    request: CriarPagamentoPixRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Cria uma cobrança Pix para adicionar saldo
    
    Fluxo:
    1. Gera cobrança no Mercado Pago
    2. Retorna QR Code para pagamento
    3. Usuário paga via Pix
    4. Webhook confirma pagamento
    5. Saldo é creditado automaticamente
    
    Args:
        request: Dados do pagamento (valor e descrição)
        current_user_id: ID do usuário autenticado
        
    Returns:
        Dados do Pix gerado (QR Code, etc)
    """
    logger.info(f"Gerando Pix - Usuário: {current_user['id']}, Valor: R$ {request.valor}")
    
    # Valida valor mínimo
    if request.valor < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valor mínimo: R$ 1,00"
        )
    
    # Valida valor máximo (opcional)
    if request.valor > 10000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valor máximo: R$ 10.000,00"
        )
    
    # Cria pagamento
    resultado = await PagamentoService.criar_pagamento_pix(
        usuario_id=current_user["id"],
        email=current_user.get("email"),
        valor=float(request.valor),
        descricao=request.descricao
    )
    
    if not resultado:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao gerar pagamento Pix. Tente novamente."
        )
    
    return PagamentoPixResponse(**resultado)


@router.post("/webhook/mercadopago")
@limiter.limit("60/minute")
async def webhook_mercadopago(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Webhook do Mercado Pago para notificações de pagamento.

    Segurança:
    - C3: Verifica assinatura HMAC (x-signature) quando MERCADOPAGO_WEBHOOK_SECRET estiver configurado
    - Sempre retorna 200 para evitar reenvios do MP
    """
    try:
        body = await request.json()
        logger.info(f"Webhook recebido: {body}")

        if body.get("type") != "payment":
            return {"status": "ignored"}

        payment_id = body.get("data", {}).get("id")

        if not payment_id:
            logger.warning("Webhook sem payment_id, ignorando")
            return {"status": "ignored"}

        # C3 — Verificar assinatura HMAC do Mercado Pago
        x_signature = request.headers.get("x-signature", "")
        x_request_id = request.headers.get("x-request-id", "")

        if not PagamentoService.verificar_assinatura_mp(x_signature, x_request_id, str(payment_id)):
            logger.error(f"Assinatura inválida no webhook para payment_id={payment_id}")
            # Retorna 200 para não expor a rejeição, mas não processa
            return {"status": "ignored"}

        background_tasks.add_task(
            PagamentoService.processar_webhook_pagamento,
            str(payment_id)
        )

        logger.info(f"Webhook agendado para processamento: {payment_id}")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Erro ao processar webhook: {str(e)}")
        return {"status": "error", "message": str(e)}


@router.get("/meus-pagamentos")
async def listar_meus_pagamentos(
    current_user_id: str = Depends(get_current_user_id)
):
    """
    Lista os pagamentos do usuário
    
    Returns:
        Lista de pagamentos
    """
    from app.core.supabase import supabase_admin as supabase
    
    logger.info(f"Listando pagamentos do usuário: {current_user_id}")
    
    response = await supabase.table("pagamentos_pix")\
        .select("*")\
        .eq("usuario_id", current_user_id)\
        .order("created_at", desc=True)\
        .limit(20)\
        .execute()
    
    if response.error:
        logger.error(f"Erro ao listar pagamentos: {response.error}")
        return []
    
    return response.data or []