from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .. import graph_client, indicators, onchain_client
from ..config import get_settings
from ..graph_client import GraphQueryError
from ..onchain_client import OnchainQueryError
from ..schemas import DayDataPoint, HourDataPoint, PoolDetail, PoolSummary, Token

# Uniswap v2 é um AMM de produto constante clássico: sem feeTier configurável
# (sempre 0,30%) e sem `feesUSD` indexado no subgraph -- estimamos as taxas
# como volume * essa taxa fixa. Ver docstring de _to_pool_summary_v2.
V2_FEE_TIER = 3000  # unidades de feeTier da v3 (1e-6): 3000 == 0,30%
V2_FEE_RATE = 0.003

# Qual chain cada protocolo vive -- v2/v3/v4 são todos Ethereum mainnet
# (mesmos endereços de token, mesmo RPC de verificação on-chain); Aerodrome
# Slipstream é Base mainnet, uma chain totalmente separada (endereços de
# token diferentes, mesmo pra "o mesmo" token como WETH). Usado para (a)
# escolher o RPC certo em _rpc_url_for_protocol -- usar o RPC errado não dá
# erro, só devolve saldo zerado, então isso importa de verdade -- e (b) não
# misturar protocolos de chains diferentes em get_related_pools (endereços
# nunca vão bater entre chains, então seria só gasto de quota à toa).
_PROTOCOL_CHAIN = {"v2": "mainnet", "v3": "mainnet", "v4": "mainnet", "aerodrome": "base"}


def _rpc_url_for_protocol(protocol: str) -> str:
    settings = get_settings()
    return settings.base_rpc_url if _PROTOCOL_CHAIN[protocol] == "base" else settings.eth_rpc_url

# Timeout mais curto pras 3 buscas em paralelo -- o subgraph v4 foi observado
# respondendo em >20s pra termos comuns ("WETH"); é melhor falhar rápido nesse
# protocolo (e degradar graciosamente, ver search_pools) do que segurar a
# resposta inteira por 20s. Endpoints de detalhe/histórico (1 chamada, não 3
# em paralelo) continuam no timeout padrão de graph_client.run_query.
_SEARCH_TIMEOUT = 10.0

_SEARCH_QUERY = """
query SearchPools($search: String!, $first: Int!) {
  bySymbol0: pools(
    where: { token0_: { symbol_contains_nocase: $search } }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: $first
  ) {
    ...PoolFields
  }
  bySymbol1: pools(
    where: { token1_: { symbol_contains_nocase: $search } }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: $first
  ) {
    ...PoolFields
  }
  byName0: pools(
    where: { token0_: { name_contains_nocase: $search } }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: $first
  ) {
    ...PoolFields
  }
  byName1: pools(
    where: { token1_: { name_contains_nocase: $search } }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: $first
  ) {
    ...PoolFields
  }
}

fragment PoolFields on Pool {
  id
  feeTier
  totalValueLockedUSD
  volumeUSD
  token0 { id symbol name decimals }
  token1 { id symbol name decimals }
}
"""

# Schema do subgraph v2 é mais simples (entidade Pair, sem feeTier/tick/liquidez
# concentrada) -- mesma estrutura de busca (4 aliases + dedupe client-side),
# campos diferentes.
_SEARCH_QUERY_V2 = """
query SearchPairs($search: String!, $first: Int!) {
  bySymbol0: pairs(
    where: { token0_: { symbol_contains_nocase: $search } }
    orderBy: reserveUSD
    orderDirection: desc
    first: $first
  ) {
    ...PairFields
  }
  bySymbol1: pairs(
    where: { token1_: { symbol_contains_nocase: $search } }
    orderBy: reserveUSD
    orderDirection: desc
    first: $first
  ) {
    ...PairFields
  }
  byName0: pairs(
    where: { token0_: { name_contains_nocase: $search } }
    orderBy: reserveUSD
    orderDirection: desc
    first: $first
  ) {
    ...PairFields
  }
  byName1: pairs(
    where: { token1_: { name_contains_nocase: $search } }
    orderBy: reserveUSD
    orderDirection: desc
    first: $first
  ) {
    ...PairFields
  }
}

fragment PairFields on Pair {
  id
  reserveUSD
  volumeUSD
  token0 { id symbol name decimals }
  token1 { id symbol name decimals }
}
"""

