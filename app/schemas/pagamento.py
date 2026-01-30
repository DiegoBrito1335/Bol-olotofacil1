from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional


class CriarPagamentoPixRequest(BaseModel):
    """
    Requisição para criar pagamento Pix
    """
    valor: Decimal
    descricao: Optional[str] = "Depósito para bolões"
    
    class Config:
        json_schema_extra = {
            "example": {
                "valor": 100.00,
                "descricao": "Adicionar R$ 100 ao saldo"
            }
        }


class PagamentoPixResponse(BaseModel):
    """
    Resposta com dados do Pix gerado
    """
    id: str
    status: str
    valor: Decimal
    qr_code: str
    qr_code_base64: str
    expira_em: datetime
    external_id: str
    
    class Config:
        from_attributes = True


class WebhookMercadoPagoPayload(BaseModel):
    """
    Payload recebido do webhook do Mercado Pago
    """
    action: str
    api_version: str
    data: dict
    date_created: datetime
    id: int
    live_mode: bool
    type: str
    user_id: str