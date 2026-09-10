"""Cliente fino pra API pública da GeckoTerminal (api.geckoterminal.com/api/v2)
-- sem API key, usada pra pools de Robinhood Chain e Solana, que o The Graph
não indexa (ver CLAUDE.md, seção "Robinhood Chain e Solana via GeckoTerminal").

Rate limit real confirmado ao vivo em 2026-09-10: ~30 req/min sem
autenticação. **Achado real**: um limitador de "até N por janela de 60s"
(rajada de até 25 chamadas de uma vez, depois espera) ainda tomou 429 num
crawl de verdade (`_crawl_geckoterminal`, ~10-20 chamadas em sequência) --
o limite parece se importar com o ESPAÇAMENTO entre chamadas, não só a
contagem por minuto (rajada rápida estoura mesmo abaixo de 30/min). Por
isso `_throttle()` foi trocado pra um intervalo mínimo fixo entre chamadas
consecutivas (`_MIN_INTERVAL_SECONDS`), em vez de contar uma janela --
mais devagar, mas não estoura em rajada. Estado compartilhado a nível de
módulo (mesmo padrão que `usage_tracker.py` já usa pro contador do Graph,
só que aqui é um limitador). `_get` também tenta de novo (com espera) uma
vez se ainda assim tomar 429, já que um crawl inteiro abortar por causa de
UM 429 transitório é pior que perder alguns segundos.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

_BASE_URL = "https://api.geckoterminal.com/api/v2"
# Achado real em 2026-09-10: uma única visualização de página de pool já
# chama `get_pool`/`get_ohlcv` várias vezes de forma redundante (detalhe do
# pool, /indicators, /history/daily e /history/hourly cada um busca o
# fee_tier e/ou o OHLCV de novo, de forma independente) -- isso sozinho já
# bastou pra estourar o rate limit numa única carga de página, causando um
# 404 "Pool não encontrado" enganoso (era rate limit, não pool inexistente).
# Cache de TTL curto (o suficiente pra cobrir as poucas chamadas de UMA
# carga de página, curto o bastante pra não deixar preço/TVL visivelmente
# desatualizado) resolve isso sem precisar re-arquitetar quem chama o quê.
_CACHE_TTL_SECONDS = 20.0
_cache: dict[str, tuple[float, Any]] = {}
_cache_lock = asyncio.Lock()


async def _cached(key: str, fetch: Callable[[], Awaitable[Any]]) -> Any:
    async with _cache_lock:
        cached = _cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    result = await fetch()
    async with _cache_lock:
        _cache[key] = (time.monotonic(), result)
    return result
# Achado real em 2026-09-10: mesmo com espaçamento de 2,5s (~24 req/min),
# uma sequência de ~10 chamadas com `include=base_token,quote_token` ainda
# tomou 429 no meio do caminho -- o custo real por chamada parece maior que
# "1 unidade" quando `include` está presente (ou o limite é mais rígido do
# que 30/min sugere). 4s (~15 req/min sustentado) é bem mais conservador;
# ver também o tratamento de erro parcial em index_builder._crawl_geckoterminal,
# que aceita o que já foi buscado em vez de descartar tudo se isso acontecer
# de novo mesmo assim.
_MIN_INTERVAL_SECONDS = 4.0
_RETRY_WAIT_SECONDS = 8.0

_lock = asyncio.Lock()
_last_request_at = 0.0


class GeckoTerminalError(RuntimeError):
    pass


async def _throttle() -> None:
    global _last_request_at
    async with _lock:
        now = time.monotonic()
        wait = _last_request_at + _MIN_INTERVAL_SECONDS - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    for attempt in range(2):
        await _throttle()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{_BASE_URL}{path}", params=params)
                if response.status_code == 429:
                    if attempt == 0:
                        await asyncio.sleep(_RETRY_WAIT_SECONDS)
                        continue
                    raise GeckoTerminalError("Limite de requisições da GeckoTerminal atingido (429).")
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise GeckoTerminalError(f"Erro de rede ao consultar a GeckoTerminal: {exc}") from exc
    raise GeckoTerminalError("Limite de requisições da GeckoTerminal atingido (429).")


def _token_lookup(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{token_id: attributes} a partir do array "included" (formato
    JSON:API) -- devolvido junto com "data" quando a chamada pede
    `include=base_token,quote_token`, pra resolver token0/token1 de cada
    pool sem uma chamada extra por pool."""
    return {t["id"]: t["attributes"] for t in payload.get("included", [])}


async def search_pools(network: str, query: str) -> tuple[list[dict[str, Any]], dict[str, dict]]:
    """Busca por termo livre (símbolo ou nome do token/pool) -- não tem
    filtro estruturado tipo `symbol_in`/par de tokens, só texto livre.
    Retorna (pools, token_lookup)."""
    data = await _get(
        "/search/pools", {"query": query, "network": network, "include": "base_token,quote_token"}
    )
    return data.get("data", []), _token_lookup(data)


async def list_pools(network: str, page: int = 1) -> tuple[list[dict[str, Any]], dict[str, dict]]:
    """Estado atual dos pools de uma network, paginado (~20 por página) --
    já vem com TVL/volume-24h prontos, sem custo extra de OHLCV por pool.
    Usado pelo crawl do índice local (ver index_builder.py). Retorna
    (pools, token_lookup)."""
    data = await _get(f"/networks/{network}/pools", {"page": page, "include": "base_token,quote_token"})
    return data.get("data", []), _token_lookup(data)


async def get_pool(network: str, address: str) -> tuple[dict[str, Any], dict[str, dict]] | None:
    """`None` só quando o pool de verdade não existe (a API responde sem
    "data") -- erros de rede/rate limit PROPAGAM como `GeckoTerminalError`
    em vez de virar `None` aqui. Achado real: isso já foi confundido com
    "pool não encontrado" (404 enganoso) quando na verdade era rate limit --
    quem chama decide como tratar uma falha de verdade, não fica escondida
    atrás do mesmo `None` que significa "não existe"."""

    async def _fetch() -> dict[str, Any]:
        return await _get(f"/networks/{network}/pools/{address}", {"include": "base_token,quote_token"})

    data = await _cached(f"pool:{network}:{address}", _fetch)
    result = data.get("data")
    if result is None:
        return None
    return result, _token_lookup(data)


async def get_ohlcv(network: str, address: str, timeframe: str, limit: int = 30) -> list[list[float]]:
    """`timeframe` é "day" ou "hour". Retorna uma lista de
    `[timestamp, open, high, low, close, volume]`, mais recente primeiro
    (mesma ordem que a API devolve)."""

    async def _fetch() -> dict[str, Any]:
        return await _get(f"/networks/{network}/pools/{address}/ohlcv/{timeframe}", {"limit": limit})

    data = await _cached(f"ohlcv:{network}:{address}:{timeframe}:{limit}", _fetch)
    return data.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
