"""
Rotas de compra de cotas
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_current_user

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
    Compra uma ou mais cotas de um bolão.
    Usa a função do banco que faz tudo atomicamente.
    """
    
    # Chamar função do banco que faz compra atômica
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
    
    # Resultado da função
    resultado = result.data
    
    if not resultado.get("sucesso"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=resultado.get("mensagem", "Erro ao comprar cota")
        )
    
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
    Lista todas as cotas do usuário logado
    """
    
    result = supabase.table("cotas")\
        .select("*, boloes(*)")\
        .eq("usuario_id", current_user["id"])\
        .execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar cotas: {result.error}"
        )
    
    return result.data or []