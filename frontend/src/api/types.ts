export interface Token {
  id: string;
  symbol: string;
  name: string;
  decimals: number;
}

export interface PoolSummary {
  id: string;
  token0: Token;
  token1: Token;
  fee_tier: number;
  total_value_locked_usd: number;
  volume_usd: number;
}

export interface PoolDetail extends PoolSummary {
  tick: number | null;
  token0_price: number;
  token1_price: number;
  fees_usd_lifetime: number;
  tx_count: number;
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
  fee_apr_full_range_30d: number;
  annualized_volatility_30d: number;
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

export interface RangeSimulationRequest {
  pool_id: string;
  price_lower: number;
  price_upper: number;
  entry_price?: number;
  history_days?: number;
}

export interface RangeSimulationResponse {
  in_range_fraction: number;
  concentration_multiplier: number;
  fee_apr_full_range: number;
  estimated_position_apr: number;
  impermanent_loss: number;
  breakeven_days: number | null;
  entry_price: number;
  end_price: number;
  sample_count: number;
  annualized_volatility: number;
}
