import asyncio

from fastapi import APIRouter, HTTPException, Query

from .. import local_db
from ..config import get_settings
from ..graph_client import GraphQueryError
from ..schemas import (
    AssetIndexResponse,
    AssetIndexRow,
    AssetTopPair,
    IndexStatusResponse,
    PoolIndexResponse,
    PoolIndexRow,
)
from ..services import index_builder

router = APIRouter(prefix="/api/index", tags=["index"])


def _asset_to_row(a: local_db.AssetRecord) -> AssetIndexRow:
    return AssetIndexRow(
        id=a.id,
        chain=a.chain,
        address=a.address,
        symbol=a.symbol,
        name=a.name,
        decimals=a.decimals,
        category=a.category,
        pools_count=a.pools_count,
        total_tvl_usd=a.total_tvl_usd,
        top_pairs=[AssetTopPair(**p) for p in a.top_pairs],
    )


def _pool_to_row(p: local_db.PoolRecord) -> PoolIndexRow:
    return PoolIndexRow(
        id=p.id,
        protocol=p.protocol,
        chain=p.chain,
        token0_symbol=p.token0_symbol,
        token0_address=p.token0_address,
        token1_symbol=p.token1_symbol,
        token1_address=p.token1_address,
        fee_tier=p.fee_tier,
        total_value_locked_usd=p.total_value_locked_usd,
        volume_usd=p.volume_usd,
        created_at=p.created_at,
    )


def _meta_to_status(meta: local_db.IndexMeta) -> IndexStatusResponse:
    return IndexStatusResponse(
        updated_at=meta.updated_at,
        min_tvl_usd=meta.min_tvl_usd,
        total_assets=meta.total_assets,
        total_pools=meta.total_pools,
        protocol_errors=meta.protocol_errors,
    )


@router.get("/status", response_model=IndexStatusResponse)
async def get_status():
    meta = await asyncio.to_thread(local_db.get_meta)
    return _meta_to_status(meta)


@router.post("/refresh", response_model=IndexStatusResponse)
async def refresh_index(min_tvl_usd: float | None = Query(None, ge=0)):
    settings = get_settings()
    floor = min_tvl_usd if min_tvl_usd is not None else settings.index_min_tvl_usd
    try:
        meta = await index_builder.rebuild_index(floor)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _meta_to_status(meta)


@router.get("/assets", response_model=AssetIndexResponse)
async def list_assets(
    q: str | None = None,
    category: str | None = None,
    sort: str = "total_tvl_usd",
    order: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items, total = await asyncio.to_thread(local_db.query_assets, q, category, sort, order, limit, offset)
    return AssetIndexResponse(items=[_asset_to_row(a) for a in items], total=total)


@router.get("/assets/suggest", response_model=list[AssetIndexRow])
async def suggest_assets(prefix: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=20)):
    items = await asyncio.to_thread(local_db.suggest_assets, prefix, limit)
    return [_asset_to_row(a) for a in items]


@router.get("/pools", response_model=PoolIndexResponse)
async def list_pools_index(
    q: str | None = None,
    protocol: str | None = None,
    sort: str = "total_value_locked_usd",
    order: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    items, total = await asyncio.to_thread(local_db.query_pools, q, protocol, sort, order, limit, offset)
    return PoolIndexResponse(items=[_pool_to_row(p) for p in items], total=total)
