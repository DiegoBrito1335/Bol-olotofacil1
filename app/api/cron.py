"""
Endpoints de cron para tarefas automáticas via cron externo (ex: cron-job.org).
- Fechar bolões abertos às 20:55
- Apurar resultados pendentes
Protegido por SECRET_KEY no header.
"""

from fastapi import APIRouter, HTTPException, Header, status
from app.core.supabase import supabase_admin as supabase
from app.services.resultado_service import ResultadoService
from app.config import settings
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/apurar-resultados")
async def cron_apurar_resultados(x_cron_secret: str = Header(...)):
    """
    Apura resultados pendentes de TODOS os bolões ativos.
    Protegido por header X-Cron-Secret = SECRET_KEY.
    Chamado por serviço de cron externo (ex: cron-job.org).
    """
    if x_cron_secret != settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Secret inválido"
        )

    # Buscar bolões que não estão apurados nem cancelados
    boloes_result = supabase.table("boloes")\
        .select("id, nome, concurso_numero, concurso_fim, status")\
        .in_("status", ["aberto", "fechado"])\
        .execute()

    boloes = boloes_result.data or []

    if not boloes:
        return {
            "mensagem": "Nenhum bolão ativo para apurar",
            "boloes_processados": 0,
        }

    resultados = []

    for bolao in boloes:
        bolao_id = bolao["id"]

        # Verificar se tem jogos
        jogos_result = supabase.table("jogos_bolao")\
            .select("id")\
            .eq("bolao_id", bolao_id)\
            .limit(1)\
            .execute()

        if not jogos_result.data:
            continue

        try:
            resultado = await ResultadoService.apurar_pendentes(bolao_id)
            novos = len(resultado.get("resultados", []))
            if novos > 0:
                resultados.append({
                    "bolao_id": bolao_id,
                    "nome": bolao["nome"],
                    "novos_apurados": novos,
                    "premio_total": resultado.get("premio_total_geral", 0),
                })
                logger.info(f"Cron: apurou {novos} concursos do bolão {bolao['nome']}")
        except Exception as e:
            logger.error(f"Cron: erro ao apurar bolão {bolao_id}: {e}")
            resultados.append({
                "bolao_id": bolao_id,
                "nome": bolao["nome"],
                "erro": str(e),
            })

    return {
        "mensagem": f"{len(resultados)} bolões processados",
        "boloes_processados": len(resultados),
        "resultados": resultados,
    }


@router.post("/fechar-boloes")
async def cron_fechar_boloes(x_cron_secret: str = Header(...)):
    """
    Fecha todos os bolões com status 'aberto'.
    Deve ser chamado às 20:55 para impedir compras em cima da hora.
    Protegido por header X-Cron-Secret = SECRET_KEY.
    """
    if x_cron_secret != settings.SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Secret inválido"
        )

    # Buscar todos os bolões abertos
    boloes_result = supabase.table("boloes")\
        .select("id, nome")\
        .eq("status", "aberto")\
        .execute()

    boloes = boloes_result.data or []

    if not boloes:
        return {
            "mensagem": "Nenhum bolão aberto para fechar",
            "boloes_fechados": 0,
        }

    fechados = []

    for bolao in boloes:
        try:
            supabase.table("boloes")\
                .update({"status": "fechado"})\
                .eq("id", bolao["id"])\
                .execute()
            fechados.append({"bolao_id": bolao["id"], "nome": bolao["nome"]})
            logger.info(f"Cron: fechou bolão '{bolao['nome']}' (ID: {bolao['id']})")
        except Exception as e:
            logger.error(f"Cron: erro ao fechar bolão {bolao['id']}: {e}")

    return {
        "mensagem": f"{len(fechados)} bolões fechados",
        "boloes_fechados": len(fechados),
        "boloes": fechados,
    }