_BATCH_DAY_DATA_QUERY = """
query BatchPoolDayData($poolIds: [String!]!, $since: Int!, $first: Int!, $skip: Int!) {
  poolDayDatas(
    where: { pool_in: $poolIds, date_gte: $since }
    orderBy: date
    orderDirection: desc
    first: $first
    skip: $skip
  ) {
    pool { id }
    date
    volumeUSD
    feesUSD
  }
}
"""

# `PairDayData` do v2 não tem relação `pair`, só o endereço cru em `pairAddress`
# (Bytes) -- e não tem `feesUSD` (derivamos de dailyVolumeUSD * V2_FEE_RATE
# depois, em _fetch_recent_day_data_batch). Confirmado por introspecção real
# em 2026-09-09 (PairDayData_filter só tem `date*`/`pairAddress*`).
_BATCH_DAY_DATA_QUERY_V2 = """
query BatchPairDayData($poolIds: [Bytes!]!, $since: Int!, $first: Int!, $skip: Int!) {
  pairDayDatas(
    where: { pairAddress_in: $poolIds, date_gte: $since }
    orderBy: date
    orderDirection: desc
    first: $first
    skip: $skip
  ) {
    pairAddress
    date
    dailyVolumeUSD
  }
}
"""

_POOL_DETAIL_QUERY = """
query PoolDetail($id: ID!) {
  pool(id: $id) {
    id
    feeTier
    totalValueLockedUSD
    volumeUSD
    feesUSD
    txCount
    tick
    token0Price
    token1Price
    createdAtTimestamp
    token0 { id symbol name decimals derivedETH }
    token1 { id symbol name decimals derivedETH }
  }
  bundle(id: "1") {
    ethPriceUSD
  }
}
"""

# v2 chama o mesmo campo de bundle.ethPrice (sem "USD" no nome) -- confirmado
# por introspecção em 2026-09-09, diferente de v3/v4 (ethPriceUSD).
_POOL_DETAIL_QUERY_V2 = """
query PairDetail($id: ID!) {
  pair(id: $id) {
    id
    reserveUSD
    volumeUSD
    txCount
    token0Price
    token1Price
    createdAtTimestamp
    token0 { id symbol name decimals derivedETH }
    token1 { id symbol name decimals derivedETH }
  }
  bundle(id: "1") {
    ethPrice
  }
}
"""

# Pools/pairs com o mesmo par de tokens (outras fee tiers em v3/v4, ou a
# versão v2/v3/v4 do mesmo par) -- usado por get_related_pools. `token0`/
# `token1` aqui filtram pelo endereço do token diretamente (tipo String,
# confirmado por introspecção em 2026-09-09), não pela busca por símbolo/nome
# usada em _SEARCH_QUERY. A ordem token0/token1 é canônica (endereço menor
# primeiro), igual em todo deployment Uniswap, então dá pra reusar os
# endereços do pool de origem sem inverter.
_RELATED_POOLS_QUERY = """
query RelatedPools($token0: String!, $token1: String!, $first: Int!) {
  pools(
    where: { token0: $token0, token1: $token1 }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: $first
  ) {
    id
    feeTier
    totalValueLockedUSD
    volumeUSD
    token0 { id symbol name decimals }
    token1 { id symbol name decimals }
  }
}
"""

_RELATED_PAIRS_QUERY_V2 = """
query RelatedPairs($token0: String!, $token1: String!, $first: Int!) {
  pairs(
    where: { token0: $token0, token1: $token1 }
    orderBy: reserveUSD
    orderDirection: desc
    first: $first
  ) {
    id
    reserveUSD
    volumeUSD
    token0 { id symbol name decimals }
    token1 { id symbol name decimals }
  }
}
"""

_POOL_DAY_DATA_QUERY = """
query PoolDayData($poolId: String!, $first: Int!) {
  poolDayDatas(
    where: { pool: $poolId }
    orderBy: date
    orderDirection: desc
    first: $first
  ) {
    date
    tvlUSD
    volumeUSD
    feesUSD
    open
    high
    low
    close
  }
}
"""

