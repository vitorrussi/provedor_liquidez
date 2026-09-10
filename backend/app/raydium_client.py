"""Cliente fino pra API pública da Raydium (api-v3.raydium.io) -- sem API
key. Usado só como companion da GeckoTerminal pro protocolo `solana`: a
GeckoTerminal não retorna a taxa da pool pra Solana (`pool_fee_percentage`
sempre `null`, confirmado em 2026-09-10 em várias pools reais), mas a
Raydium dá `feeRate` e APR/volume-de-taxa já calculados por dia/semana/mês
pras próprias pools dela. Ver CLAUDE.md.
"""

from __future__ import annotations

import asyncio

import httpx

_BASE_URL = "https://api-v3.raydium.io"
_RETRY_WAIT_SECONDS = 5.0


class RaydiumError(RuntimeError):
    pass


async def get_pool_info(pool_ids: list[str]) -> dict[str, dict]:
    """Retorna um dict {pool_id: raw_pool_info} pros ids encontrados -- ids
    não encontrados na resposta simplesmente não aparecem no dict (a Raydium
    devolve `null` na posição correspondente da lista `data`, não um erro).

    Chamado no máximo com 1 id por vez neste app (companion de fee tier de
    UM pool por vez, ver `_resolve_fee_tier_geckoterminal`), então não tem
    limitador de taxa dedicado como `geckoterminal_client.py` -- só uma
    tentativa extra com espera curta em caso de 429, mesmo espírito do
    retry de lá, já que agora uma falha aqui vira 502 pro usuário em vez de
    virar silenciosamente um APR de 0% (ver CLAUDE.md)."""
    if not pool_ids:
        return {}
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{_BASE_URL}/pools/info/ids", params={"ids": ",".join(pool_ids)}
                )
                if response.status_code == 429:
                    if attempt == 0:
                        await asyncio.sleep(_RETRY_WAIT_SECONDS)
                        continue
                    raise RaydiumError("Limite de requisições da Raydium atingido (429).")
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise RaydiumError(f"Erro de rede ao consultar a Raydium: {exc}") from exc

        if not payload.get("success"):
            raise RaydiumError(f"Resposta da Raydium sem sucesso: {payload}")

        return {p["id"]: p for p in payload.get("data", []) if p is not None}
    raise RaydiumError("Limite de requisições da Raydium atingido (429).")
