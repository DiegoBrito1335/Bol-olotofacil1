"""
Rotas administrativas para gerenciar bolões
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from typing import List, Optional
from datetime import datetime
import io

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
        # Calcular cotas vendidas a partir dos dados do bolão
        cotas_vendidas = bolao["total_cotas"] - bolao.get("cotas_disponiveis", bolao["total_cotas"])

        # Calcular campos
        cotas_disponiveis = bolao.get("cotas_disponiveis", bolao["total_cotas"])
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
    bolao_data: BolaoCreateAdmin,
    admin_id: str = Depends(get_admin_user),
):
    """
    Cria um novo bolão (admin).
    """

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
        "tipo": bolao_data.tipo,
        "data_fechamento": bolao_data.data_fechamento.isoformat() if bolao_data.data_fechamento else None,
        "criador_id": admin_id,
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
    
    # Se bolão já foi apurado, só permite alterar o status
    if bolao_atual["status"] == "apurado":
        if bolao_data.status is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não é possível editar um bolão já apurado (apenas mudança de status é permitida)"
            )
        # Verificar se está tentando alterar algo além do status
        campos_alterados = {k for k, v in bolao_data.model_dump(exclude_none=True).items() if k != "status"}
        if campos_alterados:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Bolão apurado: apenas mudança de status é permitida"
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
        # Calcular cotas vendidas a partir dos dados do bolão (não contar registros da tabela cotas,
        # pois cada compra cria 1 registro independente da quantidade de cotas compradas)
        cotas_vendidas = bolao_atual["total_cotas"] - bolao_atual["cotas_disponiveis"]

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

    if bolao_data.tipo is not None:
        update_dict["tipo"] = bolao_data.tipo

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
    
    # Calcular cotas vendidas a partir dos dados do bolão
    cotas_vendidas = bolao_atualizado["total_cotas"] - bolao_atualizado["cotas_disponiveis"]

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
    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data
    cotas_vendidas = bolao["total_cotas"] - bolao.get("cotas_disponiveis", bolao["total_cotas"])

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
    existing = supabase.table("boloes").select("id, status, tipo").eq("id", bolao_id).execute()

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

    # Validar dezenas baseado no tipo do bolão
    tipo = bolao.get("tipo") or "lotofacil"
    if tipo == "megasena":
        min_nums, max_nums, max_val = 6, 20, 60
        label = "Mega-Sena (6-20 números de 1-60)"
    else:
        min_nums, max_nums, max_val = 15, 18, 25
        label = "Lotofácil (15-18 números de 1-25)"

    for jogo in data.jogos:
        if not (min_nums <= len(jogo.dezenas) <= max_nums):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label}: quantidade inválida ({len(jogo.dezenas)} números)"
            )
        fora = [d for d in jogo.dezenas if d < 1 or d > max_val]
        if fora:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{label}: números fora do range 1-{max_val}: {fora}"
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


@router.post("/{bolao_id}/jogos/upload-csv", status_code=status.HTTP_201_CREATED)
async def upload_jogos_csv(bolao_id: str, file: UploadFile = File(...)):
    """
    Importa jogos em massa via arquivo CSV.
    Formato: um jogo por linha, 15 números separados por vírgula ou ponto-e-vírgula.
    """
    # Verificar bolão
    existing = supabase.table("boloes").select("id, status, tipo").eq("id", bolao_id).execute()

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

    # Configurar validação baseada no tipo do bolão
    tipo_bolao = bolao.get("tipo") or "lotofacil"
    if tipo_bolao == "megasena":
        csv_min, csv_max, csv_max_val = 6, 20, 60
    else:
        csv_min, csv_max, csv_max_val = 15, 18, 25

    # Ler conteúdo do arquivo (limite: 5MB)
    content = await file.read()
    if len(content) > 5_000_000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Arquivo muito grande. Limite máximo: 5MB."
        )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Não foi possível ler o arquivo. Use codificação UTF-8 ou Latin-1."
            )

    linhas = text.strip().splitlines()
    if not linhas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo vazio"
        )

    # Detectar separador na primeira linha com números
    separador = ";"  if ";" in linhas[0] else ","

    jogos_validos = []
    erros = []

    for i, linha in enumerate(linhas, start=1):
        linha = linha.strip()
        if not linha:
            continue

        # Remove aspas externas que Excel adiciona ao exportar CSV
        # ex: """01;04;09;25;27;29""" → 01;04;09;25;27;29
        linha = linha.strip('"')

        partes = [p.strip().strip('"') for p in linha.split(separador)]

        # Fallback: se resultou em 1 parte com espaços, separar por whitespace
        # (planilhas que exportam números separados por espaço em uma célula)
        if len(partes) == 1 and ' ' in partes[0]:
            partes = partes[0].split()

        # Verificar se é header (primeira linha com texto não-numérico)
        if i == 1:
            tem_texto = any(not p.replace("-", "").isdigit() for p in partes if p)
            if tem_texto:
                continue

        # Parsear números
        numeros = []
        erro_linha = False
        for p in partes:
            if not p:
                continue
            try:
                n = int(p)
                numeros.append(n)
            except ValueError:
                erros.append(f"Linha {i}: valor não numérico '{p}'")
                erro_linha = True
                break

        if erro_linha:
            continue

        # Validações (baseado no tipo do bolão)
        if not (csv_min <= len(numeros) <= csv_max):
            erros.append(f"Linha {i}: {len(numeros)} números (esperado entre {csv_min} e {csv_max})")
            continue

        fora_range = [n for n in numeros if n < 1 or n > csv_max_val]
        if fora_range:
            erros.append(f"Linha {i}: números fora do range 1-{csv_max_val}: {fora_range}")
            continue

        if len(set(numeros)) != len(numeros):
            erros.append(f"Linha {i}: números duplicados")
            continue

        jogos_validos.append(sorted(numeros))

    if not jogos_validos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nenhum jogo válido encontrado. Erros: {'; '.join(erros) if erros else 'arquivo sem dados'}"
        )

    # Batch insert
    jogos_insert = [
        {"bolao_id": bolao_id, "dezenas": dezenas}
        for dezenas in jogos_validos
    ]

    result = supabase.table("jogos_bolao").insert(jogos_insert).execute()

    if result.error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao inserir jogos: {result.error}"
        )

    return {
        "total_importados": len(jogos_validos),
        "erros": erros,
    }


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

    # Validar quantidade de dezenas baseado no tipo
    tipo = bolao.get("tipo") or "lotofacil"
    esperado = 6 if tipo == "megasena" else 15
    max_val = 60 if tipo == "megasena" else 25
    if len(resultado.dezenas) != esperado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Resultado deve ter exatamente {esperado} números para {tipo}"
        )
    fora = [d for d in resultado.dezenas if d < 1 or d > max_val]
    if fora:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Números fora do range 1-{max_val}: {fora}"
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
        resultado_apuracao = await ResultadoService.apurar_concurso(bolao_id, resultado.concurso_numero, resultado.dezenas, tipo=tipo)

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
    tipo = bolao.get("tipo") or "lotofacil"
    resultado_dezenas = await ResultadoService.buscar_resultado_api(concurso, tipo)

    if not resultado_dezenas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resultado do concurso {concurso} ainda não disponível na API"
        )

    resultado_apuracao = await ResultadoService.apurar_bolao(bolao_id, resultado_dezenas)
    return resultado_apuracao


@router.post("/{bolao_id}/apurar/concurso/{concurso_numero}")
async def apurar_concurso_individual(bolao_id: str, concurso_numero: int):
    """
    Apura um concurso específico de um bolão teimosinha via API.
    Busca resultado + premiações e distribui prêmio automaticamente.
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
            detail="Este bolão já foi totalmente apurado"
        )

    # Verificar se tem jogos
    jogos_result = supabase.table("jogos_bolao").select("id").eq("bolao_id", bolao_id).execute()
    if not jogos_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este bolão não possui jogos cadastrados"
        )

    # Validar concurso no range do bolão
    if BolaoService.is_teimosinha(bolao):
        concursos = BolaoService.concursos_list(bolao)
        if concurso_numero not in concursos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Concurso {concurso_numero} não pertence a este bolão (range: {concursos[0]}-{concursos[-1]})"
            )
    else:
        if concurso_numero != bolao["concurso_numero"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Este bolão é do concurso {bolao['concurso_numero']}"
            )

    # Verificar se já foi apurado
    ja_apurado = supabase.table("resultados_concurso")\
        .select("id")\
        .eq("bolao_id", bolao_id)\
        .eq("concurso_numero", concurso_numero)\
        .execute()

    if ja_apurado.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Concurso {concurso_numero} já foi apurado"
        )

    # Buscar resultado completo (dezenas + premiações)
    tipo = bolao.get("tipo") or "lotofacil"
    resultado_completo = await ResultadoService.buscar_resultado_completo(concurso_numero, tipo)
    if not resultado_completo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Resultado do concurso {concurso_numero} ainda não disponível na API"
        )

    # Apurar
    resultado = await ResultadoService.apurar_concurso(
        bolao_id, concurso_numero,
        resultado_completo["dezenas"],
        resultado_completo.get("premiacoes", {}),
        tipo,
    )

    # Verificar se todos foram apurados
    if BolaoService.is_teimosinha(bolao):
        total = BolaoService.total_concursos(bolao)
        bolao_atualizado = supabase.table("boloes").select("concursos_apurados").eq("id", bolao_id).execute()
        apurados = bolao_atualizado.data[0]["concursos_apurados"] if bolao_atualizado.data else 0
        if apurados >= total:
            supabase.table("boloes").update({"status": "apurado"}).eq("id", bolao_id).execute()

    return resultado


