"""
Serviço de apuração de resultados da Lotofácil
"""

from typing import List, Optional, Dict, Any
from app.core.supabase import supabase_admin as supabase
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
