from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.core.limiter import limiter
import logging
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.httpx import HttpxIntegration
from app.api import transacoes

# ====================================
# IMPORTS DAS ROTAS PÚBLICAS
# ====================================
from app.api import auth
from app.api import carteira
from app.api import boloes
from app.api import pagamentos
from app.api import cotas
from app.api import perfil

# ====================================
# IMPORTS DAS ROTAS ADMIN
# ====================================
from app.api.v1.admin.boloes import router as admin_boloes_router
from app.api.v1.admin.stats import router as admin_stats_router
from app.api.v1.admin.usuarios import router as admin_usuarios_router
from app.api.cron import router as cron_router


# Configurar logs
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# Inicializar Sentry (monitoramento de erros)
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        integrations=[
            FastApiIntegration(),
            HttpxIntegration(),
        ],
        traces_sample_rate=0.1,  # 10% de requests rastreados para performance
        send_default_pii=False,  # não enviar dados pessoais
    )

logger = logging.getLogger(__name__)

# Criar aplicação FastAPI
app = FastAPI(
    title="Bolão Lotofácil API",
    description="Backend da plataforma de bolões da Lotofácil",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False
)

# Registrar rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Cron-Secret"],
)

# ====================================
# INCLUIR ROTAS PÚBLICAS
# ====================================

app.include_router(
    auth.router,
    prefix="/api/v1/auth",
    tags=["Autenticação"]
)

app.include_router(
    transacoes.router,
    prefix="/api/v1",
    tags=["Transações"]
)

app.include_router(
    cotas.router,
    prefix="/api/v1/cotas",
    tags=["Cotas"]
)

app.include_router(
    boloes.router,
    prefix="/api/v1/boloes",
    tags=["Bolões"]
)

app.include_router(
    carteira.router,
    prefix="/api/v1/carteira",
    tags=["Carteira"]
)

app.include_router(
    pagamentos.router,
    prefix="/api/v1/pagamentos",
    tags=["Pagamentos"]
)

app.include_router(
    perfil.router,
    prefix="/api/v1/perfil",
    tags=["Perfil"]
)

# ====================================
# INCLUIR ROTAS ADMIN
# ====================================

app.include_router(
    admin_boloes_router,
    prefix="/api/v1/admin/boloes",
    tags=["Admin - Bolões"]
)

app.include_router(
    admin_stats_router,
    prefix="/api/v1/admin",
    tags=["Admin - Dashboard"]
)

app.include_router(
    admin_usuarios_router,
    prefix="/api/v1/admin/usuarios",
    tags=["Admin - Usuários"]
)

app.include_router(
    cron_router,
    prefix="/api/v1/cron",
    tags=["Cron"]
)

# ====================================
# HEALTH CHECK
# ====================================

@app.get("/")
async def health_check():
    """Health check para Railway"""
    return {"status": "ok", "service": "bolao-lotofacil-api"}

# ====================================
# EVENTOS
# ====================================

@app.on_event("startup")
async def startup_event():
    """
    Executado quando a aplicação inicia
    """
    logger.info("🚀 Iniciando Bolão Lotofácil API")
    logger.info(f"📦 Ambiente: {settings.ENVIRONMENT}")
    logger.info(f"🔗 Supabase URL: {settings.SUPABASE_URL}")
    logger.info(f"🌐 CORS Origins: {settings.cors_origins_list}")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Executado quando a aplicação é desligada
    """
    logger.info("🔴 Desligando Bolão Lotofácil API")