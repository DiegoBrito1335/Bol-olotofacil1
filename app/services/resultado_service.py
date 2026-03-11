"""
Serviço de apuração de resultados da Lotofácil
"""

from typing import List, Optional, Dict, Any
from app.core.supabase import supabase_admin as supabase
from app.services.bolao_service import BolaoService
import httpx
import logging

logger = logging.getLogger(__name__)


class ResultadoService:

    # APIs Lotofácil em ordem de preferência
    _APIS = [
        {
            "url": "https://servicebus2.caixa.gov.br/portaldeloterias/api/lotofacil/{concurso}",
            "campo_dezenas": "listaDezenas",
            "campo_premiacoes": "listaRateioPremio",
            "campo_valor": "valorPremio",
        },
        {
            "url": "https://loteriascaixa-api.herokuapp.com/api/lotofacil/{concurso}",
            "campo_dezenas": "dezenas",
            "campo_premiacoes": "premiacoes",
            "campo_valor": "valorPremio",
        },
    ]
    # APIs Mega-Sena em ordem de preferência
    _APIS_MEGASENA = [
        {
            "url": "https://servicebus2.caixa.gov.br/portaldeloterias/api/megasena/{concurso}",
            "campo_dezenas": "listaDezenas",
            "campo_premiacoes": "listaRateioPremio",
            "campo_valor": "valorPremio",
        },
        {
            "url": "https://loteriascaixa-api.herokuapp.com/api/megasena/{concurso}",
            "campo_dezenas": "dezenas",
            "campo_premiacoes": "premiacoes",
            "campo_valor": "valorPremio",
        },
    ]
    _HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BolaoBot/1.0)"}

    @staticmethod
    def _get_apis(tipo: str) -> list:
        if tipo == 'megasena':
            return ResultadoService._APIS_MEGASENA
        return ResultadoService._APIS

    @staticmethod
    def _config_loteria(tipo: str) -> dict:
        """Retorna configurações específicas de cada loteria."""
        if tipo == 'megasena':
            return {
                'total_dezenas': 6,
                'min_acertos_premio': 4,
                'faixa_offset': 7,   # acertos = 7 - faixa (faixa1=Sena=6ac, faixa3=Quadra=4ac)
                'resumo_keys': [6, 5, 4, 3, 2, 1, 0],
            }
        return {
            'total_dezenas': 15,
            'min_acertos_premio': 11,
            'faixa_offset': 16,  # acertos = 16 - faixa (faixa1=15ac, faixa5=11ac)
            'resumo_keys': [15, 14, 13, 12, 11],
        }

    @staticmethod
    async def buscar_resultado_api(concurso_numero: int, tipo: str = 'lotofacil') -> Optional[List[int]]:
        """
        Busca resultado da loteria via API pública.
        Suporta 'lotofacil' e 'megasena'.
        Retorna lista ordenada de inteiros, ou None se ambas as APIs falharem.
        """
        config = ResultadoService._config_loteria(tipo)
        total_dezenas = config['total_dezenas']
        async with httpx.AsyncClient() as client:
            for api in ResultadoService._get_apis(tipo):
                url = api["url"].format(concurso=concurso_numero)
                campo = api["campo_dezenas"]
                try:
                    response = await client.get(url, timeout=30.0, headers=ResultadoService._HEADERS)
                    if response.status_code == 200:
                        data = response.json()
                        dezenas = [int(d) for d in data.get(campo, [])]
                        if len(dezenas) == total_dezenas:
                            logger.info(f"Resultado do concurso {concurso_numero} ({tipo}) obtido via {url}")
                            return sorted(dezenas)
                        logger.warning(f"API {url} retornou {len(dezenas)} dezenas para concurso {concurso_numero}")
                    else:
                        logger.warning(f"API {url} retornou status {response.status_code}")
                except Exception as e:
                    logger.warning(f"Falha na API {url}: {e}")
        logger.error(f"Todas as APIs falharam para concurso {concurso_numero} ({tipo})")
        return None

    @staticmethod
    async def buscar_resultado_completo(concurso_numero: int, tipo: str = 'lotofacil') -> Optional[Dict[str, Any]]:
        """
        Busca resultado completo via API pública (dezenas + premiações).
        Suporta 'lotofacil' e 'megasena'.
        Retorna {dezenas: [...], premiacoes: {N_acertos: valor, ...}} ou None.
        """
        config = ResultadoService._config_loteria(tipo)
        total_dezenas = config['total_dezenas']
        faixa_offset = config['faixa_offset']
        min_acertos = config['min_acertos_premio']
        async with httpx.AsyncClient() as client:
            for api in ResultadoService._get_apis(tipo):
                url = api["url"].format(concurso=concurso_numero)
                campo_dezenas = api["campo_dezenas"]
                campo_premiacoes = api["campo_premiacoes"]
                try:
                    response = await client.get(url, timeout=30.0, headers=ResultadoService._HEADERS)
                    if response.status_code != 200:
                        logger.warning(f"API {url} retornou status {response.status_code}")
                        continue

                    data = response.json()
                    dezenas = [int(d) for d in data.get(campo_dezenas, [])]
                    if len(dezenas) != total_dezenas:
                        logger.warning(f"API {url} retornou {len(dezenas)} dezenas para concurso {concurso_numero}")
                        continue

                    # Extrair premiações por faixa de acertos
                    campo_valor = api.get("campo_valor", "valorPremio")
                    premiacoes_raw = data.get(campo_premiacoes, [])
                    premiacoes = {}
                    for p in premiacoes_raw:
                        faixa = p.get("faixa", 0)
                        valor = p.get(campo_valor, 0)
                        acertos = faixa_offset - faixa
                        if min_acertos <= acertos <= total_dezenas:
                            try:
                                premiacoes[acertos] = float(str(valor).replace(",", ".")) if valor else 0.0
                            except (ValueError, TypeError):
                                premiacoes[acertos] = 0.0

                    logger.info(f"Resultado completo do concurso {concurso_numero} ({tipo}) obtido via {url}")
                    return {
                        "dezenas": sorted(dezenas),
                        "premiacoes": premiacoes,
                    }
                except Exception as e:
                    logger.warning(f"Falha na API {url}: {e}")

        logger.error(f"Todas as APIs falharam para concurso {concurso_numero} ({tipo})")
        return None

    @staticmethod
    def calcular_acertos(jogo_dezenas: List[int], resultado_dezenas: List[int]) -> int:
        """Calcula quantos números o jogo acertou."""
        return len(set(jogo_dezenas) & set(resultado_dezenas))

    # ===================================
    # DISTRIBUIÇÃO DE PRÊMIOS
    # ===================================

    @staticmethod
    async def calcular_e_distribuir_premio(
        bolao_id: str,
        concurso_numero: int,
        premiacoes: Dict[int, float],
        jogos_resultado: List[Dict[str, Any]],
        tipo: str = 'lotofacil',
    ) -> float:
        """
        Calcula e distribui prêmios para os participantes do bolão.

        1. Para cada jogo com acertos >= min_acertos_premio, soma o premio da faixa
        2. Divide o total proporcionalmente pelas cotas vendidas
        3. Credita na carteira de cada participante

        Retorna o premio_total distribuído.
        """
        config = ResultadoService._config_loteria(tipo)
        min_acertos = config['min_acertos_premio']
        # Calcular prêmio total do bolão neste concurso
        premio_total = 0.0
        for jogo in jogos_resultado:
            acertos = jogo["acertos"]
            if acertos >= min_acertos and acertos in premiacoes:
                premio_total += premiacoes[acertos]

        if premio_total <= 0:
            # Se há jogos premiáveis mas premio=0 → API ainda não atualizou os valores
            # Salvar registro com premio_total=0 para rastrear (retry automático tenta novamente)
            prem_zero = supabase.table("premiacoes_bolao").select("id")\
                .eq("bolao_id", bolao_id).eq("concurso_numero", concurso_numero).execute()
            if not prem_zero.data:
                supabase.table("premiacoes_bolao").insert({
                    "bolao_id": bolao_id,
                    "concurso_numero": concurso_numero,
                    "premio_total": 0,
                }).execute()
            return 0.0

        # Buscar dados do bolão (nome, valor_cota, total_cotas e criador_id)
        bolao_result = supabase.table("boloes").select("nome, valor_cota, total_cotas, criador_id").eq("id", bolao_id).execute()
        bolao_nome = bolao_result.data[0]["nome"] if bolao_result.data else "Bolão"
        valor_cota = float(bolao_result.data[0]["valor_cota"]) if bolao_result.data else 0
        total_cotas_bolao = int(bolao_result.data[0]["total_cotas"]) if bolao_result.data else 0
        criador_id = bolao_result.data[0].get("criador_id") if bolao_result.data else None

        # Buscar cotas vendidas com valor_pago
        cotas_result = supabase.table("cotas")\
            .select("usuario_id, valor_pago")\
            .eq("bolao_id", bolao_id)\
            .execute()

        cotas = cotas_result.data or []

        # Contar cotas REAIS por usuário (valor_pago / valor_cota)
        cotas_por_usuario: Dict[str, int] = {}
        for cota in cotas:
            uid = cota["usuario_id"]
            if valor_cota > 0:
                qtd = max(1, round(float(cota["valor_pago"]) / valor_cota))
            else:
                qtd = 1
            cotas_por_usuario[uid] = cotas_por_usuario.get(uid, 0) + qtd

        total_cotas_vendidas = sum(cotas_por_usuario.values())

        # Usar total_cotas do bolão como denominador (cotas não vendidas pertencem ao criador)
        total_cotas = total_cotas_bolao if total_cotas_bolao > 0 else total_cotas_vendidas

        # Validação antifraude: cotas vendidas não podem exceder o total
        if total_cotas_vendidas > total_cotas:
            logger.warning(
                f"Bolão {bolao_id}: cotas vendidas ({total_cotas_vendidas}) > total ({total_cotas}) "
                f"— usando total_cotas como base para divisão"
            )

        if total_cotas == 0:
            logger.warning(f"Bolão {bolao_id} sem cotas para distribuir prêmio")
            supabase.table("premiacoes_bolao").insert({
                "bolao_id": bolao_id,
                "concurso_numero": concurso_numero,
                "premio_total": round(premio_total, 2),
            }).execute()
            return premio_total

        # Montar lista unificada: compradores + criador (cotas não vendidas)
        cotas_nao_vendidas = total_cotas - total_cotas_vendidas
        todos_participantes = []
        for uid, qtd in cotas_por_usuario.items():
            todos_participantes.append({
                "usuario_id": uid, "qtd_cotas": qtd, "tipo": "comprador", "origem": "premiacao"
            })
        if cotas_nao_vendidas > 0 and criador_id:
            todos_participantes.append({
                "usuario_id": criador_id, "qtd_cotas": cotas_nao_vendidas,
                "tipo": "criador", "origem": "premiacao_criador"
            })

        # Calcular valor por cota e distribuir proporcionalmente
        # O último participante recebe o resto para garantir soma exata = premio_total (anti-arredondamento)
        valor_por_cota = round(premio_total / total_cotas, 10)  # alta precisão interna
        soma_ate_agora = 0.0
        for i, p in enumerate(todos_participantes):
            if i == len(todos_participantes) - 1:
                p["valor"] = round(premio_total - soma_ate_agora, 2)
            else:
                p["valor"] = round(p["qtd_cotas"] * valor_por_cota, 2)
                soma_ate_agora += p["valor"]

        # Verificação antifraude: soma deve ser igual ao prêmio total
        soma_total = sum(p["valor"] for p in todos_participantes)
        if abs(soma_total - premio_total) > 0.01:
            logger.error(
                f"ANTIFRAUDE: soma distribuída R$ {soma_total:.2f} ≠ prêmio R$ {premio_total:.2f} "
                f"— bolão {bolao_id} concurso {concurso_numero}"
            )
        else:
            logger.info(
                f"Verificação OK: R$ {soma_total:.2f} = prêmio R$ {premio_total:.2f} "
                f"| valor_por_cota=R$ {premio_total/total_cotas:.4f} | {len(todos_participantes)} participante(s)"
            )

        # Creditar cada participante
        has_errors = False
        for p in todos_participantes:
            usuario_id = p["usuario_id"]
            valor = p["valor"]
            origem = p["origem"]
            qtd_cotas = p["qtd_cotas"]

            if valor <= 0:
                continue

            # Idempotência: verificar se já foi distribuído para este usuário/concurso
            existing = supabase.table("distribuicao_premios")\
                .select("id")\
                .eq("bolao_id", bolao_id)\
                .eq("concurso_numero", concurso_numero)\
                .eq("usuario_id", usuario_id)\
                .limit(1).execute()
            if existing.data:
                logger.info(f"Distribuição concurso {concurso_numero} já registrada para {usuario_id} — pulando")
                continue

            # Garantir que carteira existe antes de creditar
            carteira_check = supabase.table("carteira").select("id").eq("usuario_id", usuario_id).execute()
            if not carteira_check.data:
                supabase.table("carteira").insert({
                    "usuario_id": usuario_id, "saldo_disponivel": 0, "saldo_bloqueado": 0
                }).execute()

            # Descrição da transação
            if p["tipo"] == "criador":
                descricao = f"Prêmio (criador) {bolao_nome} - Concurso {concurso_numero} ({qtd_cotas} cotas não vendidas)"
            else:
                descricao = f"Prêmio {bolao_nome} - Concurso {concurso_numero} ({qtd_cotas} cota{'s' if qtd_cotas > 1 else ''})"

            # Creditar via RPC atômico (UPDATE carteira + INSERT transacao em uma transação SQL)
            rpc_result = supabase.rpc("creditar_carteira", {
                "p_usuario_id": usuario_id,
                "p_valor": valor,
                "p_origem": origem,
                "p_referencia_id": bolao_id,
                "p_descricao": descricao,
            }).execute()

            if rpc_result.error:
                logger.error(f"Erro no RPC creditar_carteira para {usuario_id} ({origem}): {rpc_result.error}")
                has_errors = True
            else:
                logger.info(f"Prêmio R$ {valor} creditado para {usuario_id} ({origem}, concurso {concurso_numero})")
                # Registrar distribuição para auditoria e idempotência
                supabase.table("distribuicao_premios").insert({
                    "bolao_id": bolao_id,
                    "usuario_id": usuario_id,
                    "concurso_numero": concurso_numero,
                    "qtd_cotas": qtd_cotas,
                    "valor_por_cota": round(valor_por_cota, 4),
                    "valor_recebido": valor,
                    "origem": origem,
                }).execute()

        # Registrar premiação — sempre salvar o valor calculado.
        if has_errors:
            logger.warning(f"Créditos com falha no bolão {bolao_id} concurso {concurso_numero} — use redistribuir-premio para retentar")
        prem_check = supabase.table("premiacoes_bolao").select("id")\
            .eq("bolao_id", bolao_id).eq("concurso_numero", concurso_numero).execute()
        premio_a_salvar = round(premio_total, 2)
        prem_update = {"premio_total": premio_a_salvar}
        if not has_errors:
            prem_update["distribuido"] = True
        if prem_check.data:
            supabase.table("premiacoes_bolao")\
                .update(prem_update)\
                .eq("bolao_id", bolao_id).eq("concurso_numero", concurso_numero).execute()
        else:
            supabase.table("premiacoes_bolao").insert({
                "bolao_id": bolao_id,
                "concurso_numero": concurso_numero,
                "premio_total": premio_a_salvar,
                "distribuido": not has_errors,
            }).execute()

        logger.info(f"Prêmio total R$ {premio_total:.2f} distribuído para bolão {bolao_id} concurso {concurso_numero}")
        return premio_total

    # ===================================
    # APURAÇÃO CONCURSO ÚNICO
    # ===================================

    @staticmethod
    async def apurar_bolao(bolao_id: str, resultado_dezenas: List[int]) -> Dict[str, Any]:
        """
        Realiza a apuração de um bolão (concurso único):
        1. Busca todos os jogos do bolão
        2. Calcula acertos de cada jogo
        3. Atualiza cada jogo com o número de acertos
        4. Salva resultado_dezenas no bolão e muda status para "apurado"
        5. Distribui prêmio se houver
        6. Retorna resumo
        """
        # A2 — Verificar se o bolão já foi apurado antes de prosseguir (lock otimista)
        bolao_check = supabase.table("boloes").select("status").eq("id", bolao_id).execute()
        if bolao_check.data and bolao_check.data[0].get("status") == "apurado":
            logger.warning(f"Bolão {bolao_id} já está apurado — ignorando apuração duplicada")
            return {
                "bolao_id": bolao_id,
                "resultado_dezenas": resultado_dezenas,
                "jogos_resultado": [],
                "resumo": {},
                "skipped": True,
            }

        # Buscar jogos do bolão
        jogos_result = supabase.table("jogos_bolao")\
            .select("*")\
            .eq("bolao_id", bolao_id)\
            .execute()

        jogos = jogos_result.data or []

        if not jogos:
            return {
                "bolao_id": bolao_id,
                "resultado_dezenas": resultado_dezenas,
                "jogos_resultado": [],
                "resumo": {},
            }

        # Buscar concurso_numero e tipo do bolão
        bolao_result = supabase.table("boloes")\
            .select("concurso_numero, tipo")\
            .eq("id", bolao_id)\
            .execute()
        concurso = bolao_result.data[0]["concurso_numero"] if bolao_result.data else 0
        tipo = (bolao_result.data[0].get("tipo") or 'lotofacil') if bolao_result.data else 'lotofacil'
        config = ResultadoService._config_loteria(tipo)
        min_acertos = config['min_acertos_premio']

        # Calcular acertos e atualizar cada jogo
        jogos_resultado = []
        resumo: Dict[int, int] = {k: 0 for k in config['resumo_keys']}

        for jogo in jogos:
            acertos = ResultadoService.calcular_acertos(
                jogo["dezenas"], resultado_dezenas
            )

            # Atualizar acertos no banco
            supabase.table("jogos_bolao")\
                .update({"acertos": acertos})\
                .eq("id", jogo["id"])\
                .execute()

            jogos_resultado.append({
                "jogo_id": jogo["id"],
                "dezenas": jogo["dezenas"],
                "acertos": acertos,
            })

            if acertos in resumo:
                resumo[acertos] += 1

        # Atualizar bolão com status apurado
        supabase.table("boloes")\
            .update({"status": "apurado"})\
            .eq("id", bolao_id)\
            .execute()

        # Inserir em resultados_concurso (consistência com apurar_concurso)
        supabase.table("resultados_concurso").insert({
            "bolao_id": bolao_id,
            "concurso_numero": concurso,
            "dezenas": resultado_dezenas,
        }).execute()

        # Batch insert de acertos por jogo em acertos_concurso (1 request em vez de N)
        if jogos_resultado:
            supabase.table("acertos_concurso").insert([
                {
                    "jogo_id": jogo_res["jogo_id"],
                    "bolao_id": bolao_id,
                    "concurso_numero": concurso,
                    "acertos": jogo_res["acertos"],
                }
                for jogo_res in jogos_resultado
            ]).execute()

        # Buscar premiação e distribuir (sempre chamar, mesmo com premiacoes={})
        resultado_completo = await ResultadoService.buscar_resultado_completo(concurso, tipo)
        premiacoes_api = resultado_completo.get("premiacoes", {}) if resultado_completo else {}
        premio_total = await ResultadoService.calcular_e_distribuir_premio(
            bolao_id, concurso, premiacoes_api, jogos_resultado, tipo
        )

        return {
            "bolao_id": bolao_id,
            "concurso_numero": concurso,
            "resultado_dezenas": resultado_dezenas,
            "jogos_resultado": jogos_resultado,
            "resumo": resumo,
            "premio_total": round(premio_total, 2),
        }

    # ===================================
    # MÉTODOS TEIMOSINHA (MULTI-CONCURSO)
    # ===================================

    @staticmethod
    async def apurar_concurso(bolao_id: str, concurso_numero: int, resultado_dezenas: List[int], premiacoes: Optional[Dict[int, float]] = None, tipo: str = 'lotofacil') -> Dict[str, Any]:
        """
        Apura um concurso específico de um bolão teimosinha:
        1. Busca todos os jogos do bolão
        2. Calcula acertos de cada jogo contra as dezenas deste concurso
        3. Insere em resultados_concurso
        4. Insere em acertos_concurso
        5. Incrementa concursos_apurados no bolão
        6. Distribui prêmio se houver
        """
        # Buscar jogos do bolão
        jogos_result = supabase.table("jogos_bolao")\
            .select("*")\
            .eq("bolao_id", bolao_id)\
            .execute()

        jogos = jogos_result.data or []

        # A2 — Salvar resultado do concurso (lock otimista: falha se já existir)
        resultado_insert = supabase.table("resultados_concurso").insert({
            "bolao_id": bolao_id,
            "concurso_numero": concurso_numero,
            "dezenas": resultado_dezenas,
        }).execute()

        if resultado_insert.error:
            logger.warning(
                f"Concurso {concurso_numero} do bolão {bolao_id} já está sendo apurado "
                f"ou já foi apurado (insert duplicado): {resultado_insert.error}"
            )
            return {
                "concurso_numero": concurso_numero,
                "dezenas": resultado_dezenas,
                "jogos_resultado": [],
                "resumo": {},
                "premio_total": 0.0,
                "skipped": True,
            }

        # Calcular e salvar acertos por jogo
        config = ResultadoService._config_loteria(tipo)
        jogos_resultado = []
        resumo: Dict[int, int] = {k: 0 for k in config['resumo_keys']}

        for jogo in jogos:
            acertos = ResultadoService.calcular_acertos(
                jogo["dezenas"], resultado_dezenas
            )

            jogos_resultado.append({
                "jogo_id": jogo["id"],
                "dezenas": jogo["dezenas"],
                "acertos": acertos,
            })

            if acertos in resumo:
                resumo[acertos] += 1

        # Batch insert de acertos em acertos_concurso (1 request em vez de N)
        if jogos_resultado:
            supabase.table("acertos_concurso").insert([
                {
                    "jogo_id": jogo_res["jogo_id"],
                    "bolao_id": bolao_id,
                    "concurso_numero": concurso_numero,
                    "acertos": jogo_res["acertos"],
                }
                for jogo_res in jogos_resultado
            ]).execute()

        # Incrementar concursos_apurados (com null safety)
        bolao_result = supabase.table("boloes").select("concursos_apurados").eq("id", bolao_id).execute()
        apurados_atual = (bolao_result.data[0].get("concursos_apurados") or 0) if bolao_result.data else 0

        supabase.table("boloes")\
            .update({"concursos_apurados": apurados_atual + 1})\
            .eq("id", bolao_id)\
            .execute()

        # Distribuir prêmio
        premio_total = 0.0
        if premiacoes is None:
            # Buscar premiação da API
            resultado_completo = await ResultadoService.buscar_resultado_completo(concurso_numero, tipo)
            if resultado_completo:
                premiacoes = resultado_completo.get("premiacoes", {})

        if premiacoes:
            premio_total = await ResultadoService.calcular_e_distribuir_premio(
                bolao_id, concurso_numero, premiacoes, jogos_resultado, tipo
            )

        return {
            "concurso_numero": concurso_numero,
            "dezenas": resultado_dezenas,
            "jogos_resultado": jogos_resultado,
            "resumo": resumo,
            "premio_total": round(premio_total, 2),
        }

    @staticmethod
    async def apurar_todos_concursos(bolao_id: str) -> Dict[str, Any]:
        """
        Apura TODOS os concursos de um bolão teimosinha de uma vez.
        Busca resultado de cada concurso na API e apura sequencialmente.
        """
        # Buscar bolão
        bolao_result = supabase.table("boloes").select("*").eq("id", bolao_id).execute()
        if not bolao_result.data:
            return {"error": "Bolão não encontrado"}

        bolao = bolao_result.data[0]
        tipo = bolao.get("tipo") or 'lotofacil'
        concursos = BolaoService.concursos_list(bolao)

        # Verificar quais concursos já foram apurados
        apurados_result = supabase.table("resultados_concurso")\
            .select("concurso_numero")\
            .eq("bolao_id", bolao_id)\
            .execute()
        concursos_ja_apurados = set()
        if apurados_result.data:
            concursos_ja_apurados = {r["concurso_numero"] for r in apurados_result.data}

        # Filtrar apenas concursos pendentes
        concursos_pendentes = [c for c in concursos if c not in concursos_ja_apurados]

        resultados = []
        erros = []
        premio_total_geral = 0.0

        for concurso in concursos_pendentes:
            # Buscar resultado completo da API (com premiações)
            resultado_completo = await ResultadoService.buscar_resultado_completo(concurso, tipo)
            if not resultado_completo:
                erros.append(f"Concurso {concurso}: resultado não disponível")
                continue

            # Apurar este concurso com premiações
            resultado = await ResultadoService.apurar_concurso(
                bolao_id, concurso,
                resultado_completo["dezenas"],
                resultado_completo.get("premiacoes", {}),
                tipo,
            )
            resultados.append(resultado)
            premio_total_geral += resultado.get("premio_total", 0)

        # Verificar se todos os concursos foram apurados (conta diretamente na tabela resultados_concurso)
        total_concursos = BolaoService.total_concursos(bolao)
        apurados_result = supabase.table("resultados_concurso")\
            .select("concurso_numero")\
            .eq("bolao_id", bolao_id)\
            .execute()
        apurados = len(apurados_result.data or [])

        if apurados >= total_concursos:
            # Todos apurados — mudar status para "apurado"
            supabase.table("boloes")\
                .update({"status": "apurado"})\
                .eq("id", bolao_id)\
                .execute()

        # Re-tentar distribuição de prêmios para concursos com premio_total=0
        # (API estava desatualizada no momento da apuração)
        premiacoes_dist = supabase.table("premiacoes_bolao")\
            .select("concurso_numero, premio_total")\
            .eq("bolao_id", bolao_id).execute()
        concursos_ok = {
            r["concurso_numero"] for r in (premiacoes_dist.data or [])
            if float(r.get("premio_total") or 0) > 0
        }
        todos_apurados = {r["concurso_numero"] for r in (apurados_result.data or [])}
        pendentes_premio = sorted(todos_apurados - concursos_ok)

        for concurso in pendentes_premio:
            resultado_completo = await ResultadoService.buscar_resultado_completo(concurso, tipo)
            if not resultado_completo:
                continue
            premiacoes_retry = resultado_completo.get("premiacoes", {})
            if not premiacoes_retry or not any(v > 0 for v in premiacoes_retry.values()):
                continue  # API ainda retorna 0 — tentará na próxima execução

            acertos_res = supabase.table("acertos_concurso")\
                .select("jogo_id, acertos")\
                .eq("bolao_id", bolao_id)\
                .eq("concurso_numero", concurso).execute()
            jogos_retry = [
                {"jogo_id": a["jogo_id"], "dezenas": [], "acertos": a["acertos"]}
                for a in (acertos_res.data or [])
            ]
            if not jogos_retry:
                continue

            premio = await ResultadoService.calcular_e_distribuir_premio(
                bolao_id, concurso, premiacoes_retry, jogos_retry, tipo
            )
            premio_total_geral += premio
            logger.info(f"Prêmio pendente R$ {premio:.2f} re-distribuído para concurso {concurso} do bolão {bolao_id}")

        return {
            "bolao_id": bolao_id,
            "concurso_numero": bolao["concurso_numero"],
            "concurso_fim": bolao.get("concurso_fim"),
            "total_concursos": total_concursos,
            "concursos_apurados": apurados,
            "resultados": resultados,
            "erros": erros,
            "premio_total_geral": round(premio_total_geral, 2),
        }

    @staticmethod
    async def apurar_pendentes(bolao_id: str) -> Dict[str, Any]:
        """
        Apura apenas os concursos pendentes de um bolão.
        Usado pelo auto-check (cron + page load).
        """
        return await ResultadoService.apurar_todos_concursos(bolao_id)

    @staticmethod
    async def get_resultados_teimosinha(bolao_id: str) -> List[Dict]:
        """Retorna todos os resultados por concurso de um bolão teimosinha."""
        result = supabase.table("resultados_concurso")\
            .select("*")\
            .eq("bolao_id", bolao_id)\
            .order("concurso_numero")\
            .execute()
        return result.data or []

    @staticmethod
    async def get_acertos_por_concurso(bolao_id: str) -> List[Dict]:
        """Retorna todos os acertos por jogo por concurso."""
        result = supabase.table("acertos_concurso")\
            .select("*")\
            .eq("bolao_id", bolao_id)\
            .order("concurso_numero")\
            .execute()
        return result.data or []

    @staticmethod
    async def get_premiacoes_bolao(bolao_id: str) -> List[Dict]:
        """Retorna premiações distribuídas por concurso."""
        result = supabase.table("premiacoes_bolao")\
            .select("*")\
            .eq("bolao_id", bolao_id)\
            .order("concurso_numero")\
            .execute()
        return result.data or []