_POOL_HOUR_DATA_QUERY = """
query PoolHourData($poolId: String!, $first: Int!) {
  poolHourDatas(
    where: { pool: $poolId }
    orderBy: periodStartUnix
    orderDirection: desc
    first: $first
  ) {
    periodStartUnix
    close
    tvlUSD
    volumeUSD
  }
}
"""


def _split_pool_id(pool_id: str) -> tuple[str, str]:
    """IDs expostos ao frontend têm o formato "{protocol}:{endereço}" (ex:
    "v2:0xabc...") -- ver _to_pool_summary/_to_pool_summary_v2. Sem prefixo,
    assume v3 (compatibilidade com IDs antigos)."""
    if ":" in pool_id:
        protocol, raw = pool_id.split(":", 1)
        if protocol in ("v2", "v3", "v4", "aerodrome"):
            return protocol, raw.lower()
    return "v3", pool_id.lower()


def _to_token(raw: dict) -> Token:
    return Token(id=raw["id"], symbol=raw["symbol"], name=raw["name"], decimals=int(raw["decimals"]))


def _to_pool_summary(raw: dict, protocol: str) -> PoolSummary:
    return PoolSummary(
        id=f"{protocol}:{raw['id']}",
        protocol=protocol,
        token0=_to_token(raw["token0"]),
        token1=_to_token(raw["token1"]),
        fee_tier=int(raw["feeTier"]),
        total_value_locked_usd=float(raw["totalValueLockedUSD"]),
        volume_usd=float(raw["volumeUSD"]),
    )


def _to_pool_summary_v2(raw: dict) -> PoolSummary:
    """v2 não tem feeTier (é sempre 0,30% fixo) -- usamos o mesmo valor em
    unidades de feeTier da v3 (3000 == 0,30%) só para reaproveitar
    `formatFeeTier` no frontend, não porque exista essa noção no protocolo."""
    return PoolSummary(
        id=f"v2:{raw['id']}",
        protocol="v2",
        token0=_to_token(raw["token0"]),
        token1=_to_token(raw["token1"]),
        fee_tier=V2_FEE_TIER,
        total_value_locked_usd=float(raw["reserveUSD"]),
        volume_usd=float(raw["volumeUSD"]),
    )


async def _fetch_recent_day_data_batch(
    protocol: str, raw_pool_ids: list[str], days: int = 30
) -> dict[str, list[tuple[int, float, float]]]:
    """Busca dados diários dos últimos `days` dias para vários pools/pairs de
    um mesmo protocolo de uma vez (1-2 chamadas ao gateway, não uma por pool),
    agrupando por endereço cru (sem prefixo de protocolo).

    Pagina em até 2 páginas de 1000 linhas (2000 no total). Para v2, como não
    existe `feesUSD` indexado, as taxas são estimadas como volume * V2_FEE_RATE.
    """
    if not raw_pool_ids:
        return {}

    since = int(time.time()) - (days + 1) * 86400
    grouped: dict[str, list[tuple[int, float, float]]] = {pid: [] for pid in raw_pool_ids}
    query = _BATCH_DAY_DATA_QUERY_V2 if protocol == "v2" else _BATCH_DAY_DATA_QUERY
    skip = 0
    page_size = 1000
    for _ in range(2):
        data = await graph_client.run_query(
            query,
            {"poolIds": raw_pool_ids, "since": since, "first": page_size, "skip": skip},
            protocol=protocol,
        )
        rows = data["pairDayDatas"] if protocol == "v2" else data["poolDayDatas"]
        for row in rows:
            if protocol == "v2":
                pool_id = row["pairAddress"]
                volume = float(row["dailyVolumeUSD"])
                fees = volume * V2_FEE_RATE
            else:
                pool_id = row["pool"]["id"]
                volume = float(row["volumeUSD"])
                fees = float(row["feesUSD"])
            grouped.setdefault(pool_id, []).append((int(row["date"]), volume, fees))
        if len(rows) < page_size:
            break
        skip += page_size
    return grouped


@dataclass(frozen=True)
class PoolDayStats:
    volume_1d: float
    volume_7d: float
    volume_30d: float
    volume_1d_over_tvl: float
    apr_7d: float
    apr_30d: float