@router.post("/{bolao_id}/apurar/pendentes")
async def apurar_pendentes(bolao_id: str):
    """
    Apura todos os concursos pendentes de um bolão.
    Usado pelo auto-check ao abrir a página e pelo cron.
    """
    existing = supabase.table("boloes").select("*").eq("id", bolao_id).execute()

    if not existing.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bolão não encontrado"
        )

    bolao = existing.data[0] if isinstance(existing.data, list) else existing.data

    if bolao["status"] == "apurado":
        return {
            "bolao_id": bolao_id,
            "mensagem": "Bolão já está totalmente apurado",
            "novos_apurados": 0,
        }

    # Verificar se tem jogos
    jogos_result = supabase.table("jogos_bolao").select("id").eq("bolao_id", bolao_id).execute()
    if not jogos_result.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este bolão não possui jogos cadastrados"
        )

    resultado = await ResultadoService.apurar_pendentes(bolao_id)
    return resultado


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

    # Buscar premiações
    premiacoes_result = supabase.table("premiacoes_bolao")\
        .select("concurso_numero, premio_total, distribuido")\
        .eq("bolao_id", bolao_id)\
        .execute()
    premiacoes_map = {}
    for p in (premiacoes_result.data or []):
        premiacoes_map[p["concurso_numero"]] = {
            "premio_total": float(p["premio_total"]),
            "distribuido": p["distribuido"],
        }

    status_concursos = [
        {
            "concurso_numero": c,
            "apurado": c in concursos_apurados,
            "premio_total": premiacoes_map.get(c, {}).get("premio_total", 0),
            "distribuido": premiacoes_map.get(c, {}).get("distribuido", False),
        }
        for c in concursos
    ]

    premio_total_geral = sum(p.get("premio_total", 0) for p in premiacoes_map.values())

    return {
        "teimosinha": True,
        "concurso_numero": bolao["concurso_numero"],
        "concurso_fim": bolao["concurso_fim"],
        "total_concursos": len(concursos),
        "concursos_apurados": len(concursos_apurados),
        "premio_total_geral": round(premio_total_geral, 2),
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
    tipo_bolao = bolao.get("tipo") or "lotofacil"
    cfg = ResultadoService._config_loteria(tipo_bolao)
    min_acertos_premio = cfg['min_acertos_premio']
    resumo_keys = cfg['resumo_keys']

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
        resumo_geral = {k: 0 for k in resumo_keys}

        for res in resultados:
            concurso = res["concurso_numero"]
            acertos_concurso = acertos_por_concurso.get(concurso, [])

            jogos_resultado = []
            resumo = {k: 0 for k in resumo_keys}

            for jogo in jogos:
                acerto = next((a for a in acertos_concurso if a["jogo_id"] == jogo["id"]), None)
                acertos_val = acerto["acertos"] if acerto else 0
                jogos_resultado.append({
                    "jogo_id": jogo["id"],
                    "dezenas": jogo["dezenas"],
                    "acertos": acertos_val,
                })
                if acertos_val >= min_acertos_premio:
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

    # Concurso único — buscar dezenas de resultados_concurso
    res_concurso = supabase.table("resultados_concurso")\
        .select("dezenas")\
        .eq("bolao_id", bolao_id)\
        .eq("concurso_numero", bolao["concurso_numero"])\
        .execute()

    if not res_concurso.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Este bolão ainda não foi apurado"
        )

    resultado_dezenas = res_concurso.data[0]["dezenas"]

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

    resumo = {k: 0 for k in resumo_keys}
    for j in jogos_resultado:
        if j["acertos"] >= min_acertos_premio:
            resumo[j["acertos"]] = resumo.get(j["acertos"], 0) + 1

    return {
        "bolao_id": bolao_id,
        "teimosinha": False,
        "concurso_numero": bolao["concurso_numero"],
        "resultado_dezenas": resultado_dezenas,
        "jogos_resultado": jogos_resultado,
        "resumo": resumo,
    }


