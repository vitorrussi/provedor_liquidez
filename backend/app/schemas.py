from pydantic import BaseModel


class Token(BaseModel):
    id: str
    symbol: str
    name: str
    decimals: int


class PoolSummary(BaseModel):
    id: str
    protocol: str = "v3"  # "v2" | "v3" | "v4" | "aerodrome"
    token0: Token
    token1: Token
    fee_tier: int
    total_value_locked_usd: float
    volume_usd: float
    # Agregados dos últimos ~30 dias (poolDayData). 0 quando o pool não tem
    # dados nesse período (pool novo/inativo) -- ver docstring de
    # services/pools.py sobre como são calculados em lote.
    volume_1d_usd: float = 0.0
    volume_7d_usd: float = 0.0
    volume_30d_usd: float = 0.0
    volume_1d_over_tvl: float = 0.0
    apr_pool_7d: float = 0.0
    apr_pool_30d: float = 0.0


class PoolDetail(PoolSummary):
    tick: int | None
    token0_price: float
    token1_price: float
    fees_usd_lifetime: float
    tx_count: int
    created_at: int | None = None  # unix timestamp de criação do pool/pair
    # Se True, total_value_locked_usd foi recalculado a partir do saldo real
    # on-chain dos tokens (balanceOf do contrato do pool) em vez do campo
    # totalValueLockedUSD do subgraph, que pode divergir do real -- ver
    # onchain_client.py e CLAUDE.md. Se False, a chamada on-chain falhou (RPC
    # fora do ar, timeout etc.) e o valor é o do subgraph mesmo, sem garantia.
    tvl_verified_onchain: bool = False


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
    fee_apr_full_range_7d: float
    fee_apr_full_range_30d: float
    annualized_volatility_7d: float
    annualized_volatility_30d: float
    volume_7d_usd: float
    volume_30d_usd: float


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
