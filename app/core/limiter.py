"""
Configuração do rate limiter global (slowapi).
Importe `limiter` nos routers que precisam de limite de taxa.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
