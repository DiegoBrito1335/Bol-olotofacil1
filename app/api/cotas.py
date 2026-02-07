"""
Rotas de compra de cotas
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_current_user
import logging
import traceback

logger = logging.getLogger(__name__)

router = APIRouter()


class ComprarCotaRequest(BaseModel):
    """Request para comprar cota"""
    bolao_id: str
    quantidade: int = 1


class ComprarCotaResponse(BaseModel):
    """Response da compra de cota"""
    mensagem: str
    cota_id: str
    bolao_id: str
    quantidade: int
    valor_total: float
    saldo_restante: float


@router.post("/comprar", response_model=ComprarCotaResponse)
async def comprar_cota(
    request: ComprarCotaRequest,
    current_user = Depends(get_current_user)
):
    """
    Compra uma ou mais cotas de um bolao.
    Usa a funcao do banco que faz tudo atomicamente.
    """

    # Chamar funcao do banco que faz compra atomica
    result = supabase.rpc(
        "comprar_cota",
        {
            "p_usuario_id": current_user["id"],
            "p_bolao_id": request.bolao_id,
            "p_quantidade": request.quantidade
        }
    ).execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao comprar cota: {result.error}"
        )

    # Resultado da funcao
    resultado = result.data

    if not resultado.get("sucesso"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=resultado.get("mensagem", "Erro ao comprar cota")
        )

    # Auto-fechar bolão se todas as cotas foram vendidas
    try:
        bolao_check = supabase.table("boloes")\
            .select("cotas_disponiveis, status")\
            .eq("id", request.bolao_id)\
            .execute()
        if bolao_check.data:
            bolao = bolao_check.data[0]
            if bolao["cotas_disponiveis"] <= 0 and bolao["status"] == "aberto":
                supabase.table("boloes")\
                    .update({"status": "fechado"})\
                    .eq("id", request.bolao_id)\
                    .execute()
                logger.info(f"Bolão {request.bolao_id} fechado automaticamente (cotas esgotadas)")
    except Exception as e:
        logger.warning(f"Erro ao verificar auto-fechamento: {e}")

    return ComprarCotaResponse(
        mensagem="Cota comprada com sucesso!",
        cota_id=resultado.get("cota_id", ""),
        bolao_id=request.bolao_id,
        quantidade=request.quantidade,
        valor_total=resultado.get("valor_pago", 0.0),
        saldo_restante=resultado.get("saldo_restante", 0.0)
    )


@router.get("/minhas")
async def minhas_cotas(
    current_user = Depends(get_current_user)
):
    """
    Lista todas as cotas do usuario logado.
    Usa funcao SECURITY DEFINER para bypassar RLS.
    """

    try:
        logger.info(f"Buscando cotas para usuario: {current_user['id']}")

        result = supabase.rpc(
            "buscar_minhas_cotas",
            {"p_usuario_id": current_user["id"]}
        ).execute()

        logger.info(f"Resultado RPC: error={result.error}, data_type={type(result.data)}")

        if result.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao buscar cotas: {result.error}"
            )

        cotas_data = result.data or []

        # Enriquecer com quantidade real (valor_pago / valor_cota)
        if cotas_data:
            bolao_ids = list(set(c["bolao_id"] for c in cotas_data))
            boloes_result = supabase.table("boloes").select("id, valor_cota").in_("id", bolao_ids).execute()
            valor_cota_map = {b["id"]: float(b["valor_cota"]) for b in (boloes_result.data or [])}

            for cota in cotas_data:
                vc = valor_cota_map.get(cota["bolao_id"], 0)
                cota["quantidade"] = max(1, round(float(cota["valor_pago"]) / vc)) if vc > 0 else 1

            # Enriquecer com prêmios ganhos por bolão
            premios_result = supabase.table("transacoes")\
                .select("referencia_id, valor")\
                .eq("usuario_id", current_user["id"])\
                .eq("origem", "premio_bolao")\
                .eq("status", "confirmado")\
                .execute()

            premio_por_bolao = {}
            for t in (premios_result.data or []):
                bid = t.get("referencia_id")
                if bid:
                    premio_por_bolao[bid] = premio_por_bolao.get(bid, 0) + float(t["valor"])

            for cota in cotas_data:
                cota["premio_ganho"] = round(premio_por_bolao.get(cota["bolao_id"], 0), 2)

        return cotas_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro em /minhas: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno: {str(e)}"
        )
