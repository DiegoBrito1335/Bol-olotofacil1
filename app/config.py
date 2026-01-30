from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    """
    Configurações da aplicação.
    Carrega variáveis do arquivo .env automaticamente.
    """
    
    # Aplicação
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_ANON_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str
    DATABASE_URL: str
    
    # Segurança
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Mercado Pago (opcional por enquanto)
    MERCADOPAGO_ACCESS_TOKEN: str = ""
    MERCADOPAGO_ENV: str = "sandbox"
    WEBHOOK_URL: str = ""
    
    # CORS
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    
    # Logs
    LOG_LEVEL: str = "DEBUG"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Converte string de CORS_ORIGINS em lista"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Instância única das configurações
settings = Settings()