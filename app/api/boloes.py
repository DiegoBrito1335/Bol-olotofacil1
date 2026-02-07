"""
Rotas públicas de bolões (para usuários normais)
"""

from fastapi import APIRouter, HTTPException, Depends, status
from typing import List, Optional
from app.core.supabase import supabase_admin as supabase
from app.schemas.bolao import BolaoResponse, JogosResponse
from app.schemas.admin import BolaoCreateAdmin
from app.api.deps import get_current_user_optional

router = APIRouter()

# ===================================
# LISTAR BOLÕES DISPONÍVEIS
# ===================================

@router.get("", response_model=List[BolaoResponse])
async def listar_boloes_disponiveis(
    apenas_abertos: bool = True,
    limit: int = 50
):
    """
    Lista bolões disponíveis (públicos).
    
    Por padrão, mostra apenas bolões abertos.
    """
    
    # Montar query
    query = supabase.table("boloes").select("*")
    
    if apenas_abertos:
        query = query.eq("status", "aberto")
    
    # Ordenar por data de criação (mais recentes primeiro)
    query = query.order("created_at", desc=True)
    
    # Limitar resultados
    if limit:
        query = query.limit(limit)
    
    result = query.execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar bolões: {result.error}"
        )
    
    if not result.data:
        return []
    
    return result.data


# ===================================
# VER DETALHES DE UM BOLÃO
# ===================================

@router.get("/{bolao_id}", response_model=BolaoResponse)
async def ver_detalhes_bolao(bolao_id: str):
    """
    Ver detalhes de um bolão específico.
    """
    
    result = supabase.table("boloes").select("*").eq("id", bolao_id).execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar bolão: {result.error}"
        )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )
    
    bolao = result.data[0] if isinstance(result.data, list) else result.data
    
    return bolao


# ===================================
# VER JOGOS DE UM BOLÃO
# ===================================

@router.get("/{bolao_id}/jogos", response_model=List[JogosResponse])
async def ver_jogos_bolao(bolao_id: str):
    """
    Ver todos os jogos (dezenas) de um bolão.
    """
    
    # Verificar se bolão existe
    bolao_result = supabase.table("boloes").select("id, status").eq("id", bolao_id).execute()
    
    if bolao_result.error or not bolao_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )
    
    # Buscar jogos
    jogos_result = supabase.table("jogos_bolao").select("*").eq("bolao_id", bolao_id).execute()
    
    if jogos_result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar jogos: {jogos_result.error}"
        )
    
    if not jogos_result.data:
        return []
    
    return jogos_result.data


# ===================================
# CRIAR BOLAO (redireciona do frontend)
# ===================================

@router.post("", status_code=status.HTTP_201_CREATED)
async def criar_bolao_via_public(bolao_data: BolaoCreateAdmin):
    """
    Cria um novo bolao.
    Rota acessivel via /api/v1/boloes (POST) para compatibilidade com o frontend.
    """

    # Verificar se ja existe bolao com mesmo concurso aberto
    existing = supabase.table("boloes")\
        .select("id")\
        .eq("concurso_numero", bolao_data.concurso_numero)\
        .eq("status", "aberto")\
        .execute()

    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ja existe um bolao aberto para o concurso {bolao_data.concurso_numero}"
        )

    bolao_dict = {
        "nome": bolao_data.nome,
        "descricao": bolao_data.descricao,
        "concurso_numero": bolao_data.concurso_numero,
        "total_cotas": bolao_data.total_cotas,
        "cotas_disponiveis": bolao_data.total_cotas,
        "valor_cota": float(bolao_data.valor_cota),
        "status": bolao_data.status,
        "data_fechamento": bolao_data.data_fechamento.isoformat() if bolao_data.data_fechamento else None
    }

    result = supabase.table("boloes").insert(bolao_dict).execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar bolao: {result.error}"
        )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar bolao - nenhum dado retornado"
        )

    return result.data[0] if isinstance(result.data, list) else result.data


# ===================================
# VER RESULTADO / PREMIAÇÃO
# ===================================

@router.get("/{bolao_id}/resultado")
async def ver_resultado_publico(bolao_id: str):
    """
    Ver resultado e premiação de um bolão (público).
    Retorna resultado por concurso com prêmio distribuído.
    """
    bolao_result = supabase.table("boloes").select("*").eq("id", bolao_id).execute()

    if not bolao_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = bolao_result.data[0] if isinstance(bolao_result.data, list) else bolao_result.data
    is_teimosinha = bolao.get("concurso_fim") and bolao["concurso_fim"] > bolao["concurso_numero"]

    if is_teimosinha:
        # Buscar resultados por concurso
        resultados_result = supabase.table("resultados_concurso")\
            .select("concurso_numero, dezenas")\
            .eq("bolao_id", bolao_id)\
            .order("concurso_numero")\
            .execute()

        # Buscar premiações
        premiacoes_result = supabase.table("premiacoes_bolao")\
            .select("concurso_numero, premio_total")\
            .eq("bolao_id", bolao_id)\
            .execute()
        premiacoes_map = {p["concurso_numero"]: float(p["premio_total"]) for p in (premiacoes_result.data or [])}

        resultados = []
        for r in (resultados_result.data or []):
            resultados.append({
                "concurso_numero": r["concurso_numero"],
                "dezenas": r["dezenas"],
                "premio_total": premiacoes_map.get(r["concurso_numero"], 0),
            })

        premio_total_geral = sum(premiacoes_map.values())

        return {
            "bolao_id": bolao_id,
            "teimosinha": True,
            "concurso_numero": bolao["concurso_numero"],
            "concurso_fim": bolao["concurso_fim"],
            "total_concursos": bolao["concurso_fim"] - bolao["concurso_numero"] + 1,
            "concursos_apurados": len(resultados),
            "premio_total_geral": round(premio_total_geral, 2),
            "resultados": resultados,
        }

    # Concurso único
    if not bolao.get("resultado_dezenas"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este bolão ainda não foi apurado"
        )

    # Buscar premiação
    premiacoes_result = supabase.table("premiacoes_bolao")\
        .select("premio_total")\
        .eq("bolao_id", bolao_id)\
        .eq("concurso_numero", bolao["concurso_numero"])\
        .execute()
    premio_total = float(premiacoes_result.data[0]["premio_total"]) if premiacoes_result.data else 0

    return {
        "bolao_id": bolao_id,
        "teimosinha": False,
        "concurso_numero": bolao["concurso_numero"],
        "resultado_dezenas": bolao["resultado_dezenas"],
        "premio_total": round(premio_total, 2),
    }


# ===================================
# VERIFICAR DISPONIBILIDADE
# ===================================

@router.get("/{bolao_id}/disponivel")
async def verificar_disponibilidade(bolao_id: str):
    """
    Verifica se um bolão está disponível para compra.
    """
    
    result = supabase.table("boloes").select("id, status, cotas_disponiveis").eq("id", bolao_id).execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao verificar bolão: {result.error}"
        )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )
    
    bolao = result.data[0] if isinstance(result.data, list) else result.data
    
    disponivel = (
        bolao["status"] == "aberto" and 
        bolao["cotas_disponiveis"] > 0
    )
    
    return {
        "bolao_id": bolao_id,
        "disponivel": disponivel,
        "status": bolao["status"],
        "cotas_disponiveis": bolao["cotas_disponiveis"]
    }