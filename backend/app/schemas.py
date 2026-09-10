from pydantic import BaseModel


class Token(BaseModel):
    id: str
    symbol: str
    name: str
    decimals: int


class PoolSummary(BaseModel):
    id: str
    protocol: str = "v3"  # "v2" | "v3" | "v4" | "aerodrome" | "polygon" | "avalanche"
    # "mainnet" | "base" | "polygon" | "avalanche" -- derivado de `protocol`
    # (ver services/pools.py::_PROTOCOL_CHAIN), não independente dele; existe
    # como campo próprio pro frontend não precisar reimplementar esse mapa
    # só pra mostrar a rede na lista de resultados.
    chain: str = "mainnet"
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


class RangeAnalysisRequest(BaseModel):
    pool_id: str
    price_lower: float
    price_upper: float
    # None -> o backend usa o preço no INÍCIO da janela histórica (ver
    # routers/indicators.py::analyze_range) -- mesmo default do simulador
    # antigo. Só passe um valor aqui se o usuário realmente digitou um preço
    # de entrada diferente; um valor igual ao preço atual zera o IL de todo
    # cenário (entry_price == end_price), o que parece bug mas é só a
    # definição de IL -- ver CLAUDE.md.
    entry_price: float | None = None
    investment_usd: float | None = None
    # Clampado no backend a _MAX_HISTORY_DAYS (routers/indicators.py) --
    # `poolHourDatas` é buscado com `first: history_days * 24`, e o Graph
    # limita `first` a 1000 (~41 dias de horas). Ver CLAUDE.md.
    history_days: int = 30
    include_suggested: bool = True


# Uma linha da tabela comparativa -- a faixa digitada pelo usuário ("custom") e,
# se `include_suggested`, as 4 faixas sugeridas (ver routers/indicators.py::
# analyze_range) rodam pelo mesmo replay histórico, então todas usam este
# mesmo formato.
class RangeScenario(BaseModel):
    key: str  # "custom" | "narrow" | "medium" | "wide" | "realized"
    price_lower: float
    price_upper: float
    in_range_fraction: float
    concentration_multiplier: float
    estimated_position_apr: float
    impermanent_loss: float
    breakeven_days: float | None
    entry_price: float
    end_price: float


class RangeAnalysisResponse(BaseModel):
    current_price: float
    # Preço de entrada REALMENTE usado no replay (já resolvido do default
    # quando o request não informou um) -- o frontend deve exibir/usar este
    # valor, não o que foi enviado no request, senão diverge do que os
    # `scenarios` abaixo de fato refletem.
    entry_price: float
    # Janela histórica REALMENTE usada (já clampada a _MAX_HISTORY_DAYS) --
    # mesmo motivo do campo acima: o request pode pedir mais do que o
    # backend aceitou.
    history_days: int
    fee_apr_full_range: float
    # Anualizada a partir dos fechamentos DIÁRIOS (mesma convenção de
    # routers/pools.py para os indicadores 7d/30d) -- não dos horários, ver
    # CLAUDE.md sobre o bug corrigido nesta mudança.
    annualized_volatility: float
    sample_count: int
    daily_history: list[DayDataPoint]
    scenarios: list[RangeScenario]


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


class AssetTopPair(BaseModel):
    symbol: str
    tvl_usd: float


class AssetIndexRow(BaseModel):
    id: str
    chain: str
    address: str
    symbol: str
    name: str
    decimals: int
    category: str | None
    pools_count: int
    total_tvl_usd: float
    total_volume_usd: float
    top_pairs: list[AssetTopPair]
    # None quando nenhuma pool desse ativo tem a métrica medida (ativo só
    # aparece em pools v2) -- ver local_db.py e services/index_builder.py.
    volume_1d_usd: float | None = None
    volume_30d_usd: float | None = None
    volume_1d_over_tvl: float | None = None


class AssetIndexResponse(BaseModel):
    items: list[AssetIndexRow]
    total: int


class PoolIndexRow(BaseModel):
    id: str
    protocol: str
    chain: str
    token0_symbol: str
    token0_address: str
    token1_symbol: str
    token1_address: str
    fee_tier: int
    total_value_locked_usd: float
    volume_usd: float
    created_at: int | None
    # None para pools v2 (sem poolDayData indexado com relação reversa no
    # subgraph) -- ver local_db.py e services/index_builder.py.
    volume_1d_usd: float | None = None
    volume_30d_usd: float | None = None
    volume_1d_over_tvl: float | None = None
    apr_pool_30d: float | None = None


class PoolIndexResponse(BaseModel):
    items: list[PoolIndexRow]
    total: int


class IndexStatusResponse(BaseModel):
    updated_at: int | None
    min_tvl_usd: float | None
    total_assets: int
    total_pools: int
    protocol_errors: dict[str, str]
