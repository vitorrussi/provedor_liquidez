from fastapi import APIRouter, HTTPException, Query

from .. import indicators
from ..graph_client import GraphQueryError
from ..schemas import DayDataPoint, HourDataPoint, PoolDetail, PoolIndicatorsResponse, PoolSummary
from ..services import pools as pools_service

router = APIRouter(prefix="/api/pools", tags=["pools"])


@router.get("/search", response_model=list[PoolSummary])
async def search_pools(q: str = Query(..., min_length=1), limit: int = Query(15, ge=1, le=50)):
    try:
        return await pools_service.search_pools(q, limit)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{pool_id}", response_model=PoolDetail)
async def get_pool(pool_id: str):
    try:
        pool = await pools_service.get_pool_detail(pool_id)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool não encontrado")
    return pool


@router.get("/{pool_id}/history/daily", response_model=list[DayDataPoint])
async def get_daily_history(pool_id: str, days: int = Query(30, ge=1, le=365)):
    try:
        return await pools_service.get_pool_day_data(pool_id, days)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{pool_id}/history/hourly", response_model=list[HourDataPoint])
async def get_hourly_history(pool_id: str, hours: int = Query(168, ge=1, le=744)):
    try:
        return await pools_service.get_pool_hour_data(pool_id, hours)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{pool_id}/indicators", response_model=PoolIndicatorsResponse)
async def get_pool_indicators(pool_id: str):
    try:
        pool = await pools_service.get_pool_detail(pool_id)
        if pool is None:
            raise HTTPException(status_code=404, detail="Pool não encontrado")
        daily = await pools_service.get_pool_day_data(pool_id, days=30)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if len(daily) < 2:
        raise HTTPException(status_code=422, detail="Histórico insuficiente para calcular indicadores")

    try:
        fees_30d = sum(d.fees_usd for d in daily)
        fee_apr = indicators.fee_apr_full_range(fees_30d, pool.total_value_locked_usd, period_days=len(daily))
        closes = [d.close for d in daily]
        vol = indicators.annualized_volatility(closes)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Não foi possível calcular indicadores para este pool — dados insuficientes ou "
                f"degenerados (ex: sem preço ou sem liquidez válida): {exc}"
            ),
        ) from exc

    return PoolIndicatorsResponse(pool=pool, fee_apr_full_range_30d=fee_apr, annualized_volatility_30d=vol)
