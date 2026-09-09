from __future__ import annotations

from .. import graph_client
from ..schemas import DayDataPoint, HourDataPoint, PoolDetail, PoolSummary, Token

_SEARCH_QUERY = """
query SearchPools($search: String!, $first: Int!) {
  asToken0: pools(
    where: { token0_: { symbol_contains_nocase: $search } }
    orderBy: totalValueLockedUSD
    orderDirection: desc
    first: $first
  ) {
    ...PoolFields
  }
  asToken1: pools(
    where: { token1_: { symbol_contains_nocase: $search } }
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


async def search_pools(search: str, limit: int = 15) -> list[PoolSummary]:
    data = await graph_client.run_query(_SEARCH_QUERY, {"search": search, "first": limit})
    raw_pools = data["asToken0"] + data["asToken1"]
    seen: set[str] = set()
    results: list[PoolSummary] = []
    for raw in raw_pools:
        if raw["id"] in seen:
            continue
        seen.add(raw["id"])
        results.append(_to_pool_summary(raw))
    results.sort(key=lambda p: p.total_value_locked_usd, reverse=True)
    return results[:limit]


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
