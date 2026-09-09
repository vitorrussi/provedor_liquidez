from pydantic import BaseModel


class Token(BaseModel):
    id: str
    symbol: str
    name: str
    decimals: int


class PoolSummary(BaseModel):
    id: str
    token0: Token
    token1: Token
    fee_tier: int
    total_value_locked_usd: float
    volume_usd: float


class PoolDetail(PoolSummary):
    tick: int | None
    token0_price: float
    token1_price: float
    fees_usd_lifetime: float
    tx_count: int


class DayDataPoint(BaseModel):
    date: int  # unix timestamp (dia)
    tvl_usd: float
    volume_usd: float
    fees_usd: float
    open: float
    high: float
    low: float
    close: float


class HourDataPoint(BaseModel):
    period_start_unix: int
    close: float
    tvl_usd: float
    volume_usd: float


class ImpermanentLossRequest(BaseModel):
    entry_price: float
    current_price: float
    price_lower: float
    price_upper: float


class ImpermanentLossResponse(BaseModel):
    impermanent_loss: float
    impermanent_loss_full_range_equivalent: float
    concentration_multiplier: float


class RangeSimulationRequest(BaseModel):
    pool_id: str
    price_lower: float
    price_upper: float
    entry_price: float | None = None
    history_days: int = 30


class RangeSimulationResponse(BaseModel):
    in_range_fraction: float
    concentration_multiplier: float
    fee_apr_full_range: float
    estimated_position_apr: float
    impermanent_loss: float
    breakeven_days: float | None
    entry_price: float
    end_price: float
    sample_count: int
    annualized_volatility: float


class PoolIndicatorsResponse(BaseModel):
    pool: PoolDetail
    fee_apr_full_range_30d: float
    annualized_volatility_30d: float


class GraphUsageResponse(BaseModel):
    month: str
    used: int
    limit: int
    remaining: int


class GraphRequestLogEntry(BaseModel):
    timestamp: str
    operation: str
    variables: dict
    status: str
    duration_ms: float
    error: str | None = None
