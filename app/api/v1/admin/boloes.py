"""
Rotas administrativas para gerenciar bolões
"""

from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from datetime import datetime

from app.core.supabase import supabase_admin as supabase
from app.schemas.bolao import BolaoResponse
from app.schemas.admin import BolaoCreateAdmin, BolaoUpdateAdmin

router = APIRouter(prefix="/admin/boloes", tags=["Admin - Bolões"])

# ===================================

# ===================================
# LISTAR TODOS OS BOLÕES (ADMIN)
# ===================================

@router.get("", response_model=List[BolaoResponse])
async def listar_todos_boloes(
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
):
    """
    Lista todos os bolões (admin).
    
    Filtros opcionais:
    - status_filter: aberto, fechado, apurado, cancelado
    - skip/limit: paginação
    """
    
    # Montar query
    query = supabase.table("boloes").select("*")
    
    if status_filter:
        query = query.eq("status", status_filter)
    
    # Ordenar por data de criação (mais recentes primeiro)
    query = query.order("created_at", desc=True)
    
    # Paginação
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
    
    # Calcular campos adicionais para cada bolão
    boloes_response = []
    for bolao in result.data:
        # Buscar cotas vendidas
        cotas_result = supabase.table("cotas").select("id").eq("bolao_id", bolao["id"]).execute()
        cotas_vendidas = len(cotas_result.data) if cotas_result.data else 0
        
        # Calcular campos
        cotas_disponiveis = bolao["total_cotas"] - cotas_vendidas
        receita_total = cotas_vendidas * bolao["valor_cota"]
        percentual_vendido = (cotas_vendidas / bolao["total_cotas"]) * 100 if bolao["total_cotas"] > 0 else 0
        
        boloes_response.append({
            **bolao,
            "cotas_vendidas": cotas_vendidas,
            "cotas_disponiveis": cotas_disponiveis,
            "receita_total": round(receita_total, 2),
            "percentual_vendido": round(percentual_vendido, 2)
        })
    
    return boloes_response

# ===================================
# CRIAR NOVO BOLÃO (ADMIN)
# ===================================

@router.post("", response_model=BolaoResponse, status_code=status.HTTP_201_CREATED)
async def criar_bolao(
    bolao_data: BolaoCreateAdmin
):
    """
    Cria um novo bolão (admin).
    """
    
    # Verificar se já existe bolão com mesmo concurso e status aberto
    existing = supabase.table("boloes")\
        .select("id")\
        .eq("concurso_numero", bolao_data.concurso_numero)\
        .eq("status", "aberto")\
        .execute()
    
    if existing.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao verificar bolão existente: {existing.error}"
        )
    
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Já existe um bolão aberto para o concurso {bolao_data.concurso_numero}"
        )
    
    # Preparar dados
    bolao_dict = {
        "nome": bolao_data.nome,
        "descricao": bolao_data.descricao,
        "concurso_numero": bolao_data.concurso_numero,
        "total_cotas": bolao_data.total_cotas,
        "cotas_disponiveis": bolao_data.total_cotas,  # Inicialmente todas disponíveis
        "valor_cota": bolao_data.valor_cota,
        "status": bolao_data.status,
        "data_fechamento": bolao_data.data_fechamento.isoformat() if bolao_data.data_fechamento else None
    }
    
    # Inserir no banco
    result = supabase.table("boloes").insert(bolao_dict).execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar bolão: {result.error}"
        )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao criar bolão - nenhum dado retornado"
        )
    
    bolao_criado = result.data[0] if isinstance(result.data, list) else result.data
    
    # Retornar com campos calculados
    return {
        **bolao_criado,
        "cotas_vendidas": 0,
        "receita_total": 0.0,
        "percentual_vendido": 0.0
    }

# ===================================
# ATUALIZAR BOLÃO (ADMIN)
# ===================================

