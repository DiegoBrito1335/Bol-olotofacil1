"""
Rotas administrativas para estatisticas e dashboard
"""

from fastapi import APIRouter, Depends, HTTPException, status
from datetime import datetime, timedelta
from app.core.supabase import supabase_admin as supabase
from app.api.deps import get_admin_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_user)])


@router.get("/stats")
async def get_stats():
    """
    Estatisticas gerais do sistema para o dashboard admin.
    """
    try:
        # Total de boloes
        boloes_result = supabase.table("boloes").select("id, status, valor_cota, total_cotas, cotas_disponiveis").execute()
        boloes = boloes_result.data or []

        total_boloes = len(boloes)
        boloes_abertos = len([b for b in boloes if b["status"] == "aberto"])
        boloes_fechados = len([b for b in boloes if b["status"] == "fechado"])
        boloes_apurados = len([b for b in boloes if b["status"] == "apurado"])

        # Total de cotas vendidas e receita
        cotas_result = supabase.table("cotas").select("id, valor_pago").execute()
        cotas = cotas_result.data or []
        total_cotas_vendidas = len(cotas)
        receita_total = sum(float(c.get("valor_pago", 0)) for c in cotas)

        # Total de usuarios (carteiras unicas)
        carteiras_result = supabase.table("carteira").select("usuario_id, saldo_disponivel").execute()
        carteiras = carteiras_result.data or []
        total_usuarios = len(carteiras)
        saldo_total_carteiras = sum(float(c.get("saldo_disponivel", 0)) for c in carteiras)

        return {
            "total_boloes": total_boloes,
            "boloes_abertos": boloes_abertos,
            "boloes_fechados": boloes_fechados,
            "boloes_apurados": boloes_apurados,
            "total_cotas_vendidas": total_cotas_vendidas,
            "receita_total": round(receita_total, 2),
            "total_usuarios": total_usuarios,
            "saldo_total_carteiras": round(saldo_total_carteiras, 2),
        }

    except Exception as e:
        logger.error(f"Erro ao buscar stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar estatisticas: {str(e)}"
        )


@router.get("/stats/quick")
async def get_quick_stats():
    """
    Estatisticas rapidas para cards do dashboard.
    """
    try:
        # Boloes abertos
        boloes_result = supabase.table("boloes").select("id").eq("status", "aberto").execute()
        boloes_abertos = len(boloes_result.data) if boloes_result.data else 0

        # Cotas vendidas (total)
        cotas_result = supabase.table("cotas").select("id, valor_pago").execute()
        cotas = cotas_result.data or []
        total_cotas = len(cotas)
        receita_total = sum(float(c.get("valor_pago", 0)) for c in cotas)

        # Usuarios
        carteiras_result = supabase.table("carteira").select("usuario_id").execute()
        total_usuarios = len(carteiras_result.data) if carteiras_result.data else 0

        # Pagamentos pendentes
        pagamentos_result = supabase.table("pagamentos_pix").select("id").eq("status", "pendente").execute()
        pagamentos_pendentes = len(pagamentos_result.data) if pagamentos_result.data else 0

        return {
            "boloes_ativos": boloes_abertos,
            "total_cotas_vendidas": total_cotas,
            "receita_total": round(receita_total, 2),
            "total_usuarios": total_usuarios,
            "pagamentos_pendentes": pagamentos_pendentes,
        }

    except Exception as e:
        logger.error(f"Erro ao buscar quick stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar estatisticas rapidas: {str(e)}"
        )


@router.get("/stats/revenue")
async def get_revenue_chart():
    """
    Dados de receita para o grafico do dashboard.
    Retorna receita dos ultimos 30 dias agrupada por dia.
    """
    try:
        # Buscar todas as cotas com data de criacao
        cotas_result = supabase.table("cotas").select("valor_pago, created_at").execute()
        cotas = cotas_result.data or []

        # Agrupar por dia nos ultimos 30 dias
        hoje = datetime.now().date()
        inicio = hoje - timedelta(days=29)

        # Inicializar todos os dias com 0
        receita_por_dia = {}
        for i in range(30):
            dia = inicio + timedelta(days=i)
            receita_por_dia[dia.isoformat()] = 0.0

        # Somar receita por dia
        for cota in cotas:
            if cota.get("created_at"):
                data_cota = cota["created_at"][:10]  # "2026-01-31T..." -> "2026-01-31"
                if data_cota in receita_por_dia:
                    receita_por_dia[data_cota] += float(cota.get("valor_pago", 0))

        # Converter para lista ordenada
        chart_data = [
            {"data": dia, "receita": round(valor, 2)}
            for dia, valor in sorted(receita_por_dia.items())
        ]

        return chart_data

    except Exception as e:
        logger.error(f"Erro ao buscar revenue chart: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar dados de receita: {str(e)}"
        )


@router.get("/activity")
async def get_recent_activity():
    """
    Atividade recente do sistema para o feed do dashboard.
    """
    try:
        atividades = []

        # Ultimas cotas compradas
        cotas_result = supabase.table("cotas")\
            .select("id, usuario_id, bolao_id, valor_pago, created_at")\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()

        cotas_list = cotas_result.data or []

        # Buscar nomes dos boloes em uma unica query
        bolao_ids = list(set(c["bolao_id"] for c in cotas_list if c.get("bolao_id")))
        bolao_nomes = {}
        if bolao_ids:
            boloes_result = supabase.table("boloes").select("id, nome").in_("id", bolao_ids).execute()
            for b in (boloes_result.data or []):
                bolao_nomes[b["id"]] = b["nome"]

        for cota in cotas_list:
            bolao_nome = bolao_nomes.get(cota["bolao_id"], "Bolao")

            atividades.append({
                "tipo": "compra_cota",
                "descricao": f'Compra de cota no "{bolao_nome}"',
                "valor": float(cota.get("valor_pago", 0)),
                "usuario_id": cota["usuario_id"],
                "data": cota["created_at"],
            })

        # Ultimos pagamentos
        pagamentos_result = supabase.table("pagamentos_pix")\
            .select("id, usuario_id, valor, status, created_at")\
            .order("created_at", desc=True)\
            .limit(5)\
            .execute()

        for pag in (pagamentos_result.data or []):
            status_texto = {
                "aprovado": "aprovado",
                "pendente": "pendente",
                "recusado": "recusado",
            }.get(pag.get("status", ""), pag.get("status", ""))

            atividades.append({
                "tipo": "pagamento",
                "descricao": f"Pagamento Pix {status_texto} de R$ {float(pag.get('valor', 0)):.2f}",
                "valor": float(pag.get("valor", 0)),
                "usuario_id": pag["usuario_id"],
                "data": pag["created_at"],
            })

        # Ordenar por data (mais recentes primeiro)
        atividades.sort(key=lambda x: x.get("data", ""), reverse=True)

        return atividades[:15]

    except Exception as e:
        logger.error(f"Erro ao buscar atividade recente: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar atividade recente: {str(e)}"
        )
