import httpx
from typing import Optional, Dict, Any
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class SupabaseHTTPClient:
    """
    Cliente HTTP para Supabase usando httpx.
    Funciona exatamente como o cliente oficial, mas sem dependências pesadas.
    Usa um httpx.Client persistente para reutilizar conexões TCP/SSL.
    """

    def __init__(self, api_key: str):
        self.base_url = settings.SUPABASE_URL
        self.api_key = api_key
        self.headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }
        self._client = httpx.Client(
            headers=self.headers,
            timeout=15.0,
        )

    def table(self, table_name: str):
        """Retorna uma instância de TableQuery"""
        return TableQuery(self.base_url, table_name, self.headers, self._client)

    def rpc(self, function_name: str, params: dict):
        """Chama uma função RPC (Remote Procedure Call) no Supabase"""
        return RPCQuery(self.base_url, function_name, params, self.headers, self._client)

class TableQuery:
    """
    Simula o comportamento do cliente Supabase para queries em tabelas.
    """

    def __init__(self, base_url: str, table_name: str, headers: Dict[str, str], client: httpx.Client):
        self.base_url = base_url
        self.table_name = table_name
        self.headers = dict(headers)
        self.url = f"{base_url}/rest/v1/{table_name}"
        self._client = client
        self._select_fields = "*"
        self._filters = []
        self._limit_value = None
        self._order_by = None
        self._operation = "select"
        self._payload = None
    
    def select(self, fields: str = "*", count: Optional[str] = None):
        """Define quais campos selecionar"""
        self._select_fields = fields
        if count:
            self.headers["Prefer"] = f"count={count}"
        return self
    
    def eq(self, column: str, value: Any):
        """Adiciona filtro de igualdade"""
        self._filters.append(f"{column}=eq.{value}")
        return self

    def in_(self, column: str, values: list):
        """Adiciona filtro IN (lista de valores)"""
        values_str = ",".join(str(v) for v in values)
        self._filters.append(f"{column}=in.({values_str})")
        return self
    
    def limit(self, count: int):
        """Define limite de resultados"""
        self._limit_value = count
        return self
    
    def order(self, column: str, desc: bool = False):
        """Define ordenação"""
        direction = "desc" if desc else "asc"
        self._order_by = f"{column}.{direction}"
        return self
    
    def execute(self):
        """Executa a query (select, insert, update ou delete)"""
        try:
            if self._operation == "insert":
                response = self._client.post(self.url, json=self._payload, headers=self.headers)
                response.raise_for_status()
                return QueryResponse(response.json(), None)

            elif self._operation == "update":
                url = self.url
                if self._filters:
                    filter_params = "&".join(self._filters)
                    url = f"{url}?{filter_params}"
                response = self._client.patch(url, json=self._payload, headers=self.headers)
                response.raise_for_status()
                return QueryResponse(response.json(), None)

            elif self._operation == "delete":
                url = self.url
                if self._filters:
                    filter_params = "&".join(self._filters)
                    url = f"{url}?{filter_params}"
                response = self._client.delete(url, headers=self.headers)
                response.raise_for_status()
                # DELETE pode retornar lista vazia ou dados
                try:
                    data = response.json()
                except Exception:
                    data = []
                return QueryResponse(data, None)

            else:
                # SELECT
                params = {"select": self._select_fields}
                if self._filters:
                    for filter_str in self._filters:
                        key, value = filter_str.split("=", 1)
                        params[key] = value
                if self._limit_value:
                    params["limit"] = self._limit_value
                if self._order_by:
                    params["order"] = self._order_by
                response = self._client.get(self.url, headers=self.headers, params=params)
                response.raise_for_status()
                return QueryResponse(response.json(), None)

        except httpx.HTTPStatusError as e:
            error_body = ""
            try:
                error_body = e.response.text
            except Exception:
                pass
            logger.error(f"Erro HTTP {e.response.status_code} em {self._operation} {self.table_name}: {error_body}")
            return QueryResponse(None, error_body or str(e))
        except Exception as e:
            logger.error(f"Erro ao executar {self._operation} em {self.table_name}: {str(e)}")
            return QueryResponse(None, str(e))
    
    def insert(self, data: Dict[str, Any]):
        """Prepara inserção de dados na tabela (executa em .execute())"""
        self._operation = "insert"
        self._payload = data
        return self

    def update(self, data: Dict[str, Any]):
        """Prepara atualização de dados na tabela (executa em .execute())"""
        self._operation = "update"
        self._payload = data
        return self

    def delete(self):
        """Prepara deleção de dados na tabela (executa em .execute())"""
        self._operation = "delete"
        self._payload = None
        return self


class QueryResponse:
    """
    Simula o objeto de resposta do Supabase
    """
    
    def __init__(self, data: Any, error: Optional[str]):
        self.data = data
        self.error = error

class RPCQuery:
    """
    Executa chamadas RPC (funções SQL) no Supabase
    """

    def __init__(self, base_url: str, function_name: str, params: dict, headers: dict, client: httpx.Client):
        self.base_url = base_url
        self.function_name = function_name
        self.params = params
        self.headers = headers
        self._client = client
        self.url = f"{base_url}/rest/v1/rpc/{function_name}"

    def execute(self):
        """Executa a função RPC"""
        try:
            response = self._client.post(self.url, json=self.params, headers=self.headers)
            response.raise_for_status()
            return QueryResponse(response.json(), None)
        except Exception as e:
            logger.error(f"Erro ao executar RPC {self.function_name}: {str(e)}")
            return QueryResponse(None, str(e))


# Instâncias globais
supabase = SupabaseHTTPClient(api_key=settings.SUPABASE_ANON_KEY)
supabase_admin = SupabaseHTTPClient(api_key=settings.SUPABASE_SERVICE_ROLE_KEY)