@router.put("/{bolao_id}", response_model=BolaoResponse)
async def atualizar_bolao(
    bolao_id: str,
    bolao_data: BolaoUpdateAdmin,
):
    """
    Atualiza um bolão existente (admin).
    """
    
    # Verificar se bolão existe
    existing = supabase.table("boloes").select("*").eq("id", bolao_id).execute()
    
    if existing.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar bolão: {existing.error}"
        )
    
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )
    
    bolao_atual = existing.data[0] if isinstance(existing.data, list) else existing.data
    
    # Verificar se bolão já foi apurado (não pode editar)
    if bolao_atual["status"] == "apurado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível editar um bolão já apurado"
        )
    
    # Preparar dados para atualização (apenas campos fornecidos)
    update_dict = {}
    
    if bolao_data.nome is not None:
        update_dict["nome"] = bolao_data.nome
    
    if bolao_data.descricao is not None:
        update_dict["descricao"] = bolao_data.descricao
    
    if bolao_data.concurso_numero is not None:
        update_dict["concurso_numero"] = bolao_data.concurso_numero
    
    if bolao_data.total_cotas is not None:
        # Verificar se não tem mais cotas vendidas do que o novo total
        cotas_result = supabase.table("cotas").select("id").eq("bolao_id", bolao_id).execute()
        cotas_vendidas = len(cotas_result.data) if cotas_result.data else 0
        
        if bolao_data.total_cotas < cotas_vendidas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Não é possível reduzir o total de cotas para menos que as já vendidas ({cotas_vendidas})"
            )
        
        update_dict["total_cotas"] = bolao_data.total_cotas
        update_dict["cotas_disponiveis"] = bolao_data.total_cotas - cotas_vendidas
    
    if bolao_data.valor_cota is not None:
        update_dict["valor_cota"] = bolao_data.valor_cota
    
    if bolao_data.data_fechamento is not None:
        update_dict["data_fechamento"] = bolao_data.data_fechamento.isoformat()
    
    if bolao_data.status is not None:
        update_dict["status"] = bolao_data.status
    
    if not update_dict:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum campo para atualizar"
        )
    
    # Atualizar no banco
    result = supabase.table("boloes").update(update_dict).eq("id", bolao_id).execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar bolão: {result.error}"
        )
    
    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Erro ao atualizar bolão - nenhum dado retornado"
        )
    
    bolao_atualizado = result.data[0] if isinstance(result.data, list) else result.data
    
    # Buscar cotas vendidas para cálculos
    cotas_result = supabase.table("cotas").select("id").eq("bolao_id", bolao_id).execute()
    cotas_vendidas = len(cotas_result.data) if cotas_result.data else 0
    
    # Calcular campos
    receita_total = cotas_vendidas * bolao_atualizado["valor_cota"]
    percentual_vendido = (cotas_vendidas / bolao_atualizado["total_cotas"]) * 100 if bolao_atualizado["total_cotas"] > 0 else 0
    
    return {
        **bolao_atualizado,
        "cotas_vendidas": cotas_vendidas,
        "cotas_disponiveis": bolao_atualizado["cotas_disponiveis"],
        "receita_total": round(receita_total, 2),
        "percentual_vendido": round(percentual_vendido, 2)
    }

# ===================================
# FECHAR BOLÃO (ADMIN)
# ===================================

@router.patch("/{bolao_id}/close")
async def fechar_bolao(
    bolao_id: str,
):
    """
    Fecha um bolão, impedindo novas compras de cotas.
    """
    
    # Verificar se bolão existe
    existing = supabase.table("boloes").select("*").eq("id", bolao_id).execute()
    
    if existing.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar bolão: {existing.error}"
        )
    
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )
    
    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data
    
    # Verificar se já está fechado ou apurado
    if bolao["status"] in ["fechado", "apurado"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bolão já está {bolao['status']}"
        )
    
    # Fechar o bolão
    result = supabase.table("boloes")\
        .update({"status": "fechado"})\
        .eq("id", bolao_id)\
        .execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao fechar bolão: {result.error}"
        )
    
    return {
        "mensagem": "Bolão fechado com sucesso",
        "bolao_id": bolao_id,
        "status": "fechado"
    }

# ===================================
# DELETAR BOLÃO (ADMIN)
# ===================================

@router.delete("/{bolao_id}")
async def deletar_bolao(
    bolao_id: str,
):
    """
    Deleta um bolão (admin).
    ATENÇÃO: Só pode deletar bolões sem cotas vendidas!
    """
    
    # Verificar se bolão existe
    existing = supabase.table("boloes").select("*").eq("id", bolao_id).execute()
    
    if existing.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar bolão: {existing.error}"
        )
    
    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )
    
    # Verificar se tem cotas vendidas
    cotas_result = supabase.table("cotas").select("id").eq("bolao_id", bolao_id).execute()
    cotas_vendidas = len(cotas_result.data) if cotas_result.data else 0
    
    if cotas_vendidas > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não é possível deletar um bolão com cotas já vendidas ({cotas_vendidas} cotas)"
        )
    
    # Deletar jogos primeiro (se existirem)
    supabase.table("jogos_bolao").delete().eq("bolao_id", bolao_id).execute()
    
    # Deletar o bolão
    result = supabase.table("boloes").delete().eq("id", bolao_id).execute()
    
    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao deletar bolão: {result.error}"
        )
    
    return {
        "mensagem": "Bolão deletado com sucesso",
        "bolao_id": bolao_id
    }
