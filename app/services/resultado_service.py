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
    def calcular_acertos(jogo_dezenas: List[int], resultado_dezenas: List[int]) -> int:
        """Calcula quantos números o jogo acertou."""
        return len(set(jogo_dezenas) & set(resultado_dezenas))

    @staticmethod
    async def apurar_bolao(bolao_id: str, resultado_dezenas: List[int]) -> Dict[str, Any]:
        """
        Realiza a apuração de um bolão:
        1. Busca todos os jogos do bolão
        2. Calcula acertos de cada jogo
        3. Atualiza cada jogo com o número de acertos
        4. Salva resultado_dezenas no bolão e muda status para "apurado"
        5. Retorna resumo
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

        # Atualizar bolão com resultado e status
        supabase.table("boloes")\
            .update({
                "resultado_dezenas": resultado_dezenas,
                "status": "apurado",
            })\
            .eq("id", bolao_id)\
            .execute()

        # Buscar concurso_numero
        bolao_result = supabase.table("boloes")\
            .select("concurso_numero")\
            .eq("id", bolao_id)\
            .execute()
        concurso = bolao_result.data[0]["concurso_numero"] if bolao_result.data else 0

        return {
            "bolao_id": bolao_id,
            "concurso_numero": concurso,
            "resultado_dezenas": resultado_dezenas,
            "jogos_resultado": jogos_resultado,
            "resumo": resumo,
        }

    # ===================================
    # MÉTODOS TEIMOSINHA (MULTI-CONCURSO)
    # ===================================

    @staticmethod
    async def apurar_concurso(bolao_id: str, concurso_numero: int, resultado_dezenas: List[int]) -> Dict[str, Any]:
        """
        Apura um concurso específico de um bolão teimosinha:
        1. Busca todos os jogos do bolão
        2. Calcula acertos de cada jogo contra as dezenas deste concurso
        3. Insere em resultados_concurso
        4. Insere em acertos_concurso
        5. Incrementa concursos_apurados no bolão
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

        # Incrementar concursos_apurados
        bolao_result = supabase.table("boloes").select("concursos_apurados").eq("id", bolao_id).execute()
        apurados_atual = bolao_result.data[0]["concursos_apurados"] if bolao_result.data else 0

        supabase.table("boloes")\
            .update({"concursos_apurados": apurados_atual + 1})\
            .eq("id", bolao_id)\
            .execute()

        return {
            "concurso_numero": concurso_numero,
            "dezenas": resultado_dezenas,
            "jogos_resultado": jogos_resultado,
            "resumo": resumo,
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

        for concurso in concursos_pendentes:
            # Buscar resultado da API
            dezenas = await ResultadoService.buscar_resultado_api(concurso)
            if not dezenas:
                erros.append(f"Concurso {concurso}: resultado não disponível")
                continue

            # Apurar este concurso
            resultado = await ResultadoService.apurar_concurso(bolao_id, concurso, dezenas)
            resultados.append(resultado)

        # Verificar se todos os concursos foram apurados
        total_concursos = BolaoService.total_concursos(bolao)
        bolao_atualizado = supabase.table("boloes").select("concursos_apurados").eq("id", bolao_id).execute()
        apurados = bolao_atualizado.data[0]["concursos_apurados"] if bolao_atualizado.data else 0

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
        }

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
