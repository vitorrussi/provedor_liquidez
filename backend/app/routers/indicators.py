from fastapi import APIRouter, HTTPException

from .. import indicators as ind
from ..graph_client import GraphQueryError
from ..schemas import (
    ImpermanentLossRequest,
    ImpermanentLossResponse,
    RangeAnalysisRequest,
    RangeAnalysisResponse,
    RangeScenario,
)
from ..services import pools as pools_service

router = APIRouter(prefix="/api/indicators", tags=["indicators"])

# k (em desvios-padrão) de cada faixa sugerida por volatilidade -- ver
# indicators.suggest_range_by_volatility. Não inclui a faixa "realized", que
# não usa k (é o mín/máx observado, ver suggest_range_from_realized).
_SUGGESTED_VOLATILITY_K = {"narrow": 0.5, "medium": 1.0, "wide": 2.0}

# Teto de history_days -- poolHourDatas é buscado com first: history_days*24,
# e o Graph limita first a 1000. 41*24 = 984 <= 1000; 42*24 = 1008 já estoura
# (viria truncado silenciosamente, sem erro, inflando "tempo em faixa" ao
# ignorar parte do período pedido). Ver CLAUDE.md.
_MAX_HISTORY_DAYS = 41


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


@router.post("/range-analysis", response_model=RangeAnalysisResponse)
async def analyze_range(req: RangeAnalysisRequest):
    history_days = min(req.history_days, _MAX_HISTORY_DAYS)
    try:
        hourly = await pools_service.get_pool_hour_data(req.pool_id, hours=history_days * 24)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if len(hourly) < 24:
        raise HTTPException(status_code=422, detail="Histórico horário insuficiente para analisar a faixa")

    hourly_closes = [h.close for h in hourly]
    entry_price = req.entry_price if req.entry_price is not None else hourly_closes[0]
    current_price = hourly_closes[-1]

    try:
        daily = await pools_service.get_pool_day_data(req.pool_id, days=history_days)
    except GraphQueryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if len(daily) < 2:
        raise HTTPException(status_code=422, detail="Histórico diário insuficiente para analisar a faixa")

    pool = await pools_service.get_pool_detail(req.pool_id)
    if pool is None:
        raise HTTPException(status_code=404, detail="Pool não encontrado")

    daily_closes = [d.close for d in daily]
    fees_period = sum(d.fees_usd for d in daily)

    try:
        fee_apr = ind.fee_apr_full_range(fees_period, pool.total_value_locked_usd, period_days=max(len(daily), 1))
        # Anualizada a partir dos fechamentos DIÁRIOS -- ver comentário em
        # schemas.RangeAnalysisResponse.annualized_volatility.
        vol = ind.annualized_volatility(daily_closes)

        candidates: list[tuple[str, float, float]] = [("custom", req.price_lower, req.price_upper)]
        if req.include_suggested:
            for key, k in _SUGGESTED_VOLATILITY_K.items():
                candidates.append((key, *ind.suggest_range_by_volatility(current_price, vol, history_days, k)))
            candidates.append(("realized", *ind.suggest_range_from_realized(daily_closes)))

        scenarios: list[RangeScenario] = []
        for key, price_lower, price_upper in candidates:
            try:
                replay = ind.replay_range_against_history(
                    hourly_prices=hourly_closes,
                    entry_price=entry_price,
                    price_lower=price_lower,
                    price_upper=price_upper,
                    fee_apr_full_range_value=fee_apr,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=f"Faixa '{key}' inválida: {exc}") from exc
            breakeven = ind.breakeven_days(replay.estimated_position_apr, replay.impermanent_loss)
            scenarios.append(
                RangeScenario(
                    key=key,
                    price_lower=price_lower,
                    price_upper=price_upper,
                    in_range_fraction=replay.in_range_fraction,
                    concentration_multiplier=replay.concentration_multiplier,
                    estimated_position_apr=replay.estimated_position_apr,
                    impermanent_loss=replay.impermanent_loss,
                    breakeven_days=breakeven,
                    entry_price=replay.entry_price,
                    end_price=replay.end_price,
                )
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RangeAnalysisResponse(
        current_price=current_price,
        entry_price=entry_price,
        history_days=history_days,
        fee_apr_full_range=fee_apr,
        annualized_volatility=vol,
        sample_count=len(hourly_closes),
        daily_history=daily,
        scenarios=scenarios,
    )
