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

    @staticmethod
    async def buscar_resultado_api(concurso_numero: int) -> Optional[List[int]]:
        """
        Busca resultado da Lotofácil via API pública.
        Retorna lista ordenada de 15 inteiros, ou None se falhar.
        """
        url = f"https://loteriascaixa-api.herokuapp.com/api/lotofacil/{concurso_numero}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    dezenas = [int(d) for d in data.get("dezenas", [])]
                    if len(dezenas) == 15:
                        return sorted(dezenas)
                    logger.warning(f"API retornou {len(dezenas)} dezenas para concurso {concurso_numero}")
                else:
                    logger.warning(f"API retornou status {response.status_code} para concurso {concurso_numero}")
        except Exception as e:
            logger.error(f"Erro ao buscar resultado do concurso {concurso_numero}: {e}")
        return None

    @staticmethod
    async def buscar_resultado_completo(concurso_numero: int) -> Optional[Dict[str, Any]]:
        """
        Busca resultado completo da Lotofácil via API pública.
        Retorna {dezenas: [...], premiacoes: {11: valor, 12: valor, ...}} ou None.
        """
        url = f"https://loteriascaixa-api.herokuapp.com/api/lotofacil/{concurso_numero}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    dezenas = [int(d) for d in data.get("dezenas", [])]
                    if len(dezenas) != 15:
                        logger.warning(f"API retornou {len(dezenas)} dezenas para concurso {concurso_numero}")
                        return None

                    # Extrair premiações por faixa de acertos
                    premiacoes_raw = data.get("premiacoes", [])
                    premiacoes = {}
                    for p in premiacoes_raw:
                        faixa = p.get("faixa", 0)
                        valor = p.get("valorPremio", 0)
                        # faixa 1 = 15 acertos, faixa 2 = 14 acertos, etc.
                        acertos = 16 - faixa
                        if 11 <= acertos <= 15:
                            premiacoes[acertos] = float(valor) if valor else 0.0

                    return {
                        "dezenas": sorted(dezenas),
                        "premiacoes": premiacoes,
                    }
                else:
                    logger.warning(f"API retornou status {response.status_code} para concurso {concurso_numero}")
        except Exception as e:
            logger.error(f"Erro ao buscar resultado completo do concurso {concurso_numero}: {e}")
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
    ) -> float:
        """
        Calcula e distribui prêmios para os participantes do bolão.

        1. Para cada jogo com >=11 acertos, soma o premio da faixa
        2. Divide o total proporcionalmente pelas cotas vendidas
        3. Credita na carteira de cada participante

        Retorna o premio_total distribuído.
        """
        # Calcular prêmio total do bolão neste concurso
        premio_total = 0.0
        for jogo in jogos_resultado:
            acertos = jogo["acertos"]
            if acertos >= 11 and acertos in premiacoes:
                premio_total += premiacoes[acertos]

        if premio_total <= 0:
            # Registrar premiação zerada
            supabase.table("premiacoes_bolao").insert({
                "bolao_id": bolao_id,
                "concurso_numero": concurso_numero,
                "premio_total": 0,
                "distribuido": True,
            }).execute()
            return 0.0

        # Buscar dados do bolão (nome e valor_cota para calcular quantidade real)
        bolao_result = supabase.table("boloes").select("nome, valor_cota").eq("id", bolao_id).execute()
        bolao_nome = bolao_result.data[0]["nome"] if bolao_result.data else "Bolão"
        valor_cota = float(bolao_result.data[0]["valor_cota"]) if bolao_result.data else 0

        # Buscar cotas vendidas com valor_pago
        cotas_result = supabase.table("cotas")\
            .select("usuario_id, valor_pago")\
            .eq("bolao_id", bolao_id)\
            .execute()

        cotas = cotas_result.data or []
        if not cotas:
            logger.warning(f"Bolão {bolao_id} sem cotas vendidas para distribuir prêmio")
            supabase.table("premiacoes_bolao").insert({
                "bolao_id": bolao_id,
                "concurso_numero": concurso_numero,
                "premio_total": round(premio_total, 2),
                "distribuido": False,
            }).execute()
            return premio_total

        # Contar cotas REAIS por usuário (valor_pago / valor_cota)
        cotas_por_usuario: Dict[str, int] = {}
        for cota in cotas:
            uid = cota["usuario_id"]
            if valor_cota > 0:
                qtd = max(1, round(float(cota["valor_pago"]) / valor_cota))
            else:
                qtd = 1
            cotas_por_usuario[uid] = cotas_por_usuario.get(uid, 0) + qtd

        total_cotas = sum(cotas_por_usuario.values())

        # Distribuir para cada usuário
        for usuario_id, qtd_cotas in cotas_por_usuario.items():
            premio_usuario = round((qtd_cotas / total_cotas) * premio_total, 2)
            if premio_usuario <= 0:
                continue

            # Buscar carteira do usuário
            cart_result = supabase.table("carteira")\
                .select("*")\
                .eq("usuario_id", usuario_id)\
                .execute()

            if not cart_result.data:
                logger.warning(f"Carteira não encontrada para usuário {usuario_id}")
                continue

            carteira = cart_result.data[0]
            saldo_anterior = float(carteira["saldo_disponivel"])
            saldo_posterior = round(saldo_anterior + premio_usuario, 2)

            # Atualizar saldo
            supabase.table("carteira")\
                .update({"saldo_disponivel": saldo_posterior})\
                .eq("usuario_id", usuario_id)\
                .execute()

            # Criar transação
            supabase.table("transacoes").insert({
                "usuario_id": usuario_id,
                "tipo": "credito",
                "valor": premio_usuario,
                "origem": "premio_bolao",
                "referencia_id": bolao_id,
                "descricao": f"Prêmio {bolao_nome} - Concurso {concurso_numero} ({qtd_cotas} cota{'s' if qtd_cotas > 1 else ''})",
                "saldo_anterior": saldo_anterior,
                "saldo_posterior": saldo_posterior,
                "status": "confirmado",
            }).execute()

            logger.info(f"Prêmio R$ {premio_usuario} creditado para usuário {usuario_id} (concurso {concurso_numero})")

        # Registrar premiação
        supabase.table("premiacoes_bolao").insert({
            "bolao_id": bolao_id,
            "concurso_numero": concurso_numero,
            "premio_total": round(premio_total, 2),
            "distribuido": True,
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

        # Calcular acertos e atualizar cada jogo
        jogos_resultado = []
        resumo = {15: 0, 14: 0, 13: 0, 12: 0, 11: 0}

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

            if acertos >= 11:
                resumo[acertos] = resumo.get(acertos, 0) + 1

        # Atualizar bolão com status apurado
        supabase.table("boloes")\
            .update({"status": "apurado"})\
            .eq("id", bolao_id)\
            .execute()

        # Buscar concurso_numero
        bolao_result = supabase.table("boloes")\
            .select("concurso_numero")\
            .eq("id", bolao_id)\
            .execute()
        concurso = bolao_result.data[0]["concurso_numero"] if bolao_result.data else 0

        # Inserir em resultados_concurso (consistência com apurar_concurso)
        supabase.table("resultados_concurso").insert({
            "bolao_id": bolao_id,
            "concurso_numero": concurso,
            "dezenas": resultado_dezenas,
        }).execute()

        # Inserir acertos por jogo em acertos_concurso
        for jogo_res in jogos_resultado:
            supabase.table("acertos_concurso").insert({
                "jogo_id": jogo_res["jogo_id"],
                "bolao_id": bolao_id,
                "concurso_numero": concurso,
                "acertos": jogo_res["acertos"],
            }).execute()

        # Buscar premiação e distribuir
        premio_total = 0.0
        resultado_completo = await ResultadoService.buscar_resultado_completo(concurso)
        if resultado_completo and resultado_completo.get("premiacoes"):
            premio_total = await ResultadoService.calcular_e_distribuir_premio(
                bolao_id, concurso, resultado_completo["premiacoes"], jogos_resultado
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
    async def apurar_concurso(bolao_id: str, concurso_numero: int, resultado_dezenas: List[int], premiacoes: Optional[Dict[int, float]] = None) -> Dict[str, Any]:
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

        # Salvar resultado do concurso
        supabase.table("resultados_concurso").insert({
            "bolao_id": bolao_id,
            "concurso_numero": concurso_numero,
            "dezenas": resultado_dezenas,
        }).execute()

        # Calcular e salvar acertos por jogo
        jogos_resultado = []
        resumo = {15: 0, 14: 0, 13: 0, 12: 0, 11: 0}

        for jogo in jogos:
            acertos = ResultadoService.calcular_acertos(
                jogo["dezenas"], resultado_dezenas
            )

            # Inserir acertos do concurso
            supabase.table("acertos_concurso").insert({
                "jogo_id": jogo["id"],
                "bolao_id": bolao_id,
                "concurso_numero": concurso_numero,
                "acertos": acertos,
            }).execute()

            jogos_resultado.append({
                "jogo_id": jogo["id"],
                "dezenas": jogo["dezenas"],
                "acertos": acertos,
            })

            if acertos >= 11:
                resumo[acertos] = resumo.get(acertos, 0) + 1

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
            resultado_completo = await ResultadoService.buscar_resultado_completo(concurso_numero)
            if resultado_completo:
                premiacoes = resultado_completo.get("premiacoes", {})

        if premiacoes:
            premio_total = await ResultadoService.calcular_e_distribuir_premio(
                bolao_id, concurso_numero, premiacoes, jogos_resultado
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

        if not concursos_pendentes:
            return {
                "bolao_id": bolao_id,
                "mensagem": "Todos os concursos já foram apurados",
                "resultados": [],
            }

        resultados = []
        erros = []
        premio_total_geral = 0.0

        for concurso in concursos_pendentes:
            # Buscar resultado completo da API (com premiações)
            resultado_completo = await ResultadoService.buscar_resultado_completo(concurso)
            if not resultado_completo:
                erros.append(f"Concurso {concurso}: resultado não disponível")
                continue

            # Apurar este concurso com premiações
            resultado = await ResultadoService.apurar_concurso(
                bolao_id, concurso,
                resultado_completo["dezenas"],
                resultado_completo.get("premiacoes", {})
            )
            resultados.append(resultado)
            premio_total_geral += resultado.get("premio_total", 0)

        # Verificar se todos os concursos foram apurados
        total_concursos = BolaoService.total_concursos(bolao)
        bolao_atualizado = supabase.table("boloes").select("concursos_apurados").eq("id", bolao_id).execute()
        apurados = (bolao_atualizado.data[0].get("concursos_apurados") or 0) if bolao_atualizado.data else 0

        if apurados >= total_concursos:
            # Todos apurados — mudar status para "apurado"
            supabase.table("boloes")\
                .update({"status": "apurado"})\
                .eq("id", bolao_id)\
                .execute()

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
