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

export const api = {
  searchPools: (q: string, limit = 50) =>
    request<PoolSummary[]>(`/api/pools/search?q=${encodeURIComponent(q)}&limit=${limit}`),

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
    sort?: string;
    order?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
  }) => request<AssetIndexResponse>(`/api/index/assets?${buildQuery(params)}`),

  suggestAssets: (prefix: string, limit = 8) =>
    request<AssetIndexRow[]>(`/api/index/assets/suggest?prefix=${encodeURIComponent(prefix)}&limit=${limit}`),

  listPoolsIndex: (params: {
    q?: string;
    protocol?: string;
    sort?: string;
    order?: 'asc' | 'desc';
    limit?: number;
    offset?: number;
  }) => request<PoolIndexResponse>(`/api/index/pools?${buildQuery(params)}`),
};

function buildQuery(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') usp.set(key, String(value));
  }
  return usp.toString();
}

export { ApiError };
