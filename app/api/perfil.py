"""
Rotas de perfil do usuário
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
from typing import Optional
from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class PerfilResponse(BaseModel):
    nome: str
    email: str
    telefone: Optional[str] = None
    chave_pix: Optional[str] = None


class PerfilUpdate(BaseModel):
    nome: Optional[str] = None
    telefone: Optional[str] = None
    chave_pix: Optional[str] = None


@router.get("", response_model=PerfilResponse)
async def get_perfil(current_user=Depends(get_current_user)):
    """Retorna dados do perfil do usuário."""

    # Tentar com chave_pix, fallback sem (coluna pode não existir ainda)
    result = await supabase.table("usuarios")\
        .select("nome, telefone, chave_pix")\
        .eq("id", current_user["id"])\
        .execute()

    if result.error:
        # Fallback: buscar sem chave_pix
        result = await supabase.table("usuarios")\
            .select("nome, telefone")\
            .eq("id", current_user["id"])\
            .execute()

    # Buscar email do Supabase Auth (necessário independentemente do resultado acima)
    email = ""
    nome_auth = ""
    try:
        import httpx
        from app.config import settings
        auth_url = f"{settings.SUPABASE_URL}/auth/v1/admin/users/{current_user['id']}"
        auth_headers = {
            "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        }
        async with httpx.AsyncClient() as _client:
            resp = await _client.get(auth_url, headers=auth_headers, timeout=10.0)
        if resp.status_code == 200:
            auth_data = resp.json()
            email = auth_data.get("email", "")
            nome_auth = auth_data.get("user_metadata", {}).get("nome", "")
    except Exception as e:
        logger.warning(f"Erro ao buscar email: {e}")

    if result.error or not result.data:
        # Perfil não existe — auto-criar com dados do Auth
        logger.info(f"Criando perfil ausente para usuário {current_user['id']}")
        nome_inicial = nome_auth or email.split("@")[0] if email else "Usuário"
        await supabase.table("usuarios").insert({
            "id": current_user["id"],
            "nome": nome_inicial,
            "telefone": None,
        }).execute()
        # Garantir que a carteira também existe
        carteira_check = await supabase.table("carteira").select("id").eq("usuario_id", current_user["id"]).execute()
        if not carteira_check.data:
            await supabase.table("carteira").insert({
                "usuario_id": current_user["id"],
                "saldo_disponivel": 0.0,
                "saldo_bloqueado": 0.0,
            }).execute()
        return PerfilResponse(
            nome=nome_inicial,
            email=email,
            telefone=None,
            chave_pix=None,
        )

    perfil = result.data[0] if isinstance(result.data, list) else result.data

    return PerfilResponse(
        nome=perfil.get("nome", ""),
        email=email,
        telefone=perfil.get("telefone"),
        chave_pix=perfil.get("chave_pix"),
    )


@router.put("")
async def update_perfil(
    data: PerfilUpdate,
    current_user=Depends(get_current_user)
):
    """Atualiza dados do perfil do usuário."""

    update_data = {}
    if data.nome is not None:
        if not data.nome.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nome não pode ser vazio"
            )
        update_data["nome"] = data.nome.strip()
    if data.telefone is not None:
        update_data["telefone"] = data.telefone.strip() or None
    if data.chave_pix is not None:
        update_data["chave_pix"] = data.chave_pix.strip() or None

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum dado para atualizar"
        )

    result = await supabase.table("usuarios")\
        .update(update_data)\
        .eq("id", current_user["id"])\
        .execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar perfil: {result.error}"
        )

    return {"mensagem": "Perfil atualizado com sucesso"}