_EMPTY_DAY_STATS = PoolDayStats(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


def _apr_or_zero(fees: float, tvl_usd: float, period_days: float) -> float:
    if tvl_usd <= 0:
        return 0.0
    try:
        return indicators.fee_apr_full_range(fees, tvl_usd, period_days=period_days)
    except ValueError:
        return 0.0


def _aggregate_pool_stats(day_rows: list[tuple[int, float, float]], tvl_usd: float) -> PoolDayStats:
    """A partir das linhas (date, volumeUSD, feesUSD) de um pool (até ~30
    dias), calcula volume/APR agregados em três janelas (1d/7d/30d)."""
    if not day_rows:
        return _EMPTY_DAY_STATS

    rows_desc = sorted(day_rows, key=lambda r: r[0], reverse=True)
    rows_7d = rows_desc[:7]

    volume_30d = sum(r[1] for r in rows_desc)
    volume_7d = sum(r[1] for r in rows_7d)
    volume_1d = rows_desc[0][1]
    volume_1d_over_tvl = volume_1d / tvl_usd if tvl_usd > 0 else 0.0

    fees_30d = sum(r[2] for r in rows_desc)
    fees_7d = sum(r[2] for r in rows_7d)
    apr_30d = _apr_or_zero(fees_30d, tvl_usd, period_days=len(rows_desc))
    apr_7d = _apr_or_zero(fees_7d, tvl_usd, period_days=len(rows_7d))

    return PoolDayStats(
        volume_1d=volume_1d,
        volume_7d=volume_7d,
        volume_30d=volume_30d,
        volume_1d_over_tvl=volume_1d_over_tvl,
        apr_7d=apr_7d,
        apr_30d=apr_30d,
    )


async def _search_v3v4(protocol: str, search: str, limit: int) -> list[PoolSummary]:
    data = await graph_client.run_query(
        _SEARCH_QUERY, {"search": search, "first": limit}, protocol=protocol, timeout=_SEARCH_TIMEOUT
    )
    raw_pools = data["bySymbol0"] + data["bySymbol1"] + data["byName0"] + data["byName1"]
    seen: set[str] = set()
    results: list[PoolSummary] = []
    for raw in raw_pools:
        if raw["id"] in seen:
            continue
        seen.add(raw["id"])
        results.append(_to_pool_summary(raw, protocol))
    return results


async def _search_v2(search: str, limit: int) -> list[PoolSummary]:
    data = await graph_client.run_query(
        _SEARCH_QUERY_V2, {"search": search, "first": limit}, protocol="v2", timeout=_SEARCH_TIMEOUT
    )
    raw_pairs = data["bySymbol0"] + data["bySymbol1"] + data["byName0"] + data["byName1"]
    seen: set[str] = set()
    results: list[PoolSummary] = []
    for raw in raw_pairs:
        if raw["id"] in seen:
            continue
        seen.add(raw["id"])
        results.append(_to_pool_summary_v2(raw))
    return results


async def search_pools(search: str, limit: int = 15) -> list[PoolSummary]:
    """Busca nos quatro subgraphs (v3, v4, v2, Aerodrome Slipstream) em
    paralelo e mescla por TVL.

    Custo em chamadas ao gateway: 4 de busca + até 2 de enriquecimento (dados
    diários) por protocolo com resultados = até 12 no total por busca (era 3
    quando só existia v3).

    Cada protocolo é isolado com `return_exceptions=True`: o subgraph v4, em
    particular, foi observado respondendo em >20s para termos de busca muito
    comuns (ex: "WETH") -- se um protocolo falhar ou estourar o timeout, os
    outros dois ainda são retornados em vez de derrubar a busca inteira.
    """
    raw_results = await asyncio.gather(
        _search_v3v4("v3", search, limit),
        _search_v3v4("v4", search, limit),
        _search_v2(search, limit),
        _search_v3v4("aerodrome", search, limit),
        return_exceptions=True,
    )
    results: list[PoolSummary] = []
    for r in raw_results:
        if isinstance(r, BaseException):
            continue
        results.extend(r)
    results.sort(key=lambda p: p.total_value_locked_usd, reverse=True)
    results = results[:limit]

    by_protocol: dict[str, list[PoolSummary]] = {}
    for pool in results:
        by_protocol.setdefault(pool.protocol, []).append(pool)

    protocols = list(by_protocol.keys())
    day_data_batches = await asyncio.gather(
        *[
            _fetch_recent_day_data_batch(protocol, [p.id.split(":", 1)[1] for p in pools])
            for protocol, pools in by_protocol.items()
        ],
        return_exceptions=True,
    )
    day_data_by_protocol: dict[str, dict[str, list[tuple[int, float, float]]]] = {}
    for protocol, batch in zip(protocols, day_data_batches):
        # Se o enriquecimento falhar para um protocolo, os pools desse
        # protocolo continuam na lista, só sem volume 1d/30d/APR (mesmo
        # visual de pool sem histórico -- degradação aceitável).
        day_data_by_protocol[protocol] = {} if isinstance(batch, BaseException) else batch

    for pool in results:
        raw_id = pool.id.split(":", 1)[1]
        day_rows = day_data_by_protocol[pool.protocol].get(raw_id, [])
        stats = _aggregate_pool_stats(day_rows, pool.total_value_locked_usd)
        pool.volume_1d_usd = stats.volume_1d
        pool.volume_7d_usd = stats.volume_7d
        pool.volume_30d_usd = stats.volume_30d
        pool.volume_1d_over_tvl = stats.volume_1d_over_tvl
        pool.apr_pool_7d = stats.apr_7d
        pool.apr_pool_30d = stats.apr_30d

    return results


async def _verify_tvl_onchain(
    pool_address: str,
    token0: Token,
    token1: Token,
    token0_derived_eth: float,
    token1_derived_eth: float,
    eth_price_usd: float,
    rpc_url: str,
) -> tuple[float, bool]:
    """Recalcula o TVL a partir do saldo real on-chain dos dois tokens no
    contrato do pool (balanceOf), em vez de confiar no totalValueLockedUSD/
    reserveUSD do subgraph -- que já observamos divergir bastante do real em
    alguns pools (bug de tracking incremental por delta de eventos, não
    resincroniza com o saldo real; ver CLAUDE.md). Usa o mesmo preço que o
    subgraph usaria (derivedETH * ethPriceUSD, já validado contra um pool de
    referência independente), só troca a fonte do saldo.

    Retorna (tvl_usd, verificado). Se a chamada on-chain falhar (RPC fora do
    ar, timeout), verificado=False e o chamador deve manter o valor do
    subgraph como fallback.
    """
    try:
        balance0_raw, balance1_raw = await asyncio.gather(
            onchain_client.get_erc20_balance(token0.id, pool_address, rpc_url),
            onchain_client.get_erc20_balance(token1.id, pool_address, rpc_url),
        )
    except OnchainQueryError:
        return 0.0, False

    balance0 = balance0_raw / (10**token0.decimals)
    balance1 = balance1_raw / (10**token1.decimals)
    price0_usd = token0_derived_eth * eth_price_usd
    price1_usd = token1_derived_eth * eth_price_usd
    return balance0 * price0_usd + balance1 * price1_usd, True


async def _get_pool_detail_v3v4(protocol: str, raw_id: str) -> PoolDetail | None:
    data = await graph_client.run_query(_POOL_DETAIL_QUERY, {"id": raw_id}, protocol=protocol)
    raw = data.get("pool")
    if raw is None:
        return None
    pool = PoolDetail(
        id=f"{protocol}:{raw['id']}",
        protocol=protocol,
        token0=_to_token(raw["token0"]),
        token1=_to_token(raw["token1"]),
        fee_tier=int(raw["feeTier"]),
        total_value_locked_usd=float(raw["totalValueLockedUSD"]),
        volume_usd=float(raw["volumeUSD"]),
        tick=int(raw["tick"]) if raw["tick"] is not None else None,
        token0_price=float(raw["token0Price"]),
        token1_price=float(raw["token1Price"]),
        fees_usd_lifetime=float(raw["feesUSD"]),
        tx_count=int(raw["txCount"]),
        created_at=int(raw["createdAtTimestamp"]),
    )

    bundle = data.get("bundle")
    if bundle is not None:
        tvl_onchain, verified = await _verify_tvl_onchain(
            raw_id,
            pool.token0,
            pool.token1,
            float(raw["token0"]["derivedETH"]),
            float(raw["token1"]["derivedETH"]),
            float(bundle["ethPriceUSD"]),
            _rpc_url_for_protocol(protocol),
        )
        if verified:
            pool.total_value_locked_usd = tvl_onchain
            pool.tvl_verified_onchain = True

    return pool


async def _get_pool_detail_v2(raw_id: str) -> PoolDetail | None:
    data = await graph_client.run_query(_POOL_DETAIL_QUERY_V2, {"id": raw_id}, protocol="v2")
    raw = data.get("pair")
    if raw is None:
        return None
    tvl = float(raw["reserveUSD"])
    pool = PoolDetail(
        id=f"v2:{raw['id']}",
        protocol="v2",
        token0=_to_token(raw["token0"]),
        token1=_to_token(raw["token1"]),
        fee_tier=V2_FEE_TIER,
        total_value_locked_usd=tvl,
        volume_usd=float(raw["volumeUSD"]),
        tick=None,
        token0_price=float(raw["token0Price"]),
        token1_price=float(raw["token1Price"]),
        fees_usd_lifetime=float(raw["volumeUSD"]) * V2_FEE_RATE,
        tx_count=int(raw["txCount"]),
        created_at=int(raw["createdAtTimestamp"]),
    )

    bundle = data.get("bundle")
    if bundle is not None:
        tvl_onchain, verified = await _verify_tvl_onchain(
            raw_id,
            pool.token0,
            pool.token1,
            float(raw["token0"]["derivedETH"]),
            float(raw["token1"]["derivedETH"]),
            float(bundle["ethPrice"]),
            _rpc_url_for_protocol("v2"),
        )
        if verified:
            tvl = tvl_onchain
            pool.total_value_locked_usd = tvl_onchain
            pool.tvl_verified_onchain = True

    # Reaproveita o mesmo lote diário usado na busca para preencher volume
    # 1d/7d/30d e APR estimado (a v2 não tem esses campos no detalhe direto).
    day_data = await _fetch_recent_day_data_batch("v2", [raw_id])
    stats = _aggregate_pool_stats(day_data.get(raw_id, []), tvl)
    pool.volume_1d_usd = stats.volume_1d
    pool.volume_7d_usd = stats.volume_7d
    pool.volume_30d_usd = stats.volume_30d
    pool.volume_1d_over_tvl = stats.volume_1d_over_tvl
    pool.apr_pool_7d = stats.apr_7d
    pool.apr_pool_30d = stats.apr_30d
    return pool


async def get_pool_detail(pool_id: str) -> PoolDetail | None:
    protocol, raw_id = _split_pool_id(pool_id)
    if protocol == "v2":
        return await _get_pool_detail_v2(raw_id)
    return await _get_pool_detail_v3v4(protocol, raw_id)


async def get_pool_day_data(pool_id: str, days: int = 30) -> list[DayDataPoint]:
    protocol, raw_id = _split_pool_id(pool_id)
    if protocol == "v2":
        # PairDayData da v2 não tem série OHLC (só reservas/volume) -- ver
        # docstring de _BATCH_DAY_DATA_QUERY_V2. Sem gráfico de preço para v2.
        raise GraphQueryError("Histórico de preço diário não está disponível para pools Uniswap v2 neste app.")
    data = await graph_client.run_query(_POOL_DAY_DATA_QUERY, {"poolId": raw_id, "first": days}, protocol=protocol)
    points = [
        DayDataPoint(
            date=int(d["date"]),
            tvl_usd=float(d["tvlUSD"]),
            volume_usd=float(d["volumeUSD"]),
            fees_usd=float(d["feesUSD"]),
            open=float(d["open"]),
            high=float(d["high"]),
            low=float(d["low"]),
            close=float(d["close"]),
        )
        for d in data["poolDayDatas"]
    ]
    return list(reversed(points))  # ordem cronológica ascendente


async def get_pool_hour_data(pool_id: str, hours: int = 168) -> list[HourDataPoint]:
    protocol, raw_id = _split_pool_id(pool_id)
    if protocol == "v2":
        # Sem liquidez concentrada na v2 -- o simulador de faixa não se aplica
        # (o frontend nem oferece essa opção para pools v2, ver App.tsx).
        raise GraphQueryError("Simulação de faixa não se aplica a pools Uniswap v2.")
    data = await graph_client.run_query(_POOL_HOUR_DATA_QUERY, {"poolId": raw_id, "first": hours}, protocol=protocol)
    points = [
        HourDataPoint(
            period_start_unix=int(h["periodStartUnix"]),
            close=float(h["close"]),
            tvl_usd=float(h["tvlUSD"]),
            volume_usd=float(h["volumeUSD"]),
        )
        for h in data["poolHourDatas"]
    ]
    return list(reversed(points))


_RELATED_POOLS_LIMIT = 8


async def _related_v3v4(protocol: str, token0_addr: str, token1_addr: str) -> list[PoolSummary]:
    data = await graph_client.run_query(
        _RELATED_POOLS_QUERY,
        {"token0": token0_addr, "token1": token1_addr, "first": _RELATED_POOLS_LIMIT},
        protocol=protocol,
    )
    return [_to_pool_summary(raw, protocol) for raw in data["pools"]]


async def _related_v2(token0_addr: str, token1_addr: str) -> list[PoolSummary]:
    data = await graph_client.run_query(
        _RELATED_PAIRS_QUERY_V2,
        {"token0": token0_addr, "token1": token1_addr, "first": _RELATED_POOLS_LIMIT},
        protocol="v2",
    )
    return [_to_pool_summary_v2(raw) for raw in data["pairs"]]


async def get_related_pools(pool_id: str) -> list[PoolSummary]:
    """Outras pools/pairs do mesmo par de tokens, nos protocolos que vivem na
    mesma chain do pool de origem -- outras fee tiers em v3/v4, a versão
    v2/v3/v4 do mesmo par, ou outras fee tiers/tick spacings em Aerodrome
    Slipstream. Não mistura protocolos de chains diferentes (v2/v3/v4 são
    Ethereum mainnet, Aerodrome é Base) -- os endereços de token nunca batem
    entre chains, então consultar os subgraphs da chain errada só gastaria
    quota à toa sem nunca achar nada. Exclui a própria pool da lista, ordena
    por TVL.
    """
    pool = await get_pool_detail(pool_id)
    if pool is None:
        return []

    token0_addr = pool.token0.id
    token1_addr = pool.token1.id
    same_chain_protocols = [p for p, chain in _PROTOCOL_CHAIN.items() if chain == _PROTOCOL_CHAIN[pool.protocol]]

    raw_results = await asyncio.gather(
        *[
            _related_v2(token0_addr, token1_addr)
            if protocol == "v2"
            else _related_v3v4(protocol, token0_addr, token1_addr)
            for protocol in same_chain_protocols
        ],
        return_exceptions=True,
    )
    results: list[PoolSummary] = [p for r in raw_results if not isinstance(r, BaseException) for p in r]
    results = [p for p in results if p.id != pool.id]

    by_protocol: dict[str, list[PoolSummary]] = {}
    for p in results:
        by_protocol.setdefault(p.protocol, []).append(p)

    protocols = list(by_protocol.keys())
    day_data_batches = await asyncio.gather(
        *[
            _fetch_recent_day_data_batch(protocol, [p.id.split(":", 1)[1] for p in pools])
            for protocol, pools in by_protocol.items()
        ],
        return_exceptions=True,
    )
    day_data_by_protocol: dict[str, dict[str, list[tuple[int, float, float]]]] = {}
    for protocol, batch in zip(protocols, day_data_batches):
        day_data_by_protocol[protocol] = {} if isinstance(batch, BaseException) else batch

    for p in results:
        raw_id = p.id.split(":", 1)[1]
        day_rows = day_data_by_protocol[p.protocol].get(raw_id, [])
        stats = _aggregate_pool_stats(day_rows, p.total_value_locked_usd)
        p.volume_1d_usd = stats.volume_1d
        p.volume_7d_usd = stats.volume_7d
        p.volume_30d_usd = stats.volume_30d
        p.volume_1d_over_tvl = stats.volume_1d_over_tvl
        p.apr_pool_7d = stats.apr_7d
        p.apr_pool_30d = stats.apr_30d

    # TVL abaixo de ~$1k é essencialmente poeira (pool de teste/esquecida) e
    # o APR calculado sobre um denominador tão pequeno vira ruído sem sentido
    # (já vimos casos de >1000000% "APR" nesses pools) -- não ajuda a comparar
    # onde a liquidez de verdade está, então não mostramos.
    results = [p for p in results if p.total_value_locked_usd >= 1_000]
    results.sort(key=lambda p: p.total_value_locked_usd, reverse=True)
    return results[:6]
