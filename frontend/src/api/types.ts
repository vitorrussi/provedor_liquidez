export interface Token {
  id: string;
  symbol: string;
  name: string;
  decimals: number;
}

export type Protocol = 'v2' | 'v3' | 'v4' | 'aerodrome' | 'polygon' | 'avalanche';
export type Chain = 'mainnet' | 'base' | 'polygon' | 'avalanche';

export interface PoolSummary {
  id: string;
  protocol: Protocol;
  chain: Chain;
  token0: Token;
  token1: Token;
  fee_tier: number;
  total_value_locked_usd: number;
  volume_usd: number;
  volume_1d_usd: number;
  volume_7d_usd: number;
  volume_30d_usd: number;
  volume_1d_over_tvl: number;
  apr_pool_7d: number;
  apr_pool_30d: number;
}

export interface PoolDetail extends PoolSummary {
  tick: number | null;
  token0_price: number;
  token1_price: number;
  fees_usd_lifetime: number;
  tx_count: number;
  created_at: number | null;
  tvl_verified_onchain: boolean;
}

export interface DayDataPoint {
  date: number;
  tvl_usd: number;
  volume_usd: number;
  fees_usd: number;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface HourDataPoint {
  period_start_unix: number;
  close: number;
  tvl_usd: number;
  volume_usd: number;
}

export interface PoolIndicatorsResponse {
  pool: PoolDetail;
  fee_apr_full_range_7d: number;
  fee_apr_full_range_30d: number;
  annualized_volatility_7d: number;
  annualized_volatility_30d: number;
  volume_7d_usd: number;
  volume_30d_usd: number;
}

export interface ImpermanentLossRequest {
  entry_price: number;
  current_price: number;
  price_lower: number;
  price_upper: number;
}

export interface ImpermanentLossResponse {
  impermanent_loss: number;
  impermanent_loss_full_range_equivalent: number;
  concentration_multiplier: number;
}

export interface RangeAnalysisRequest {
  pool_id: string;
  price_lower: number;
  price_upper: number;
  entry_price?: number;
  investment_usd?: number;
  history_days?: number;
  include_suggested?: boolean;
}

export type RangeScenarioKey = 'custom' | 'narrow' | 'medium' | 'wide' | 'realized';

export interface RangeScenario {
  key: RangeScenarioKey;
  price_lower: number;
  price_upper: number;
  in_range_fraction: number;
  concentration_multiplier: number;
  estimated_position_apr: number;
  impermanent_loss: number;
  breakeven_days: number | null;
  entry_price: number;
  end_price: number;
}

export interface RangeAnalysisResponse {
  current_price: number;
  // Preço de entrada e janela histórica REALMENTE usados no replay (já
  // resolvidos/clampados no backend) -- use estes, não o que foi enviado no
  // request, pra qualquer cálculo derivado (ex: escalar APR por dias).
  entry_price: number;
  history_days: number;
  fee_apr_full_range: number;
  annualized_volatility: number;
  sample_count: number;
  daily_history: DayDataPoint[];
  scenarios: RangeScenario[];
}

export interface GraphUsageResponse {
  month: string;
  used: number;
  limit: number;
  remaining: number;
}

export interface AssetTopPair {
  symbol: string;
  tvl_usd: number;
}

export interface AssetIndexRow {
  id: string;
  chain: Chain;
  address: string;
  symbol: string;
  name: string;
  decimals: number;
  category: string | null;
  pools_count: number;
  total_tvl_usd: number;
  total_volume_usd: number;
  top_pairs: AssetTopPair[];
  // null quando nenhuma pool desse ativo tem a métrica medida (ativo só
  // aparece em pools v2, sem poolDayData indexado -- ver CLAUDE.md).
  volume_1d_usd: number | null;
  volume_30d_usd: number | null;
  volume_1d_over_tvl: number | null;
}

export interface AssetIndexResponse {
  items: AssetIndexRow[];
  total: number;
}

export interface PoolIndexRow {
  id: string;
  protocol: Protocol;
  chain: Chain;
  token0_symbol: string;
  token0_address: string;
  token1_symbol: string;
  token1_address: string;
  fee_tier: number;
  total_value_locked_usd: number;
  volume_usd: number;
  created_at: number | null;
  // null para pools v2 (sem poolDayData indexado -- ver CLAUDE.md).
  volume_1d_usd: number | null;
  volume_30d_usd: number | null;
  volume_1d_over_tvl: number | null;
  apr_pool_30d: number | null;
}

export interface PoolIndexResponse {
  items: PoolIndexRow[];
  total: number;
}

export interface IndexStatusResponse {
  updated_at: number | null;
  min_tvl_usd: number | null;
  total_assets: number;
  total_pools: number;
  protocol_errors: Record<string, string>;
}
