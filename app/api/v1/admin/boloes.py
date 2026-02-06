"""
Rotas administrativas para gerenciar bolões
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Optional
from datetime import datetime

from app.core.supabase import supabase_admin as supabase
from app.schemas.bolao import BolaoResponse
from app.schemas.admin import BolaoCreateAdmin, BolaoUpdateAdmin, JogosCreateBatchAdmin, ResultadoInput
from app.services.resultado_service import ResultadoService
from app.services.bolao_service import BolaoService
from app.api.deps import get_admin_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_user)])

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
        "concurso_fim": bolao_data.concurso_fim,
        "concursos_apurados": 0,
        "total_cotas": bolao_data.total_cotas,
        "cotas_disponiveis": bolao_data.total_cotas,  # Inicialmente todas disponíveis
        "valor_cota": float(bolao_data.valor_cota),
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

    if bolao_data.concurso_fim is not None:
        update_dict["concurso_fim"] = bolao_data.concurso_fim

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
        update_dict["valor_cota"] = float(bolao_data.valor_cota)
    
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


# ===================================
# GERENCIAR JOGOS DO BOLÃO
# ===================================

@router.post("/{bolao_id}/jogos", status_code=status.HTTP_201_CREATED)
async def adicionar_jogos(bolao_id: str, data: JogosCreateBatchAdmin):
    """
    Adiciona um ou mais jogos (dezenas) a um bolão.
    """
    # Verificar se bolão existe
    existing = supabase.table("boloes").select("id, status").eq("id", bolao_id).execute()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data

    if bolao["status"] == "apurado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível adicionar jogos a um bolão já apurado"
        )

    # Preparar dados para inserção batch
    jogos_insert = [
        {"bolao_id": bolao_id, "dezenas": jogo.dezenas}
        for jogo in data.jogos
    ]

    result = supabase.table("jogos_bolao").insert(jogos_insert).execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao adicionar jogos: {result.error}"
        )

    return result.data or []


@router.delete("/{bolao_id}/jogos/{jogo_id}")
async def remover_jogo(bolao_id: str, jogo_id: str):
    """
    Remove um jogo específico de um bolão.
    """
    # Verificar se bolão existe e não está apurado
    existing = supabase.table("boloes").select("id, status").eq("id", bolao_id).execute()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data

    if bolao["status"] == "apurado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível remover jogos de um bolão já apurado"
        )

    result = supabase.table("jogos_bolao")\
        .delete()\
        .eq("id", jogo_id)\
        .eq("bolao_id", bolao_id)\
        .execute()

    return {"mensagem": "Jogo removido com sucesso", "jogo_id": jogo_id}


# ===================================
# APURAÇÃO DE RESULTADOS
# ===================================

@router.post("/{bolao_id}/apurar")
async def apurar_bolao_manual(bolao_id: str, resultado: ResultadoInput):
    """
    Apuração manual — admin informa os 15 números sorteados.
    Para teimosinha, informar concurso_numero no body.
    """
    # Verificar bolão
    existing = supabase.table("boloes").select("*").eq("id", bolao_id).execute()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data

    if bolao["status"] == "apurado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este bolão já foi apurado"
        )

    # Verificar se tem jogos
    jogos_result = supabase.table("jogos_bolao").select("id").eq("bolao_id", bolao_id).execute()
    if not jogos_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este bolão não possui jogos cadastrados"
        )

    # Teimosinha: apurar concurso específico
    if BolaoService.is_teimosinha(bolao):
        if not resultado.concurso_numero:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Para teimosinha, informe o concurso_numero no body"
            )
        concursos = BolaoService.concursos_list(bolao)
        if resultado.concurso_numero not in concursos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Concurso {resultado.concurso_numero} não pertence a este bolão (range: {concursos[0]}-{concursos[-1]})"
            )
        resultado_apuracao = await ResultadoService.apurar_concurso(bolao_id, resultado.concurso_numero, resultado.dezenas)

        # Verificar se todos foram apurados
        total = BolaoService.total_concursos(bolao)
        bolao_atualizado = supabase.table("boloes").select("concursos_apurados").eq("id", bolao_id).execute()
        apurados = bolao_atualizado.data[0]["concursos_apurados"] if bolao_atualizado.data else 0
        if apurados >= total:
            supabase.table("boloes").update({"status": "apurado"}).eq("id", bolao_id).execute()

        return resultado_apuracao

    # Concurso único: apuração normal
    resultado_apuracao = await ResultadoService.apurar_bolao(bolao_id, resultado.dezenas)
    return resultado_apuracao


@router.post("/{bolao_id}/apurar/automatico")
async def apurar_bolao_automatico(bolao_id: str):
    """
    Apuração automática — busca resultado da API da Lotofácil.
    Para teimosinha, apura todos os concursos de uma vez.
    """
    # Verificar bolão
    existing = supabase.table("boloes").select("*").eq("id", bolao_id).execute()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data

    if bolao["status"] == "apurado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este bolão já foi apurado"
        )

    # Verificar se tem jogos
    jogos_result = supabase.table("jogos_bolao").select("id").eq("bolao_id", bolao_id).execute()
    if not jogos_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este bolão não possui jogos cadastrados"
        )

    # Teimosinha: apurar todos os concursos
    if BolaoService.is_teimosinha(bolao):
        resultado = await ResultadoService.apurar_todos_concursos(bolao_id)
        if resultado.get("erros"):
            logger.warning(f"Erros na apuração teimosinha: {resultado['erros']}")
        return resultado

    # Concurso único: apuração normal
    concurso = bolao["concurso_numero"]
    resultado_dezenas = await ResultadoService.buscar_resultado_api(concurso)

    if not resultado_dezenas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resultado do concurso {concurso} ainda não disponível na API"
        )

    resultado_apuracao = await ResultadoService.apurar_bolao(bolao_id, resultado_dezenas)
    return resultado_apuracao


@router.get("/{bolao_id}/apuracao/status")
async def status_apuracao(bolao_id: str):
    """
    Retorna o status da apuração de um bolão teimosinha.
    """
    bolao_result = supabase.table("boloes").select("*").eq("id", bolao_id).execute()

    if not bolao_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = bolao_result.data[0]

    if not BolaoService.is_teimosinha(bolao):
        return {
            "teimosinha": False,
            "concurso_numero": bolao["concurso_numero"],
            "apurado": bolao["status"] == "apurado",
        }

    concursos = BolaoService.concursos_list(bolao)

    # Buscar concursos já apurados
    apurados_result = supabase.table("resultados_concurso")\
        .select("concurso_numero")\
        .eq("bolao_id", bolao_id)\
        .execute()
    concursos_apurados = {r["concurso_numero"] for r in (apurados_result.data or [])}

    status_concursos = [
        {"concurso_numero": c, "apurado": c in concursos_apurados}
        for c in concursos
    ]

    return {
        "teimosinha": True,
        "concurso_numero": bolao["concurso_numero"],
        "concurso_fim": bolao["concurso_fim"],
        "total_concursos": len(concursos),
        "concursos_apurados": len(concursos_apurados),
        "concursos": status_concursos,
    }


@router.get("/{bolao_id}/resultado")
async def ver_resultado(bolao_id: str):
    """
    Retorna o resultado da apuração de um bolão.
    Para teimosinha, retorna resultados agrupados por concurso.
    """
    # Buscar bolão
    bolao_result = supabase.table("boloes").select("*").eq("id", bolao_id).execute()

    if not bolao_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = bolao_result.data[0] if isinstance(bolao_result.data, list) else bolao_result.data

    # Teimosinha: resultado por concurso
    if BolaoService.is_teimosinha(bolao):
        resultados = await ResultadoService.get_resultados_teimosinha(bolao_id)
        if not resultados:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Este bolão ainda não possui concursos apurados"
            )

        # Buscar jogos
        jogos_result = supabase.table("jogos_bolao").select("*").eq("bolao_id", bolao_id).execute()
        jogos = jogos_result.data or []

        # Buscar acertos por concurso
        acertos_data = await ResultadoService.get_acertos_por_concurso(bolao_id)
        # Agrupar por concurso_numero
        acertos_por_concurso = {}
        for a in acertos_data:
            c = a["concurso_numero"]
            if c not in acertos_por_concurso:
                acertos_por_concurso[c] = []
            acertos_por_concurso[c].append(a)

        resultados_formatados = []
        resumo_geral = {15: 0, 14: 0, 13: 0, 12: 0, 11: 0}

        for res in resultados:
            concurso = res["concurso_numero"]
            acertos_concurso = acertos_por_concurso.get(concurso, [])

            jogos_resultado = []
            resumo = {15: 0, 14: 0, 13: 0, 12: 0, 11: 0}

            for jogo in jogos:
                acerto = next((a for a in acertos_concurso if a["jogo_id"] == jogo["id"]), None)
                acertos_val = acerto["acertos"] if acerto else 0
                jogos_resultado.append({
                    "jogo_id": jogo["id"],
                    "dezenas": jogo["dezenas"],
                    "acertos": acertos_val,
                })
                if acertos_val >= 11:
                    resumo[acertos_val] = resumo.get(acertos_val, 0) + 1
                    resumo_geral[acertos_val] = resumo_geral.get(acertos_val, 0) + 1

            resultados_formatados.append({
                "concurso_numero": concurso,
                "dezenas": res["dezenas"],
                "jogos_resultado": jogos_resultado,
                "resumo": resumo,
            })

        return {
            "bolao_id": bolao_id,
            "teimosinha": True,
            "concurso_numero": bolao["concurso_numero"],
            "concurso_fim": bolao["concurso_fim"],
            "resultados": resultados_formatados,
            "resumo_geral": resumo_geral,
        }

    # Concurso único: resultado normal
    if not bolao.get("resultado_dezenas"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este bolão ainda não foi apurado"
        )

    jogos_result = supabase.table("jogos_bolao")\
        .select("*")\
        .eq("bolao_id", bolao_id)\
        .execute()

    jogos = jogos_result.data or []

    jogos_resultado = [
        {
            "jogo_id": j["id"],
            "dezenas": j["dezenas"],
            "acertos": j.get("acertos", 0),
        }
        for j in jogos
    ]

    resumo = {15: 0, 14: 0, 13: 0, 12: 0, 11: 0}
    for j in jogos_resultado:
        if j["acertos"] >= 11:
            resumo[j["acertos"]] = resumo.get(j["acertos"], 0) + 1

    return {
        "bolao_id": bolao_id,
        "teimosinha": False,
        "concurso_numero": bolao["concurso_numero"],
        "resultado_dezenas": bolao["resultado_dezenas"],
        "jogos_resultado": jogos_resultado,
        "resumo": resumo,
    }


# ===================================
# MIGRAÇÃO DO BANCO
# ===================================

@router.post("/migrate/add-columns", tags=["Admin - Migração"])
async def migrate_add_columns():
    """
    Adiciona colunas necessárias para apuração.
    Executar uma vez. Seguro para rodar múltiplas vezes (IF NOT EXISTS).
    """
    from app.config import settings
    import httpx

    sql = """
    ALTER TABLE boloes ADD COLUMN IF NOT EXISTS resultado_dezenas integer[] DEFAULT NULL;
    ALTER TABLE jogos_bolao ADD COLUMN IF NOT EXISTS acertos integer DEFAULT NULL;
    """

    # Executar via Supabase SQL endpoint (REST)
    url = f"{settings.SUPABASE_URL}/rest/v1/rpc/exec_sql"
    headers = {
        "apikey": settings.SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {settings.SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
    }

    # Tentar via RPC primeiro
    try:
        response = httpx.post(url, json={"query": sql}, headers=headers, timeout=15.0)
        if response.status_code in (200, 201):
            return {"mensagem": "Migração executada com sucesso via RPC"}
    except Exception:
        pass

    # Fallback: executar via SQL direto no endpoint do Supabase
    sql_url = f"{settings.SUPABASE_URL}/rest/v1/rpc/"
    try:
        # Tentar adicionar colunas individualmente usando o Supabase Management API
        # Se RPC não funcionar, as colunas precisam ser adicionadas manualmente
        return {
            "mensagem": "RPC não disponível. Execute o SQL manualmente no Supabase Dashboard",
            "sql": sql.strip(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro na migração: {str(e)}"
        )
