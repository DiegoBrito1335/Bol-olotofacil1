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

        # Enriquecer com quantidade real e prêmios
        if cotas_data:
            bolao_ids = list(set(c["bolao_id"] for c in cotas_data))
            boloes_result = supabase.table("boloes")\
                .select("id, valor_cota, total_cotas, cotas_disponiveis")\
                .in_("id", bolao_ids).execute()
            boloes_map = {b["id"]: b for b in (boloes_result.data or [])}

            for cota in cotas_data:
                b = boloes_map.get(cota["bolao_id"], {})
                vc = float(b.get("valor_cota", 0))
                cota["quantidade"] = max(1, round(float(cota["valor_pago"]) / vc)) if vc > 0 else 1

            # Enriquecer com prêmios ganhos por bolão
            # Usar premiacoes_bolao (mais confiável) + proporção do usuário
            premiacoes_result = supabase.table("premiacoes_bolao")\
                .select("bolao_id, premio_total")\
                .in_("bolao_id", bolao_ids)\
                .execute()

            premio_total_por_bolao = {}
            for p in (premiacoes_result.data or []):
                bid = p["bolao_id"]
                premio_total_por_bolao[bid] = premio_total_por_bolao.get(bid, 0) + float(p["premio_total"])

            for cota in cotas_data:
                bid = cota["bolao_id"]
                total_premio = premio_total_por_bolao.get(bid, 0)
                if total_premio > 0:
                    b = boloes_map.get(bid, {})
                    total_cotas = b.get("total_cotas", 0)
                    cotas_disp = b.get("cotas_disponiveis", 0)
                    vendidas = total_cotas - cotas_disp
                    user_qtd = cota.get("quantidade", 1)
                    if vendidas > 0:
                        cota["premio_ganho"] = round(total_premio * user_qtd / vendidas, 2)
                    else:
                        cota["premio_ganho"] = 0
                else:
                    cota["premio_ganho"] = 0

        return cotas_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro em /minhas: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno: {str(e)}"
        )
