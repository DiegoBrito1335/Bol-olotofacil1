"""
Rotas de compra de cotas
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Dict
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


@router.get("/meus-resultados")
async def meus_resultados(
    current_user = Depends(get_current_user)
):
    """
    Retorna resultados dos bolões em que o usuário participou.
    Inclui dezenas sorteadas, jogos com acertos e prêmios.
    """

    try:
        # 1. Buscar cotas do usuário
        cotas_result = supabase.rpc(
            "buscar_minhas_cotas",
            {"p_usuario_id": current_user["id"]}
        ).execute()

        if cotas_result.error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao buscar cotas: {cotas_result.error}"
            )

        cotas_data = cotas_result.data or []
        if not cotas_data:
            return []

        # Filtrar apenas bolões apurados
        bolao_ids_apurados = list(set(
            c["bolao_id"] for c in cotas_data
            if c.get("bolao_status") == "apurado"
        ))

        if not bolao_ids_apurados:
            return []

        # 2. Buscar dados dos bolões
        boloes_result = supabase.table("boloes")\
            .select("id, nome, concurso_numero, concurso_fim, status, resultado_dezenas, total_cotas, cotas_disponiveis, valor_cota")\
            .in_("id", bolao_ids_apurados)\
            .execute()
        boloes_map = {b["id"]: b for b in (boloes_result.data or [])}

        # 3. Buscar jogos de todos os bolões
        jogos_result = supabase.table("jogos_bolao")\
            .select("id, bolao_id, dezenas, acertos")\
            .in_("bolao_id", bolao_ids_apurados)\
            .execute()

        jogos_por_bolao: Dict[str, list] = {}
        for j in (jogos_result.data or []):
            bid = j["bolao_id"]
            jogos_por_bolao.setdefault(bid, []).append(j)

        # 4. Buscar resultados_concurso (teimosinha)
        resultados_result = supabase.table("resultados_concurso")\
            .select("bolao_id, concurso_numero, dezenas")\
            .in_("bolao_id", bolao_ids_apurados)\
            .order("concurso_numero")\
            .execute()

        resultados_por_bolao: Dict[str, list] = {}
        for r in (resultados_result.data or []):
            bid = r["bolao_id"]
            resultados_por_bolao.setdefault(bid, []).append(r)

        # 5. Buscar acertos_concurso (teimosinha - acertos por jogo por concurso)
        acertos_result = supabase.table("acertos_concurso")\
            .select("bolao_id, concurso_numero, jogo_id, acertos")\
            .in_("bolao_id", bolao_ids_apurados)\
            .execute()

        acertos_map: Dict[str, Dict[int, Dict[str, int]]] = {}
        for a in (acertos_result.data or []):
            bid = a["bolao_id"]
            cn = a["concurso_numero"]
            jid = a["jogo_id"]
            acertos_map.setdefault(bid, {}).setdefault(cn, {})[jid] = a["acertos"]

        # 6. Buscar premiações
        premiacoes_result = supabase.table("premiacoes_bolao")\
            .select("bolao_id, concurso_numero, premio_total")\
            .in_("bolao_id", bolao_ids_apurados)\
            .execute()

        premiacoes_map: Dict[str, Dict[int, float]] = {}
        premio_total_por_bolao: Dict[str, float] = {}
        for p in (premiacoes_result.data or []):
            bid = p["bolao_id"]
            cn = p["concurso_numero"]
            val = float(p["premio_total"])
            premiacoes_map.setdefault(bid, {})[cn] = val
            premio_total_por_bolao[bid] = premio_total_por_bolao.get(bid, 0) + val

        # 7. Montar resposta
        response = []

        for cota in cotas_data:
            bid = cota["bolao_id"]
            if bid not in boloes_map:
                continue

            bolao = boloes_map[bid]
            is_teimosinha = bolao.get("concurso_fim") and bolao["concurso_fim"] > bolao["concurso_numero"]

            # Calcular quantidade de cotas do usuário
            vc = float(bolao.get("valor_cota", 0))
            user_qtd = max(1, round(float(cota["valor_pago"]) / vc)) if vc > 0 else 1

            # Calcular prêmio do usuário (proporcional)
            total_premio = premio_total_por_bolao.get(bid, 0)
            vendidas = bolao["total_cotas"] - bolao["cotas_disponiveis"]
            if vendidas > 0 and total_premio > 0:
                premio_usuario = round(total_premio * user_qtd / vendidas, 2)
            else:
                premio_usuario = 0

            # Montar resultados por concurso
            resultados_list = []
            jogos_bolao = jogos_por_bolao.get(bid, [])

            if is_teimosinha:
                # Teimosinha: múltiplos concursos
                for res in resultados_por_bolao.get(bid, []):
                    cn = res["concurso_numero"]
                    acertos_cn = acertos_map.get(bid, {}).get(cn, {})

                    jogos_com_acertos = []
                    for j in jogos_bolao:
                        jogos_com_acertos.append({
                            "dezenas": sorted(j["dezenas"]),
                            "acertos": acertos_cn.get(j["id"], 0)
                        })

                    resultados_list.append({
                        "concurso_numero": cn,
                        "dezenas_sorteadas": sorted(res["dezenas"]),
                        "premio_total": premiacoes_map.get(bid, {}).get(cn, 0),
                        "jogos": jogos_com_acertos,
                    })
            else:
                # Concurso único
                dezenas_resultado = bolao.get("resultado_dezenas")
                if dezenas_resultado:
                    resultado_set = set(dezenas_resultado)
                    jogos_com_acertos = []
                    for j in jogos_bolao:
                        acertos = len(set(j["dezenas"]) & resultado_set)
                        jogos_com_acertos.append({
                            "dezenas": sorted(j["dezenas"]),
                            "acertos": acertos
                        })

                    cn = bolao["concurso_numero"]
                    resultados_list.append({
                        "concurso_numero": cn,
                        "dezenas_sorteadas": sorted(dezenas_resultado),
                        "premio_total": premiacoes_map.get(bid, {}).get(cn, 0),
                        "jogos": jogos_com_acertos,
                    })

            if resultados_list:
                response.append({
                    "bolao_id": bid,
                    "bolao_nome": bolao["nome"],
                    "concurso_numero": bolao["concurso_numero"],
                    "concurso_fim": bolao.get("concurso_fim"),
                    "status": bolao["status"],
                    "resultados": resultados_list,
                    "premio_usuario": premio_usuario,
                    "quantidade_cotas": user_qtd,
                })

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro em /meus-resultados: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno: {str(e)}"
        )
