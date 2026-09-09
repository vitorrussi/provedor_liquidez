from fastapi import APIRouter, HTTPException

from .. import indicators as ind
from ..graph_client import GraphQueryError
from ..schemas import (
    ImpermanentLossRequest,
    ImpermanentLossResponse,
    RangeSimulationRequest,
    RangeSimulationResponse,
)
from ..services import pools as pools_service

router = APIRouter(prefix="/api/indicators", tags=["indicators"])


@router.post("/impermanent-loss", response_model=ImpermanentLossResponse)
def compute_impermanent_loss(req: ImpermanentLossRequest):
    try:
        il = ind.impermanent_loss_v3(req.entry_price, req.current_price, req.price_lower, req.price_upper)
        r = req.current_price / req.entry_price
        il_full_range = ind.impermanent_loss_v2(r)
        mult = ind.concentration_multiplier(req.price_lower, req.price_upper)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ImpermanentLossResponse(
        impermanent_loss=il,
        impermanent_loss_full_range_equivalent=il_full_range,
        concentration_multiplier=mult,
    )


@router.post("/range-simulate", response_model=RangeSimulationResponse)
async def simulate_range(req: RangeSimulationRequest):
    try:
        hourly = await pools_service.get_pool_hour_data(req.pool_id, hours=req.history_days * 24)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if len(hourly) < 24:
        raise HTTPException(status_code=422, detail="Histórico horário insuficiente para simular a faixa")

    closes = [h.close for h in hourly]
    entry_price = req.entry_price if req.entry_price is not None else closes[0]

    try:
        daily = await pools_service.get_pool_day_data(req.pool_id, days=req.history_days)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pool = await pools_service.get_pool_detail(req.pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool não encontrado")

    fees_period = sum(d.fees_usd for d in daily)
    try:
        fee_apr = ind.fee_apr_full_range(fees_period, pool.total_value_locked_usd, period_days=max(len(daily), 1))
        replay = ind.replay_range_against_history(
            hourly_prices=closes,
            entry_price=entry_price,
            price_lower=req.price_lower,
            price_upper=req.price_upper,
            fee_apr_full_range_value=fee_apr,
        )
        breakeven = ind.breakeven_days(replay.estimated_position_apr, replay.impermanent_loss)
        vol = ind.annualized_volatility(closes) if len(closes) >= 2 else 0.0
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RangeSimulationResponse(
        in_range_fraction=replay.in_range_fraction,
        concentration_multiplier=replay.concentration_multiplier,
        fee_apr_full_range=fee_apr,
        estimated_position_apr=replay.estimated_position_apr,
        impermanent_loss=replay.impermanent_loss,
        breakeven_days=breakeven,
        entry_price=replay.entry_price,
        end_price=replay.end_price,
        sample_count=replay.sample_count,
        annualized_volatility=vol,
    )
