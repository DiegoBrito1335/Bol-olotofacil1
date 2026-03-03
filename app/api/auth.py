"""
Rotas de autenticação e registro de usuários
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from typing import Optional
from app.core.supabase import supabase_admin as supabase
from app.core.security import create_access_token
from app.core.limiter import limiter
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
    email: str
    mensagem: str
    is_admin: bool = False


@router.post("/register", response_model=RegistroResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def registrar_usuario(request: Request, body: RegistroRequest):
    """
    Registra um novo usuário.
    1. Cria usuário via Supabase Auth signup (envia email de confirmação)
    2. Cria perfil na tabela 'usuarios'
    3. Cria carteira com saldo zero
    Rate limit: 5 cadastros por minuto por IP.
    """

    if not body.nome or not body.nome.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nome é obrigatório"
        )

    if not body.email or not body.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail é obrigatório"
        )

    if not body.senha or len(body.senha) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha deve ter no mínimo 6 caracteres"
        )

    # 1. Criar usuário via Supabase Auth signup (envia email de confirmação automaticamente)
    redirect_to = f"{settings.FRONTEND_URL}/confirmar-email"
    auth_url = f"{settings.SUPABASE_URL}/auth/v1/signup?redirect_to={redirect_to}"
    auth_headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    auth_payload = {
        "email": body.email.strip(),
        "password": body.senha,
        "data": {"nome": body.nome.strip()},
    }

    try:
        auth_response = httpx.post(auth_url, json=auth_payload, headers=auth_headers, timeout=15.0)
    except Exception as e:
        logger.error(f"Erro de conexão com Supabase Auth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao conectar com serviço de autenticação"
        )

    if auth_response.status_code not in (200, 201):
        error_detail = ""
        try:
            resp_json = auth_response.json()
            error_detail = resp_json.get("msg", resp_json.get("message", auth_response.text))
        except Exception:
            error_detail = auth_response.text
        logger.error(f"Erro Supabase Auth signup {auth_response.status_code}: {error_detail}")

        # Email já cadastrado — Supabase retorna 400 ou 422 dependendo da versão/config
        if auth_response.status_code in (400, 422) or "already" in error_detail.lower() or "registered" in error_detail.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este e-mail já está cadastrado"
            )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar conta. Tente novamente."
        )

    resp_json = auth_response.json()

    # Supabase retorna estrutura diferente dependendo da configuração:
    # - Confirmação ativada: { id, email, identities, ... }
    # - Confirmação desativada: { access_token, user: { id, email, identities, ... } }
    if "user" in resp_json and isinstance(resp_json["user"], dict):
        auth_user = resp_json["user"]
    else:
        auth_user = resp_json

    # Email duplicado: Supabase retorna 200 mas com identities vazio
    identities = auth_user.get("identities", None)
    if identities is not None and len(identities) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este e-mail já está cadastrado"
        )

    usuario_id = auth_user.get("id")
    if not usuario_id:
        logger.error(f"Supabase signup não retornou id: {resp_json}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar conta"
        )

    # 2. Criar perfil na tabela 'usuarios'
    usuario_data = {
        "id": usuario_id,
        "nome": body.nome.strip(),
        "telefone": body.telefone,
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

    logger.info(f"Usuário registrado: {usuario_id} - {body.nome}")

    is_admin = body.email.strip().lower() in settings.admin_emails_list

    return RegistroResponse(
        id=usuario_id,
        nome=body.nome.strip(),
        email=body.email.strip(),
        mensagem="Cadastro realizado! Verifique seu email para confirmar a conta.",
        is_admin=is_admin,
    )


class LoginRequest(BaseModel):
    email: str
    senha: str


class LoginResponse(BaseModel):
    id: str
    nome: str
    email: str
    is_admin: bool = False
    access_token: str


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
async def login_usuario(request: Request, body: LoginRequest):
    """
    Autentica um usuário com e-mail e senha via Supabase Auth.
    Retorna um JWT assinado para uso como Bearer token.
    Rate limit: 10 tentativas por minuto por IP.
    """

    if not body.email or not body.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail é obrigatório"
        )

    if not body.senha:
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
        "email": body.email.strip(),
        "password": body.senha,
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
        try:
            err = auth_response.json()
            if "not confirmed" in err.get("error_description", "").lower():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="EMAIL_NOT_CONFIRMED"
                )
        except HTTPException:
            raise
        except Exception:
            pass
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
    user_email = user.get("email", body.email)

    # Buscar nome do perfil
    perfil = supabase.table("usuarios").select("nome").eq("id", usuario_id).execute()
    nome = ""
    if perfil.data:
        row = perfil.data[0] if isinstance(perfil.data, list) else perfil.data
        nome = row.get("nome", "")

    logger.info(f"Login bem-sucedido: {usuario_id} - {user_email}")

    is_admin = user_email.lower() in settings.admin_emails_list

    # Checar tabela admins (admins dinâmicos promovidos via painel)
    if not is_admin:
        admins_result = supabase.table("admins").select("usuario_id").eq("usuario_id", usuario_id).execute()
        if admins_result.data:
            is_admin = True

    # Gerar JWT assinado com SECRET_KEY
    access_token = create_access_token(
        user_id=usuario_id,
        email=user_email,
        is_admin=is_admin,
    )

    return LoginResponse(
        id=usuario_id,
        nome=nome,
        email=user_email,
        is_admin=is_admin,
        access_token=access_token,
    )


class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
@limiter.limit("3/minute")
async def esqueceu_senha(request: Request, body: ForgotPasswordRequest):
    """
    Envia email de recuperação de senha.
    Sempre retorna 200 para não revelar se o email existe.
    Rate limit: 3 por minuto por IP (anti-spam de email).
    """

    if not body.email or not body.email.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail é obrigatório"
        )

    redirect_to = f"{settings.FRONTEND_URL}/redefinir-senha"
    auth_url = f"{settings.SUPABASE_URL}/auth/v1/recover"
    auth_headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Content-Type": "application/json",
    }
    auth_payload = {
        "email": body.email.strip(),
        "redirect_to": redirect_to,
    }

    try:
        httpx.post(auth_url, json=auth_payload, headers=auth_headers, timeout=15.0)
    except Exception as e:
        logger.error(f"Erro ao enviar email de recuperação: {e}")

    return {"mensagem": "Se esse email estiver cadastrado, você receberá um link em instantes."}


class ResetPasswordRequest(BaseModel):
    access_token: str
    nova_senha: str


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def redefinir_senha(request: ResetPasswordRequest):
    """
    Redefine a senha usando o access_token recebido no email de recuperação.
    """

    if not request.nova_senha or len(request.nova_senha) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nova senha deve ter no mínimo 6 caracteres"
        )

    auth_url = f"{settings.SUPABASE_URL}/auth/v1/user"
    auth_headers = {
        "apikey": settings.SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {request.access_token}",
        "Content-Type": "application/json",
    }
    auth_payload = {"password": request.nova_senha}

    try:
        auth_response = httpx.put(auth_url, json=auth_payload, headers=auth_headers, timeout=15.0)
    except Exception as e:
        logger.error(f"Erro ao redefinir senha: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao conectar com serviço de autenticação"
        )

    if auth_response.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Link de recuperação inválido ou expirado"
        )

    if auth_response.status_code not in (200, 201):
        logger.error(f"Erro ao redefinir senha {auth_response.status_code}: {auth_response.text}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao redefinir senha"
        )

    logger.info("Senha redefinida com sucesso")
    return {"mensagem": "Senha redefinida com sucesso!"}
