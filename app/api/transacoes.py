"""
Rotas de transações
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Optional
from datetime import datetime

from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_current_user_id

router = APIRouter(prefix="/transacoes", tags=["Transações"])


@router.get("/")
async def listar_transacoes(
    usuario_id: str = Query(None, description="ID do usuário (opcional se autenticado)"),
    tipo: Optional[str] = Query(None, description="Filtrar por tipo: credito ou debito"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100)
):
    """
    Lista as transações do usuário autenticado ou especificado.
    
    Retorna as transações ordenadas da mais recente para a mais antiga.
    """
    
    # Se não passou usuario_id, pegar do token (implementar depois)
    # Por enquanto, aceitar via query param
    if not usuario_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="usuario_id é obrigatório"
        )
    
    try:
        # Construir query
        query = supabase.table("transacoes").select("*").eq("usuario_id", usuario_id)
        
        # Filtrar por tipo se especificado
        if tipo:
            if tipo not in ["credito", "debito"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="tipo deve ser 'credito' ou 'debito'"
                )
            query = query.eq("tipo", tipo)
        
        # Ordenar e paginar
        query = query.order("created_at", desc=True).limit(limit)
        
        # Executar
        response = query.execute()
        
        # Formatar resposta
        transacoes = []
        for t in response.data:
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
        
    except Exception as e:
        print(f"❌ Erro ao listar transações: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar transações: {str(e)}"
        )


@router.get("/resumo")
async def resumo_transacoes(
    usuario_id: str = Query(..., description="ID do usuário")
):
    """
    Retorna resumo das transações agrupadas por tipo e origem.
    """

    try:
        # Buscar todas as transações do usuário
        response = supabase.table("transacoes").select("tipo, valor, origem").eq("usuario_id", usuario_id).execute()

        # Calcular totais
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
            elif origem == "premio_bolao":
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

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao calcular resumo: {str(e)}"
        )