"""
Gerenciamento de usuários (admin).
- Listar todos os usuários com saldo e info de admin
- Promover/rebaixar admin (via tabela 'admins')
- Remover perfil de usuário
"""

from fastapi import APIRouter, HTTPException, status, Depends
from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_admin_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_user)])


@router.get("")
async def listar_usuarios(current_admin_id: str = Depends(get_admin_user)):
    """
    Lista todos os usuários com perfil, saldo e status de admin.
    """
    # 1. Perfis
    perfis_result = await supabase.table("usuarios").select("id, nome, telefone").execute()
    perfis = perfis_result.data or []
    perfil_map = {p["id"]: p for p in perfis}

    # 2. Carteiras
    carteiras_result = await supabase.table("carteira").select("usuario_id, saldo_disponivel, saldo_bloqueado").execute()
    carteiras = carteiras_result.data or []
    carteira_map = {c["usuario_id"]: c for c in carteiras}

    # 3. Admins dinâmicos (tabela admins)
    admins_result = await supabase.table("admins").select("usuario_id").execute()
    admins_ids = {r["usuario_id"] for r in (admins_result.data or [])}

    # 4. Emails via Auth Admin API
    auth_users = await supabase.get_auth_users()
    email_map = {u["id"]: u.get("email", "") for u in auth_users}
    created_map = {u["id"]: u.get("created_at", "") for u in auth_users}

    # 5. Montar lista (todos os usuários que têm perfil OU auth)
    todos_ids = set(perfil_map.keys()) | {u["id"] for u in auth_users}

    resultado = []
    for uid in todos_ids:
        perfil = perfil_map.get(uid, {})
        carteira = carteira_map.get(uid, {})
        resultado.append({
            "id": uid,
            "nome": perfil.get("nome"),
            "email": email_map.get(uid, ""),
            "telefone": perfil.get("telefone"),
            "saldo_disponivel": float(carteira.get("saldo_disponivel", 0)),
            "saldo_bloqueado": float(carteira.get("saldo_bloqueado", 0)),
            "is_admin": uid in admins_ids,
            "created_at": created_map.get(uid, ""),
        })

    # Ordenar por data de criação (mais recentes primeiro)
    resultado.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return resultado


@router.post("/{usuario_id}/promover", status_code=status.HTTP_200_OK)
async def promover_admin(usuario_id: str, current_admin_id: str = Depends(get_admin_user)):
    """
    Promove um usuário a administrador.
    """
    # Buscar email do usuário via Auth API
    auth_users = await supabase.get_auth_users()
    usuario = next((u for u in auth_users if u["id"] == usuario_id), None)

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não encontrado"
        )

    email = usuario.get("email", "")

    # Verificar se já é admin
    existing = await supabase.table("admins").select("usuario_id").eq("usuario_id", usuario_id).execute()
    if existing.data:
        return {"mensagem": "Usuário já é administrador"}

    result = await supabase.table("admins").insert({
        "usuario_id": usuario_id,
        "email": email,
    }).execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao promover usuário: {result.error}"
        )

    logger.info(f"Usuário {email} ({usuario_id}) promovido a admin por {current_admin_id}")
    return {"mensagem": f"Usuário {email} promovido a administrador. Terá acesso na próxima vez que fizer login."}


@router.delete("/{usuario_id}/rebaixar", status_code=status.HTTP_200_OK)
async def rebaixar_admin(usuario_id: str, current_admin_id: str = Depends(get_admin_user)):
    """
    Remove o status de administrador de um usuário.
    """
    if usuario_id == current_admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode remover seu próprio acesso de admin"
        )

    result = await supabase.table("admins").delete().eq("usuario_id", usuario_id).execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao rebaixar usuário: {result.error}"
        )

    logger.info(f"Usuário {usuario_id} removido de admin por {current_admin_id}")
    return {"mensagem": "Acesso de administrador removido. Terá efeito na próxima vez que o usuário fizer login."}


@router.delete("/{usuario_id}", status_code=status.HTTP_200_OK)
async def remover_usuario(usuario_id: str, current_admin_id: str = Depends(get_admin_user)):
    """
    Remove completamente um usuário (perfil + conta Supabase Auth).
    Falha se o usuário tiver cotas vinculadas.
    """
    if usuario_id == current_admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Você não pode remover sua própria conta"
        )

    # Verificar cotas
    cotas = await supabase.table("cotas").select("id").eq("usuario_id", usuario_id).limit(1).execute()
    if cotas.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuário possui cotas em bolões — não é possível remover. Use o painel do Supabase para exclusão completa."
        )

    # Remover da tabela admins (se for admin)
    await supabase.table("admins").delete().eq("usuario_id", usuario_id).execute()

    # Remover da tabela usuarios (perfil)
    await supabase.table("usuarios").delete().eq("id", usuario_id).execute()

    # Remover carteira
    await supabase.table("carteira").delete().eq("usuario_id", usuario_id).execute()

    # Remover conta do Supabase Auth
    try:
        await supabase.delete_auth_user(usuario_id)
    except Exception as e:
        logger.error(f"Erro ao deletar auth user {usuario_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Perfil removido, mas houve erro ao remover a conta de autenticação. Remova manualmente no Supabase."
        )

    logger.info(f"Usuário {usuario_id} removido por admin {current_admin_id}")
    return {"mensagem": "Usuário removido com sucesso"}
