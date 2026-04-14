"""
Configuração de testes e helpers compartilhados.
As env vars são definidas antes de qualquer import da app para
evitar erros de validação do pydantic-settings.
"""
import os
import sys

# Garantir que o diretório raiz do projeto está no sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Variáveis de ambiente mínimas para que app.config.Settings() não falhe ao importar
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("ENVIRONMENT", "test")

from unittest.mock import MagicMock, AsyncMock


class FakeQueryResponse:
    """Simula app.core.supabase.QueryResponse com .data e .error."""

    def __init__(self, data=None, error=None):
        self.data = data
        self.error = error


def make_chain(responses: list):
    """
    Retorna um MagicMock que suporta encadeamento ilimitado de métodos
    (.select, .eq, .like_, .limit, .update, .insert, .order)
    e devolve respostas sucessivas em cada chamada a .execute().
    """
    mock = MagicMock()
    for method in ("select", "eq", "like_", "limit", "update", "insert", "order"):
        getattr(mock, method).return_value = mock
    
    mock.execute = AsyncMock()
    if len(responses) == 1:
        mock.execute.return_value = responses[0]
    else:
        mock.execute.side_effect = list(responses)
    return mock


def make_supabase(table_map: dict, rpc_responses: list | None = None):
    """
    Constrói um mock do cliente supabase.

    table_map: {nome_tabela: [FakeQueryResponse, ...]}
        — cada item na lista é devolvido por execute() em ordem sequencial.
    rpc_responses: [FakeQueryResponse, ...] para chamadas a .rpc(...).execute()
    """
    chains = {name: make_chain(resps) for name, resps in table_map.items()}

    mock = MagicMock()
    mock.table.side_effect = lambda name: chains[name]

    if rpc_responses is not None:
        rpc_chain = MagicMock()
        rpc_chain.execute = AsyncMock()
        if len(rpc_responses) == 1:
            rpc_chain.execute.return_value = rpc_responses[0]
        else:
            rpc_chain.execute.side_effect = list(rpc_responses)
        mock.rpc.return_value = rpc_chain

    return mock
