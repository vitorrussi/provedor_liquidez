"""Constrói o índice local (SQLite, ver local_db.py) de ativos e pools
"relevantes" (TVL/reserva acima de um piso configurável), usado pelas páginas
/assets e /pools e pelo autocomplete do campo de busca principal.

Pagina por cursor (`id_gt`), não por skip/offset -- o Graph limita `skip` a
5000, e uma lista com TVL >= $1k passa disso fácil (~7900 pools só na v3
mainnet, medido em 2026-09-09). `_MAX_PAGES` é uma margem de segurança, não
um limite esperado de ser atingido na prática.

Não roda automaticamente: só quando o usuário clica em "Atualizar" (ver
routers/local_index.py). Custo típico de um refresh completo: ~90-180
consultas ao gateway (rodando os 6 protocolos em paralelo -- v2/v3/v4
mainnet, Aerodrome Slipstream em Base, Uniswap v3 em Polygon e Avalanche) --
ainda uma fração pequena da cota mensal de 100k, mas grande o bastante pra
não valer a pena rodar a cada carregamento de página.

`_PAGE_SIZE` é 500, não 1.000, para todos os protocolos v3-like (v3/v4/
aerodrome/polygon/avalanche, que trazem `poolDayData` aninhado, ver
`_INDEX_POOLS_QUERY`) -- achado real em
2026-09-10: com `first: 1000` e 30 dias aninhados por pool (até 30 mil
entidades por página), um crawl de v3 falhou com "bad indexers:
Timeout/Unavailable" no gateway; página menor reduz o payload por
requisição e a chance de bater nesse tipo de instabilidade do lado dos
indexadores, ao custo de o dobro de páginas (mesmo teto de ~30 mil pools no
total, `_MAX_PAGES` dobrado também).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .. import graph_client, local_db, token_categories
from ..graph_client import GraphQueryError
from . import pools as pools_service

_PAGE_SIZE = 500
_MAX_PAGES = 60

# `poolDayData` é um campo derivado (@derivedFrom) no schema do Pool -- vem
# de graça na MESMA consulta (sem custo extra de query ao gateway), diferente
# de v2 (ver _INDEX_PAIRS_QUERY_V2 abaixo): PairDayData não tem relação
# reversa pra Pair no schema, só o endereço cru em `pairAddress` (Bytes) --
# confirmado por introspecção em 2026-09-10 (nenhum campo "*day*" em `Pair`).
# Por isso pools v2 ficam sem volume_1d/30d/APR no índice local (NULL, não 0
# -- ver local_db.py); replicar isso pra v2 exigiria uma segunda rodada de
# consultas em lote (pairDayDatas com pair_in) só pra esse protocolo, cara
# demais pro refresh manual de ~40k pools (ver docstring do módulo).
_INDEX_POOLS_QUERY = """
query IndexPools($minTvl: BigDecimal!, $first: Int!, $lastId: String!) {
  pools(
    where: { totalValueLockedUSD_gte: $minTvl, id_gt: $lastId }
    orderBy: id
    orderDirection: asc
    first: $first
  ) {
    id
    feeTier
    totalValueLockedUSD
    volumeUSD
    createdAtTimestamp
    token0 { id symbol name decimals }
    token1 { id symbol name decimals }
    poolDayData(first: 30, orderBy: date, orderDirection: desc) {
      date
      volumeUSD
      feesUSD
    }
  }
}
"""

# v2 (entidade Pair) não tem feeTier -- ver pools_service.V2_FEE_TIER.
_INDEX_PAIRS_QUERY_V2 = """
query IndexPairs($minTvl: BigDecimal!, $first: Int!, $lastId: String!) {
  pairs(
    where: { reserveUSD_gte: $minTvl, id_gt: $lastId }
    orderBy: id
    orderDirection: asc
    first: $first
  ) {
    id
    reserveUSD
    volumeUSD
    createdAtTimestamp
    token0 { id symbol name decimals }
    token1 { id symbol name decimals }
  }
}
"""


async def _crawl_v3v4_like(protocol: str, min_tvl_usd: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_id = ""
    for _ in range(_MAX_PAGES):
        data = await graph_client.run_query(
            _INDEX_POOLS_QUERY,
            {"minTvl": str(min_tvl_usd), "first": _PAGE_SIZE, "lastId": last_id},
            protocol=protocol,
            timeout=60.0,
        )
        page = data["pools"]
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        last_id = page[-1]["id"]
    return rows


async def _crawl_v2(min_tvl_usd: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    last_id = ""
    for _ in range(_MAX_PAGES):
        data = await graph_client.run_query(
            _INDEX_PAIRS_QUERY_V2,
            {"minTvl": str(min_tvl_usd), "first": _PAGE_SIZE, "lastId": last_id},
            protocol="v2",
            timeout=60.0,
        )
        page = data["pairs"]
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        last_id = page[-1]["id"]
    return rows


@dataclass
class _AssetAgg:
    chain: str
    address: str
    symbol: str
    name: str
    decimals: int
    pools_count: int = 0
    total_tvl_usd: float = 0.0
    # Soma do volume histórico (lifetime) das pools onde o ativo aparece --
    # usado pelo filtro "ocultar sem atividade" nas páginas /assets e /pools
    # (mesmo critério de "atividade" da busca ao vivo, ver
    # local_db._MIN_ACTIVE_VOLUME_USD).
    total_volume_usd: float = 0.0
    # Soma do volume 1d/30d das pools onde o ativo aparece que TÊM essa
    # métrica medida (ver _INDEX_POOLS_QUERY) -- todo protocolo v3-like
    # contribui (v3/v4/aerodrome/polygon/avalanche); só v2 não participa
    # dessa soma (não é tratado como 0, ver `has_windowed_data`).
    total_volume_1d_usd: float = 0.0
    total_volume_30d_usd: float = 0.0
    # True se pelo menos uma pool desse ativo tinha volume_1d/30d medido --
    # se False, o ativo só aparece em pools v2 e as somas acima ficam sem
    # sentido (NULL na resposta, não 0 -- ver local_db.init_schema).
    has_windowed_data: bool = False
    # símbolo da contraparte -> soma do TVL das pools com essa contraparte;
    # usado como aproximação de "com o que esse ativo mais negocia".
    counterpart_tvl: dict[str, float] = field(default_factory=dict)


def _add_to_agg(
    agg: dict[str, _AssetAgg],
    chain: str,
    token: dict[str, Any],
    pool_tvl: float,
    pool_volume: float,
    counterpart_symbol: str,
    day_stats: "pools_service.PoolDayStats | None",
) -> None:
    asset_id = f"{chain}:{token['id'].lower()}"
    entry = agg.get(asset_id)
    if entry is None:
        entry = _AssetAgg(
            chain=chain, address=token["id"].lower(), symbol=token["symbol"], name=token["name"],
            decimals=int(token["decimals"]),
        )
        agg[asset_id] = entry
    entry.pools_count += 1
    entry.total_tvl_usd += pool_tvl
    entry.total_volume_usd += pool_volume
    if day_stats is not None:
        entry.has_windowed_data = True
        entry.total_volume_1d_usd += day_stats.volume_1d
        entry.total_volume_30d_usd += day_stats.volume_30d
    entry.counterpart_tvl[counterpart_symbol] = entry.counterpart_tvl.get(counterpart_symbol, 0.0) + pool_tvl


def _build_pool_record(
    protocol: str,
    chain: str,
    raw: dict[str, Any],
    fee_tier: int,
    tvl: float,
    volume: float,
    day_stats: "pools_service.PoolDayStats | None",
) -> local_db.PoolRecord:
    return local_db.PoolRecord(
        id=f"{protocol}:{raw['id']}",
        protocol=protocol,
        chain=chain,
        token0_symbol=raw["token0"]["symbol"],
        token0_address=raw["token0"]["id"],
        token1_symbol=raw["token1"]["symbol"],
        token1_address=raw["token1"]["id"],
        fee_tier=fee_tier,
        total_value_locked_usd=tvl,
        volume_usd=volume,
        created_at=int(raw["createdAtTimestamp"]) if raw.get("createdAtTimestamp") is not None else None,
        volume_1d_usd=day_stats.volume_1d if day_stats is not None else None,
        volume_30d_usd=day_stats.volume_30d if day_stats is not None else None,
        volume_1d_over_tvl=day_stats.volume_1d_over_tvl if day_stats is not None else None,
        apr_pool_30d=day_stats.apr_30d if day_stats is not None else None,
    )


async def rebuild_index(min_tvl_usd: float = 1000.0) -> local_db.IndexMeta:
    """Refaz o índice local do zero (crawl completo dos 6 protocolos, em
    paralelo). Se TODOS os protocolos falharem, não sobrescreve o índice
    existente (levanta GraphQueryError) -- uma atualização parcial (alguns
    protocolos ok, outros não) ainda substitui o índice inteiro, mas fica
    registrada em `protocol_errors` pra UI avisar que aquele protocolo pode
    estar desatualizado até a próxima tentativa.
    """
    protocols = ["v2", "v3", "v4", "aerodrome", "polygon", "avalanche"]
    raw_results = await asyncio.gather(
        _crawl_v2(min_tvl_usd),
        _crawl_v3v4_like("v3", min_tvl_usd),
        _crawl_v3v4_like("v4", min_tvl_usd),
        _crawl_v3v4_like("aerodrome", min_tvl_usd),
        _crawl_v3v4_like("polygon", min_tvl_usd),
        _crawl_v3v4_like("avalanche", min_tvl_usd),
        return_exceptions=True,
    )

    protocol_errors: dict[str, str] = {}
    pool_records: list[local_db.PoolRecord] = []
    asset_agg: dict[str, _AssetAgg] = {}

    for protocol, raw in zip(protocols, raw_results):
        if isinstance(raw, BaseException):
            protocol_errors[protocol] = str(raw)
            continue
        chain = pools_service._PROTOCOL_CHAIN[protocol]
        for row in raw:
            if protocol == "v2":
                tvl = float(row["reserveUSD"])
                fee_tier = pools_service.V2_FEE_TIER
            else:
                tvl = float(row["totalValueLockedUSD"])
                fee_tier = int(row["feeTier"])
            volume = float(row["volumeUSD"])
            # Descarta pools com dados corrompidos/manipulados -- achado real
            # ao construir esse índice, ver pools_service._is_plausible_pool.
            if not pools_service._is_plausible_pool(tvl, fee_tier, volume):
                continue
            # v2 não tem `poolDayData` na resposta (nem existe no schema, ver
            # comentário em _INDEX_POOLS_QUERY) -- day_stats fica None, e as
            # métricas por janela ficam NULL no índice pra esse pool/ativo.
            day_stats = None
            if protocol != "v2":
                day_rows = [
                    (int(d["date"]), float(d["volumeUSD"]), float(d["feesUSD"]))
                    for d in row.get("poolDayData", [])
                ]
                day_stats = pools_service._aggregate_pool_stats(day_rows, tvl)
            pool_records.append(_build_pool_record(protocol, chain, row, fee_tier, tvl, volume, day_stats))
            _add_to_agg(asset_agg, chain, row["token0"], tvl, volume, row["token1"]["symbol"], day_stats)
            _add_to_agg(asset_agg, chain, row["token1"], tvl, volume, row["token0"]["symbol"], day_stats)

    if len(protocol_errors) == len(protocols):
        raise GraphQueryError(f"Falha ao atualizar o índice em todos os protocolos: {protocol_errors}")

    asset_records: list[local_db.AssetRecord] = []
    for asset_id, agg in asset_agg.items():
        top_pairs = sorted(agg.counterpart_tvl.items(), key=lambda kv: kv[1], reverse=True)[:3]
        asset_records.append(
            local_db.AssetRecord(
                id=asset_id,
                chain=agg.chain,
                address=agg.address,
                symbol=agg.symbol,
                name=agg.name,
                decimals=agg.decimals,
                category=token_categories.categorize(agg.symbol),
                pools_count=agg.pools_count,
                total_tvl_usd=agg.total_tvl_usd,
                total_volume_usd=agg.total_volume_usd,
                top_pairs=[{"symbol": s, "tvl_usd": v} for s, v in top_pairs],
                volume_1d_usd=agg.total_volume_1d_usd if agg.has_windowed_data else None,
                volume_30d_usd=agg.total_volume_30d_usd if agg.has_windowed_data else None,
                volume_1d_over_tvl=(
                    agg.total_volume_1d_usd / agg.total_tvl_usd
                    if agg.has_windowed_data and agg.total_tvl_usd > 0
                    else None
                ),
            )
        )

    return local_db.replace_index(asset_records, pool_records, min_tvl_usd, protocol_errors)
