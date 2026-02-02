"""
Rotas de autenticação e registro de usuários (modo desenvolvimento)
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.core.supabase import supabase_admin as supabase
from app.config import settings
import logging
import httpx

logger = logging.getLogger(__name__)

router = APIRouter()


class RegistroRequest(BaseModel):
    nome: str
    email: str
    senha: str
    telefone: Optional[str] = None


class RegistroResponse(BaseModel):
    id: str
    nome: str
    mensagem: str


@router.post("/register", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
async def registrar_usuario(request: RegistroRequest):
    """
    Registra um novo usuário.
    1. Cria usuário no Supabase Auth (auth.users)
    2. Cria perfil na tabela 'usuarios'
    3. Cria carteira com saldo zero
    """

    if not request.nome or not request.nome.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome é obrigatório"
        )

    if not request.email or not request.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail é obrigatório"
        )

    if not request.senha or len(request.senha) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha deve ter no mínimo 6 caracteres"
        )

    # 1. Criar usuário no Supabase Auth via Admin API
    auth_url = f"{settings.SUPABASE_URL}/auth/v1/admin/users"
    auth_headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }
    auth_payload = {
        "email": request.email.strip(),
        "password": request.senha,
        "email_confirm": True,
        "user_metadata": {"nome": request.nome.strip()},
    }

    try:
        auth_response = httpx.post(auth_url, json=auth_payload, headers=auth_headers, timeout=15.0)
    except Exception as e:
        logger.error(f"Erro de conexão com Supabase Auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao conectar com serviço de autenticação"
        )

    if auth_response.status_code == 422:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este e-mail já está cadastrado"
        )

    if auth_response.status_code not in (200, 201):
        error_detail = ""
        try:
            error_detail = auth_response.json().get("msg", auth_response.text)
        except Exception:
            error_detail = auth_response.text
        logger.error(f"Erro Supabase Auth {auth_response.status_code}: {error_detail}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar conta: {error_detail}"
        )

    auth_user = auth_response.json()
    usuario_id = auth_user["id"]

    # 2. Criar perfil na tabela 'usuarios'
    usuario_data = {
        "id": usuario_id,
        "nome": request.nome.strip(),
        "telefone": request.telefone,
    }

    result = supabase.table("usuarios").insert(usuario_data).execute()

    if result.error:
        logger.warning(f"Aviso: Erro ao criar perfil para {usuario_id}: {result.error}")

    # 3. Criar carteira com saldo zero
    carteira_data = {
        "usuario_id": usuario_id,
        "saldo_disponivel": 0.0,
        "saldo_bloqueado": 0.0,
    }

    cart_result = supabase.table("carteira").insert(carteira_data).execute()

    if cart_result.error:
        logger.warning(f"Aviso: Erro ao criar carteira para {usuario_id}: {cart_result.error}")

    logger.info(f"Usuário registrado: {usuario_id} - {request.nome}")

    return RegistroResponse(
        id=usuario_id,
        nome=request.nome.strip(),
        mensagem="Conta criada com sucesso!"
    )


class LoginRequest(BaseModel):
    email: str
    senha: str


class LoginResponse(BaseModel):
    id: str
    nome: str
    email: str


@router.post("/login", response_model=LoginResponse)
async def login_usuario(request: LoginRequest):
    """
    Autentica um usuário com e-mail e senha via Supabase Auth.
    Retorna o UUID do usuário para uso como Bearer token.
    """

    if not request.email or not request.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail é obrigatório"
        )

    if not request.senha:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha é obrigatória"
        )

    # Autenticar via Supabase Auth
    auth_url = f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password"
    auth_headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    auth_payload = {
        "email": request.email.strip(),
        "password": request.senha,
    }

    try:
        auth_response = httpx.post(auth_url, json=auth_payload, headers=auth_headers, timeout=15.0)
    except Exception as e:
        logger.error(f"Erro de conexão com Supabase Auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao conectar com serviço de autenticação"
        )

    if auth_response.status_code == 400:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="E-mail ou senha incorretos"
        )

    if auth_response.status_code not in (200, 201):
        logger.error(f"Erro Supabase Auth login {auth_response.status_code}: {auth_response.text}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao autenticar"
        )

    auth_data = auth_response.json()
    user = auth_data.get("user", {})
    usuario_id = user.get("id")
    user_email = user.get("email", request.email)

    # Buscar nome do perfil
    perfil = supabase.table("usuarios").select("nome").eq("id", usuario_id).execute()
    nome = ""
    if perfil.data:
        row = perfil.data[0] if isinstance(perfil.data, list) else perfil.data
        nome = row.get("nome", "")

    logger.info(f"Login bem-sucedido: {usuario_id} - {user_email}")

    return LoginResponse(
        id=usuario_id,
        nome=nome,
        email=user_email,
    )
