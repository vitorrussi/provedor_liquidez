import type {
  AssetIndexResponse,
  AssetIndexRow,
  DayDataPoint,
  GraphUsageResponse,
  HourDataPoint,
  ImpermanentLossRequest,
  ImpermanentLossResponse,
  IndexStatusResponse,
  PoolDetail,
  PoolIndexResponse,
  PoolIndicatorsResponse,
  PoolSummary,
  RangeSimulationRequest,
  RangeSimulationResponse,
} from './types';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8787';

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `Erro ${response.status}`, response.status);
  }
  return response.json();
}

export interface PoolSearchParams {
  q?: string;
  // Chips selecionados no autocomplete (ver TokenMultiSelect.tsx) -- listas,
  // não texto livre; o backend casa por `symbol_in` (exato), não
  // contains/exact. Ver services/pools.py::search_pools.
  tokenA?: string[];
  tokenB?: string[];
  exact?: boolean;
  hideInactive?: boolean;
  minTvlUsd?: number;
  protocols?: string[];
  limit?: number;
  minVolume1dUsd?: number;
  maxVolume1dUsd?: number;
  minVolume30dUsd?: number;
  maxVolume30dUsd?: number;
  minVolume1dOverTvl?: number;
  maxVolume1dOverTvl?: number;
  minAprPool30d?: number;
  maxAprPool30d?: number;
}

export const api = {
  searchPools: (params: PoolSearchParams) =>
    request<PoolSummary[]>(
      `/api/pools/search?${buildQuery({
        q: params.q,
        token_a: params.tokenA,
        token_b: params.tokenB,
        exact: params.exact ? 'true' : undefined,
        hide_inactive: params.hideInactive ? 'true' : undefined,
        min_tvl_usd: params.minTvlUsd,
        protocol: params.protocols,
        limit: params.limit,
        min_volume_1d_usd: params.minVolume1dUsd,
        max_volume_1d_usd: params.maxVolume1dUsd,
        min_volume_30d_usd: params.minVolume30dUsd,
        max_volume_30d_usd: params.maxVolume30dUsd,
        min_volume_1d_over_tvl: params.minVolume1dOverTvl,
        max_volume_1d_over_tvl: params.maxVolume1dOverTvl,
        min_apr_pool_30d: params.minAprPool30d,
        max_apr_pool_30d: params.maxAprPool30d,
      })}`,
    ),

  getPool: (poolId: string) => request<PoolDetail>(`/api/pools/${encodeURIComponent(poolId)}`),

  getPoolIndicators: (poolId: string) =>
    request<PoolIndicatorsResponse>(`/api/pools/${encodeURIComponent(poolId)}/indicators`),

  getDailyHistory: (poolId: string, days = 30) =>
    request<DayDataPoint[]>(`/api/pools/${encodeURIComponent(poolId)}/history/daily?days=${days}`),

  getHourlyHistory: (poolId: string, hours = 168) =>
    request<HourDataPoint[]>(`/api/pools/${encodeURIComponent(poolId)}/history/hourly?hours=${hours}`),

  getRelatedPools: (poolId: string) => request<PoolSummary[]>(`/api/pools/${encodeURIComponent(poolId)}/related`),

  computeImpermanentLoss: (req: ImpermanentLossRequest) =>
    request<ImpermanentLossResponse>('/api/indicators/impermanent-loss', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  simulateRange: (req: RangeSimulationRequest) =>
    request<RangeSimulationResponse>('/api/indicators/range-simulate', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  getGraphUsage: () => request<GraphUsageResponse>('/api/graph-usage'),

  getIndexStatus: () => request<IndexStatusResponse>('/api/index/status'),

  refreshIndex: () => request<IndexStatusResponse>('/api/index/refresh', { method: 'POST' }),

  listAssets: (params: {
    q?: string;
    category?: string;
    exact?: boolean;
    hideInactive?: boolean;
    sort?: string;
    order?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
    minVolume1dUsd?: number;
    maxVolume1dUsd?: number;
    minVolume30dUsd?: number;
    maxVolume30dUsd?: number;
    minVolume1dOverTvl?: number;
    maxVolume1dOverTvl?: number;
    chain?: string;
  }) =>
    request<AssetIndexResponse>(
      `/api/index/assets?${buildQuery({
        q: params.q,
        category: params.category,
        exact: params.exact ? 'true' : undefined,
        hide_inactive: params.hideInactive ? 'true' : undefined,
        sort: params.sort,
        order: params.order,
        limit: params.limit,
        offset: params.offset,
        min_volume_1d_usd: params.minVolume1dUsd,
        max_volume_1d_usd: params.maxVolume1dUsd,
        min_volume_30d_usd: params.minVolume30dUsd,
        max_volume_30d_usd: params.maxVolume30dUsd,
        min_volume_1d_over_tvl: params.minVolume1dOverTvl,
        max_volume_1d_over_tvl: params.maxVolume1dOverTvl,
        chain: params.chain,
      })}`,
    ),

  suggestAssets: (prefix: string, limit = 8) =>
    request<AssetIndexRow[]>(`/api/index/assets/suggest?prefix=${encodeURIComponent(prefix)}&limit=${limit}`),

  listPoolsIndex: (params: {
    q?: string;
    tokenA?: string[];
    tokenB?: string[];
    exact?: boolean;
    hideInactive?: boolean;
    protocol?: string;
    sort?: string;
    order?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
    minVolume1dUsd?: number;
    maxVolume1dUsd?: number;
    minVolume30dUsd?: number;
    maxVolume30dUsd?: number;
    minVolume1dOverTvl?: number;
    maxVolume1dOverTvl?: number;
    minAprPool30d?: number;
    maxAprPool30d?: number;
    chain?: string;
  }) =>
    request<PoolIndexResponse>(
      `/api/index/pools?${buildQuery({
        q: params.q,
        token_a: params.tokenA,
        token_b: params.tokenB,
        exact: params.exact ? 'true' : undefined,
        hide_inactive: params.hideInactive ? 'true' : undefined,
        protocol: params.protocol,
        sort: params.sort,
        order: params.order,
        limit: params.limit,
        offset: params.offset,
        min_volume_1d_usd: params.minVolume1dUsd,
        max_volume_1d_usd: params.maxVolume1dUsd,
        min_volume_30d_usd: params.minVolume30dUsd,
        max_volume_30d_usd: params.maxVolume30dUsd,
        min_volume_1d_over_tvl: params.minVolume1dOverTvl,
        max_volume_1d_over_tvl: params.maxVolume1dOverTvl,
        min_apr_pool_30d: params.minAprPool30d,
        max_apr_pool_30d: params.maxAprPool30d,
        chain: params.chain,
      })}`,
    ),
};

type QueryValue = string | number | string[] | undefined;

function buildQuery(params: Record<string, QueryValue>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue;
    if (Array.isArray(value)) {
      for (const v of value) usp.append(key, v);
    } else {
      usp.set(key, String(value));
    }
  }
  return usp.toString();
}

export { ApiError };
