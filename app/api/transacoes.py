"""
Rotas de transações
"""

from fastapi import APIRouter, HTTPException, status, Query, Depends
from typing import Optional
import logging

from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transacoes", tags=["Transações"])


@router.get("/")
async def listar_transacoes(
    tipo: Optional[str] = Query(None, description="Filtrar por tipo: credito ou debito"),
    limit: int = Query(50, ge=1, le=100),
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Lista as transações do usuário autenticado.

    Retorna as transações ordenadas da mais recente para a mais antiga.
    """

    try:
        query = supabase.table("transacoes").select("*").eq("usuario_id", current_user_id)

        if tipo:
            if tipo not in ["credito", "debito"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="tipo deve ser 'credito' ou 'debito'"
                )
            query = query.eq("tipo", tipo)

        query = query.order("created_at", desc=True).limit(limit)

        response = query.execute()

        transacoes = []
        for t in (response.data or []):
            transacoes.append({
                "id": t["id"],
                "tipo": t["tipo"],
                "valor": t["valor"],
                "origem": t["origem"],
                "descricao": t.get("descricao"),
                "saldo_anterior": t["saldo_anterior"],
                "saldo_posterior": t["saldo_posterior"],
                "status": t["status"],
                "created_at": t["created_at"],
            })

        return transacoes

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao listar transações para {current_user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao buscar transações"
        )


@router.get("/resumo")
async def resumo_transacoes(
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Retorna resumo das transações agrupadas por tipo e origem.
    """

    try:
        response = supabase.table("transacoes")\
            .select("tipo, valor, origem")\
            .eq("usuario_id", current_user_id)\
            .execute()

        total_credito = 0
        total_debito = 0
        total_depositos = 0
        total_premios = 0
        total_compras = 0

        for t in (response.data or []):
            valor = float(t["valor"])
            if t["tipo"] == "credito":
                total_credito += valor
            elif t["tipo"] == "debito":
                total_debito += valor

            origem = t.get("origem", "")
            if origem == "pix":
                total_depositos += valor
            elif origem == "premiacao":
                total_premios += valor
            elif origem == "compra_cota":
                total_compras += valor

        return {
            "total_depositos": round(total_depositos, 2),
            "total_premios": round(total_premios, 2),
            "total_compras": round(total_compras, 2),
            "total_credito": round(total_credito, 2),
            "total_debito": round(total_debito, 2),
            "saldo_movimentado": round(total_credito - total_debito, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao calcular resumo de transações para {current_user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao calcular resumo"
        )
