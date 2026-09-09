from fastapi import APIRouter, HTTPException, Query

from .. import indicators
from ..graph_client import GraphQueryError
from ..schemas import DayDataPoint, HourDataPoint, PoolDetail, PoolIndicatorsResponse, PoolSummary
from ..services import pools as pools_service

router = APIRouter(prefix="/api/pools", tags=["pools"])


@router.get("/search", response_model=list[PoolSummary])
async def search_pools(q: str = Query(..., min_length=1), limit: int = Query(50, ge=1, le=50)):
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


@router.get("/{pool_id}/related", response_model=list[PoolSummary])
async def get_related_pools(pool_id: str):
    try:
        return await pools_service.get_related_pools(pool_id)
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

    # daily vem em ordem cronológica ascendente (ver get_pool_day_data) -- os
    # últimos 7 elementos são os 7 dias mais recentes.
    daily_7d = daily[-7:]

    try:
        fees_30d = sum(d.fees_usd for d in daily)
        fee_apr_30d = indicators.fee_apr_full_range(fees_30d, pool.total_value_locked_usd, period_days=len(daily))
        closes_30d = [d.close for d in daily]
        vol_30d = indicators.annualized_volatility(closes_30d)

        fees_7d = sum(d.fees_usd for d in daily_7d)
        fee_apr_7d = indicators.fee_apr_full_range(fees_7d, pool.total_value_locked_usd, period_days=len(daily_7d))
        closes_7d = [d.close for d in daily_7d]
        # Volatilidade de 7d precisa de pelo menos 2 preços -- pools com
        # histórico curto (<8 dias) ainda calculam a de 30d normalmente, só
        # a de 7d fica indisponível (0.0, o frontend trata como "sem dado").
        vol_7d = indicators.annualized_volatility(closes_7d) if len(closes_7d) >= 2 else 0.0
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Não foi possível calcular indicadores para este pool — dados insuficientes ou "
                f"degenerados (ex: sem preço ou sem liquidez válida): {exc}"
            ),
        ) from exc

    return PoolIndicatorsResponse(
        pool=pool,
        fee_apr_full_range_7d=fee_apr_7d,
        fee_apr_full_range_30d=fee_apr_30d,
        annualized_volatility_7d=vol_7d,
        annualized_volatility_30d=vol_30d,
        volume_7d_usd=sum(d.volume_usd for d in daily_7d),
        volume_30d_usd=sum(d.volume_usd for d in daily),
    )
