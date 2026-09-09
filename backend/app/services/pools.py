from __future__ import annotations

import time

from .. import graph_client, indicators
from ..schemas import DayDataPoint, HourDataPoint, PoolDetail, PoolSummary, Token

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


def _to_token(raw: dict) -> Token:
    return Token(id=raw["id"], symbol=raw["symbol"], name=raw["name"], decimals=int(raw["decimals"]))


def _to_pool_summary(raw: dict) -> PoolSummary:
    return PoolSummary(
        id=raw["id"],
        token0=_to_token(raw["token0"]),
        token1=_to_token(raw["token1"]),
        fee_tier=int(raw["feeTier"]),
        total_value_locked_usd=float(raw["totalValueLockedUSD"]),
        volume_usd=float(raw["volumeUSD"]),
    )


async def _fetch_recent_day_data_batch(pool_ids: list[str], days: int = 30) -> dict[str, list[tuple[int, float, float]]]:
    """Busca poolDayData dos últimos `days` dias para vários pools de uma vez
    (1-2 chamadas ao gateway no total, não uma por pool), agrupando por pool id.

    Pagina em até 2 páginas de 1000 linhas (2000 no total) — cobre
    confortavelmente até ~60 pools * 31 dias, a faixa que este app usa
    (SEARCH_LIMIT do frontend é 50).
    """
    if not pool_ids:
        return {}

    since = int(time.time()) - (days + 1) * 86400
    grouped: dict[str, list[tuple[int, float, float]]] = {pid: [] for pid in pool_ids}
    skip = 0
    page_size = 1000
    for _ in range(2):
        data = await graph_client.run_query(
            _BATCH_DAY_DATA_QUERY,
            {"poolIds": pool_ids, "since": since, "first": page_size, "skip": skip},
        )
        rows = data["poolDayDatas"]
        for row in rows:
            pool_id = row["pool"]["id"]
            grouped.setdefault(pool_id, []).append((int(row["date"]), float(row["volumeUSD"]), float(row["feesUSD"])))
        if len(rows) < page_size:
            break
        skip += page_size
    return grouped


def _aggregate_pool_stats(
    day_rows: list[tuple[int, float, float]], tvl_usd: float
) -> tuple[float, float, float, float]:
    """A partir das linhas (date, volumeUSD, feesUSD) de um pool, retorna
    (volume_1d, volume_30d, volume_1d_sobre_tvl, apr_pool_30d)."""
    if not day_rows:
        return 0.0, 0.0, 0.0, 0.0

    rows_desc = sorted(day_rows, key=lambda r: r[0], reverse=True)
    volume_30d = sum(r[1] for r in rows_desc)
    fees_30d = sum(r[2] for r in rows_desc)
    volume_1d = rows_desc[0][1]
    volume_1d_over_tvl = volume_1d / tvl_usd if tvl_usd > 0 else 0.0

    apr_pool_30d = 0.0
    if tvl_usd > 0:
        try:
            apr_pool_30d = indicators.fee_apr_full_range(fees_30d, tvl_usd, period_days=len(rows_desc))
        except ValueError:
            apr_pool_30d = 0.0

    return volume_1d, volume_30d, volume_1d_over_tvl, apr_pool_30d


async def search_pools(search: str, limit: int = 15) -> list[PoolSummary]:
    data = await graph_client.run_query(_SEARCH_QUERY, {"search": search, "first": limit})
    raw_pools = data["bySymbol0"] + data["bySymbol1"] + data["byName0"] + data["byName1"]
    seen: set[str] = set()
    results: list[PoolSummary] = []
    for raw in raw_pools:
        if raw["id"] in seen:
            continue
        seen.add(raw["id"])
        results.append(_to_pool_summary(raw))
    results.sort(key=lambda p: p.total_value_locked_usd, reverse=True)
    results = results[:limit]

    day_data_by_pool = await _fetch_recent_day_data_batch([p.id for p in results])
    for pool in results:
        vol_1d, vol_30d, vol_1d_over_tvl, apr_30d = _aggregate_pool_stats(
            day_data_by_pool.get(pool.id, []), pool.total_value_locked_usd
        )
        pool.volume_1d_usd = vol_1d
        pool.volume_30d_usd = vol_30d
        pool.volume_1d_over_tvl = vol_1d_over_tvl
        pool.apr_pool_30d = apr_30d

    return results


async def get_pool_detail(pool_id: str) -> PoolDetail | None:
    data = await graph_client.run_query(_POOL_DETAIL_QUERY, {"id": pool_id.lower()})
    raw = data.get("pool")
    if raw is None:
        return None
    return PoolDetail(
        id=raw["id"],
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
    )


async def get_pool_day_data(pool_id: str, days: int = 30) -> list[DayDataPoint]:
    data = await graph_client.run_query(_POOL_DAY_DATA_QUERY, {"poolId": pool_id.lower(), "first": days})
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
    data = await graph_client.run_query(_POOL_HOUR_DATA_QUERY, {"poolId": pool_id.lower(), "first": hours})
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
