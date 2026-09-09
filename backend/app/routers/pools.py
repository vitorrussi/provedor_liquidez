from fastapi import APIRouter, HTTPException, Query

from .. import indicators
from ..graph_client import GraphQueryError
from ..schemas import DayDataPoint, HourDataPoint, PoolDetail, PoolIndicatorsResponse, PoolSummary
from ..services import pools as pools_service

router = APIRouter(prefix="/api/pools", tags=["pools"])

_VALID_PROTOCOLS = {"v2", "v3", "v4", "aerodrome"}


@router.get("/search", response_model=list[PoolSummary])
async def search_pools(
    q: str | None = Query(None, min_length=1),
    token_a: str | None = Query(None, min_length=1),
    token_b: str | None = Query(None, min_length=1),
    exact: bool = False,
    hide_inactive: bool = False,
    min_tvl_usd: float = Query(0.0, ge=0),
    protocol: list[str] | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
):
    pair_mode = bool(token_a and token_b)
    if not q and not pair_mode and not token_a and not token_b:
        raise HTTPException(
            status_code=400, detail="Informe um termo de busca (q) ou as duas siglas do par (token_a e token_b)."
        )
    if protocol is not None:
        invalid = set(protocol) - _VALID_PROTOCOLS
        if invalid:
            raise HTTPException(status_code=400, detail=f"Protocolo(s) inválido(s): {', '.join(sorted(invalid))}")

    # Se só um dos dois campos de par foi preenchido, trata como busca de
    # texto normal por aquele token em vez de erro -- fallback mais útil que
    # simplesmente ignorar o valor digitado.
    search_term = q or (token_a if not pair_mode else None) or (token_b if not pair_mode else None)

    try:
        return await pools_service.search_pools(
            search=search_term,
            token_a=token_a if pair_mode else None,
            token_b=token_b if pair_mode else None,
            exact=exact,
            hide_inactive=hide_inactive,
            min_tvl_usd=min_tvl_usd,
            protocols=protocol,
            limit=limit,
        )
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
