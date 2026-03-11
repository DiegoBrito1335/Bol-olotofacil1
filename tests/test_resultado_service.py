"""
Testes unitários para ResultadoService.calcular_e_distribuir_premio.

Cobre os cenários financeiros críticos:
  1. Nenhum jogo premiado → retorna 0, registra premio_total=0
  2. Premio zero já registrado → não duplica insert
  3. Distribuição normal entre compradores
  4. Cotas não vendidas vão para o criador
  5. Idempotência: crédito já existe → pula RPC
  6. Erro no RPC → has_errors=True → salva 0 para retry
  7. Carteira inexistente → cria automaticamente antes de creditar
  8. Arredondamento exato: soma dos créditos == premio_total
"""

from unittest.mock import patch
import pytest

from tests.conftest import FakeQueryResponse, make_supabase
from app.services.resultado_service import ResultadoService

BOLAO_ID = "bolao-test-uuid"
CONCURSO = 3000
BOLAO_DATA = {
    "nome": "Bolão Teste",
    "valor_cota": 10.0,
    "total_cotas": 10,
    "criador_id": "criador-uuid",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jogos(acertos_list: list[int]) -> list[dict]:
    """Gera lista de jogos com os acertos informados."""
    return [{"jogo_id": f"jogo-{i}", "dezenas": [], "acertos": a}
            for i, a in enumerate(acertos_list)]


def _prem(acertos_para_valor: dict) -> dict:
    """Converte {n_acertos: valor} em premiações."""
    return acertos_para_valor


# ---------------------------------------------------------------------------
# 1. Nenhum jogo premiado (acertos < min_acertos_premio = 11)
# ---------------------------------------------------------------------------

async def test_premio_zero_nenhum_jogo_premiado():
    jogos = _jogos([9, 10, 8])         # todos < 11
    premiacoes = {11: 500.0, 12: 1000.0, 15: 5000.0}

    supabase_mock = make_supabase({
        "premiacoes_bolao": [
            FakeQueryResponse(data=None, error=None),   # select → não existe
            FakeQueryResponse(data=[{"id": "p1"}], error=None),  # insert
        ],
    })

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    assert resultado == 0.0
    # Deve ter inserido o registro com premio_total=0
    insert_call = supabase_mock.table("premiacoes_bolao").insert.call_args
    assert insert_call is not None
    payload = insert_call[0][0]
    assert payload["premio_total"] == 0
    assert payload["bolao_id"] == BOLAO_ID


# ---------------------------------------------------------------------------
# 2. Premio zero já registrado → não duplica insert
# ---------------------------------------------------------------------------

async def test_premio_zero_ja_registrado():
    jogos = _jogos([8])
    premiacoes = {11: 500.0}

    supabase_mock = make_supabase({
        "premiacoes_bolao": [
            FakeQueryResponse(data=[{"id": "p1"}], error=None),  # já existe
        ],
    })

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    assert resultado == 0.0
    # insert NÃO deve ter sido chamado
    assert supabase_mock.table("premiacoes_bolao").insert.call_count == 0


# ---------------------------------------------------------------------------
# 3. Distribuição normal entre compradores (10 cotas vendidas = 10 total)
# ---------------------------------------------------------------------------

async def test_distribuicao_normal_compradores():
    jogos = _jogos([15, 14])            # dois jogos premiados
    premiacoes = {15: 300.0, 14: 200.0}  # premio_total = 500.0
    # 2 compradores: user-a com 6 cotas (valor_pago=60), user-b com 4 cotas (valor_pago=40)
    cotas_data = [
        {"usuario_id": "user-a", "valor_pago": 60.0},
        {"usuario_id": "user-b", "valor_pago": 40.0},
    ]

    supabase_mock = make_supabase(
        {
            "boloes": [FakeQueryResponse(data=[BOLAO_DATA])],
            "cotas": [FakeQueryResponse(data=cotas_data)],
            # user-a: transacao não existe, carteira existe
            # user-b: transacao não existe, carteira existe
            "transacoes": [
                FakeQueryResponse(data=[], error=None),
                FakeQueryResponse(data=[], error=None),
            ],
            "carteira": [
                FakeQueryResponse(data=[{"id": "c1"}]),
                FakeQueryResponse(data=[{"id": "c2"}]),
            ],
            "premiacoes_bolao": [
                FakeQueryResponse(data=None, error=None),       # select → não existe
                FakeQueryResponse(data=[{"id": "p1"}], error=None),  # insert
            ],
        },
        rpc_responses=[
            FakeQueryResponse(data={"saldo": 60.0}, error=None),  # user-a
            FakeQueryResponse(data={"saldo": 40.0}, error=None),  # user-b
        ],
    )

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    assert resultado == 500.0
    # RPC creditado duas vezes
    assert supabase_mock.rpc.call_count == 2

    # Verificar valores creditados proporcionalmente:
    # user-a: 6/10 × 500 = 300; user-b: 4/10 × 500 = 200
    creditos = [
        call[0][1]["p_valor"]              # segundo arg posicional = params dict
        for call in supabase_mock.rpc.call_args_list
    ]
    assert sorted(creditos) == [200.0, 300.0]


# ---------------------------------------------------------------------------
# 4. Cotas não vendidas vão para o criador
# ---------------------------------------------------------------------------

async def test_cotas_nao_vendidas_vao_para_criador():
    jogos = _jogos([15])
    premiacoes = {15: 1000.0}
    # Apenas 6 cotas vendidas de 10 → criador fica com 4
    cotas_data = [{"usuario_id": "user-a", "valor_pago": 60.0}]

    supabase_mock = make_supabase(
        {
            "boloes": [FakeQueryResponse(data=[BOLAO_DATA])],
            "cotas": [FakeQueryResponse(data=cotas_data)],
            # user-a: transacao, carteira
            # criador: transacao, carteira
            "transacoes": [
                FakeQueryResponse(data=[], error=None),
                FakeQueryResponse(data=[], error=None),
            ],
            "carteira": [
                FakeQueryResponse(data=[{"id": "c1"}]),
                FakeQueryResponse(data=[{"id": "c2"}]),
            ],
            "premiacoes_bolao": [
                FakeQueryResponse(data=None, error=None),
                FakeQueryResponse(data=[{"id": "p1"}], error=None),
            ],
        },
        rpc_responses=[
            FakeQueryResponse(data=None, error=None),
            FakeQueryResponse(data=None, error=None),
        ],
    )

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    assert resultado == 1000.0
    # 2 créditos: user-a + criador
    assert supabase_mock.rpc.call_count == 2

    usuarios_creditados = {
        call[0][1]["p_usuario_id"]
        for call in supabase_mock.rpc.call_args_list
    }
    assert "user-a" in usuarios_creditados
    assert "criador-uuid" in usuarios_creditados

    # user-a: 6/10 × 1000 = 600; criador: 4/10 × 1000 = 400
    creditos = sorted(
        call[0][1]["p_valor"]
        for call in supabase_mock.rpc.call_args_list
    )
    assert creditos == [400.0, 600.0]


# ---------------------------------------------------------------------------
# 5. Idempotência: crédito já existe → pula RPC
# ---------------------------------------------------------------------------

async def test_idempotencia_credito_ja_existente():
    jogos = _jogos([15])
    premiacoes = {15: 500.0}
    cotas_data = [{"usuario_id": "user-a", "valor_pago": 50.0}]

    supabase_mock = make_supabase(
        {
            "boloes": [FakeQueryResponse(data=[BOLAO_DATA])],
            "cotas": [FakeQueryResponse(data=cotas_data)],
            # transacao já existe para user-a
            "transacoes": [FakeQueryResponse(data=[{"id": "tx1"}], error=None)],
            "premiacoes_bolao": [
                FakeQueryResponse(data=None, error=None),
                FakeQueryResponse(data=[{"id": "p1"}], error=None),
            ],
        },
        rpc_responses=[FakeQueryResponse(data=None, error=None)],
    )

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    assert resultado == 500.0
    # RPC NÃO deve ter sido chamado (já creditado)
    assert supabase_mock.rpc.call_count == 0


# ---------------------------------------------------------------------------
# 6. Erro no RPC → has_errors=True → salva premio_total real (retry via redistribuir-premio)
# ---------------------------------------------------------------------------

async def test_rpc_error_salva_valor_real_para_retry():
    jogos = _jogos([15])
    premiacoes = {15: 500.0}
    cotas_data = [{"usuario_id": "user-a", "valor_pago": 50.0}]

    supabase_mock = make_supabase(
        {
            "boloes": [FakeQueryResponse(data=[BOLAO_DATA])],
            "cotas": [FakeQueryResponse(data=cotas_data)],
            "transacoes": [FakeQueryResponse(data=[], error=None)],
            "carteira": [FakeQueryResponse(data=[{"id": "c1"}])],
            "premiacoes_bolao": [
                FakeQueryResponse(data=None, error=None),
                FakeQueryResponse(data=[{"id": "p1"}], error=None),
            ],
        },
        rpc_responses=[FakeQueryResponse(data=None, error="DB error: constraint violation")],
    )

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    # Retorna o premio calculado mesmo com erro
    assert resultado == 500.0
    # premiacoes_bolao deve ser inserido com o valor real — admin usa redistribuir-premio para retentar
    insert_call = supabase_mock.table("premiacoes_bolao").insert.call_args
    assert insert_call is not None
    assert insert_call[0][0]["premio_total"] == 500.0


# ---------------------------------------------------------------------------
# 7. Carteira inexistente → cria automaticamente antes de creditar
# ---------------------------------------------------------------------------

async def test_carteira_inexistente_cria_automaticamente():
    jogos = _jogos([15])
    premiacoes = {15: 100.0}
    cotas_data = [{"usuario_id": "user-a", "valor_pago": 10.0}]
    # criador_id=None → cotas não vendidas não geram participante adicional
    bolao_sem_criador = {**BOLAO_DATA, "criador_id": None}

    supabase_mock = make_supabase(
        {
            "boloes": [FakeQueryResponse(data=[bolao_sem_criador])],
            "cotas": [FakeQueryResponse(data=cotas_data)],
            "transacoes": [FakeQueryResponse(data=[], error=None)],
            # carteira não existe na primeira consulta
            "carteira": [
                FakeQueryResponse(data=[], error=None),              # select → vazio
                FakeQueryResponse(data=[{"id": "new"}], error=None), # insert
            ],
            "premiacoes_bolao": [
                FakeQueryResponse(data=None, error=None),
                FakeQueryResponse(data=[{"id": "p1"}], error=None),
            ],
        },
        rpc_responses=[FakeQueryResponse(data=None, error=None)],
    )

    with patch("app.services.resultado_service.supabase", supabase_mock):
        await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    # insert na carteira deve ter sido chamado
    carteira_inserts = supabase_mock.table("carteira").insert.call_count
    assert carteira_inserts == 1
    # RPC creditado normalmente após criar a carteira
    assert supabase_mock.rpc.call_count == 1


# ---------------------------------------------------------------------------
# 8. Soma exata: arredondamento → último participante absorve diferença
# ---------------------------------------------------------------------------

async def test_soma_exata_arredondamento():
    """
    R$100 dividido por 3 participantes com 1 cota cada:
    33.33 + 33.33 + 33.34 = 100.00 (o último absorve a diferença)
    """
    jogos = _jogos([15])
    premiacoes = {15: 100.0}
    # 3 compradores, cada um com 1 cota (valor_pago=10)
    cotas_data = [
        {"usuario_id": "user-a", "valor_pago": 10.0},
        {"usuario_id": "user-b", "valor_pago": 10.0},
        {"usuario_id": "user-c", "valor_pago": 10.0},
    ]
    bolao_3_cotas = {**BOLAO_DATA, "total_cotas": 3}

    supabase_mock = make_supabase(
        {
            "boloes": [FakeQueryResponse(data=[bolao_3_cotas])],
            "cotas": [FakeQueryResponse(data=cotas_data)],
            "transacoes": [
                FakeQueryResponse(data=[], error=None),
                FakeQueryResponse(data=[], error=None),
                FakeQueryResponse(data=[], error=None),
            ],
            "carteira": [
                FakeQueryResponse(data=[{"id": "c1"}]),
                FakeQueryResponse(data=[{"id": "c2"}]),
                FakeQueryResponse(data=[{"id": "c3"}]),
            ],
            "premiacoes_bolao": [
                FakeQueryResponse(data=None, error=None),
                FakeQueryResponse(data=[{"id": "p1"}], error=None),
            ],
        },
        rpc_responses=[
            FakeQueryResponse(data=None, error=None),
            FakeQueryResponse(data=None, error=None),
            FakeQueryResponse(data=None, error=None),
        ],
    )

    with patch("app.services.resultado_service.supabase", supabase_mock):
        resultado = await ResultadoService.calcular_e_distribuir_premio(
            BOLAO_ID, CONCURSO, premiacoes, jogos
        )

    assert resultado == 100.0

    creditos = [
        call[0][1]["p_valor"]
        for call in supabase_mock.rpc.call_args_list
    ]
    # Soma exata deve ser R$100,00
    assert round(sum(creditos), 2) == 100.0
    # Nenhum crédito negativo
    assert all(v > 0 for v in creditos)