@router.post("/{bolao_id}/redistribuir-premio/{concurso_numero}")
async def redistribuir_premio(
    bolao_id: str,
    concurso_numero: int,
    admin_id: str = Depends(get_admin_user),
):
    """
    Re-credita o prêmio de um concurso já apurado nas carteiras dos participantes.
    Usar quando o crédito automático falhou (ex: apurado com código antigo sem admin key).
    ATENÇÃO: sem idempotência — chamar apenas UMA VEZ por bolão/concurso.
    """
    # 1. Verificar premiacoes_bolao
    prem = supabase.table("premiacoes_bolao")\
        .select("premio_total")\
        .eq("bolao_id", bolao_id)\
        .eq("concurso_numero", concurso_numero)\
        .execute()
    if not prem.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Premiação não encontrada para este bolão/concurso")
    premio_total = float(prem.data[0]["premio_total"])
    if premio_total <= 0:
        return {"detail": "Prêmio zero, nada a redistribuir"}

    # 2. Buscar dados do bolão
    bolao_r = supabase.table("boloes")\
        .select("nome, valor_cota, total_cotas, criador_id")\
        .eq("id", bolao_id)\
        .execute()
    if not bolao_r.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bolão não encontrado")
    b = bolao_r.data[0]
    valor_cota = float(b["valor_cota"])
    total_cotas = int(b["total_cotas"])
    criador_id = b.get("criador_id")
    bolao_nome = b["nome"]

    # 3. Buscar e agrupar cotas vendidas por usuário
    cotas_r = supabase.table("cotas")\
        .select("usuario_id, valor_pago")\
        .eq("bolao_id", bolao_id)\
        .execute()
    cotas_por_usuario: dict = {}
    for c in (cotas_r.data or []):
        uid = c["usuario_id"]
        qtd = max(1, round(float(c["valor_pago"]) / valor_cota)) if valor_cota > 0 else 1
        cotas_por_usuario[uid] = cotas_por_usuario.get(uid, 0) + qtd
    total_vendidas = sum(cotas_por_usuario.values())
    if total_cotas == 0:
        total_cotas = total_vendidas

    creditados: list = []
    ja_creditados: list = []
    erros: list = []

    # 4. Creditar compradores proporcionalmente
    for uid, qtd in cotas_por_usuario.items():
        valor = round((qtd / total_cotas) * premio_total, 2)
        if valor <= 0:
            continue
        desc = f"Prêmio {bolao_nome} - Concurso {concurso_numero} ({qtd} cota{'s' if qtd > 1 else ''})"
        # Idempotência: verificar se já foi creditado para este concurso
        existing = supabase.table("transacoes")\
            .select("id")\
            .eq("usuario_id", uid)\
            .eq("origem", "premiacao")\
            .like_("descricao", f"%Concurso {concurso_numero}%")\
            .limit(1)\
            .execute()
        if existing.data:
            ja_creditados.append({"usuario_id": uid, "valor": valor})
            continue
        r = supabase.rpc("creditar_carteira", {
            "p_usuario_id": uid,
            "p_valor": valor,
            "p_origem": "premiacao",
            "p_referencia_id": bolao_id,
            "p_descricao": desc,
        }).execute()
        if r.error:
            erros.append({"usuario_id": uid, "valor": valor, "erro": str(r.error)})
        else:
            creditados.append({"usuario_id": uid, "valor": valor})

    # 5. Creditar criador pelas cotas não vendidas
    nao_vendidas = total_cotas - total_vendidas
    if nao_vendidas > 0 and criador_id:
        valor_criador = round((nao_vendidas / total_cotas) * premio_total, 2)
        if valor_criador > 0:
            desc_c = f"Prêmio (criador) {bolao_nome} - Concurso {concurso_numero} ({nao_vendidas} cotas não vendidas)"
            existing_c = supabase.table("transacoes")\
                .select("id")\
                .eq("usuario_id", criador_id)\
                .eq("origem", "premiacao")\
                .like_("descricao", f"%Concurso {concurso_numero}%")\
                .limit(1)\
                .execute()
            if existing_c.data:
                ja_creditados.append({"usuario_id": criador_id, "valor": valor_criador, "tipo": "criador"})
            else:
                r = supabase.rpc("creditar_carteira", {
                    "p_usuario_id": criador_id,
                    "p_valor": valor_criador,
                    "p_origem": "premiacao",
                    "p_referencia_id": bolao_id,
                    "p_descricao": desc_c,
                }).execute()
                if r.error:
                    erros.append({"usuario_id": criador_id, "valor": valor_criador, "tipo": "criador", "erro": str(r.error)})
                else:
                    creditados.append({"usuario_id": criador_id, "valor": valor_criador, "tipo": "criador"})

    return {
        "premio_total": premio_total,
        "total_cotas": total_cotas,
        "total_vendidas": total_vendidas,
        "creditados": creditados,
        "ja_creditados": ja_creditados,
        "erros": erros,
    }
