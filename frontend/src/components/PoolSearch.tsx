import { useState } from 'react';
import { api, ApiError } from '../api/client';
import type { PoolSummary } from '../api/types';
import { formatFeeTier, formatUsd } from '../format';

interface Props {
  onSelect: (pool: PoolSummary) => void;
}

export function PoolSearch({ onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const pools = await api.searchPools(query.trim());
      setResults(pools);
      setSearched(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao buscar pools');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="pool-search">
      <form onSubmit={handleSearch} className="pool-search__form">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar por token (ex: ETH, USDC, WBTC)"
          className="pool-search__input"
        />
        <button type="submit" disabled={loading} className="btn btn--primary">
          {loading ? 'Buscando...' : 'Buscar'}
        </button>
      </form>

      {error && <p className="error-text">{error}</p>}

      {searched && !loading && results.length === 0 && !error && (
        <p className="muted">Nenhum pool encontrado para "{query}".</p>
      )}

      {results.length > 0 && (
        <ul className="pool-list">
          {results.map((pool) => (
            <li key={pool.id} className="pool-list__item" onClick={() => onSelect(pool)}>
              <span className="pool-list__pair">
                {pool.token0.symbol} / {pool.token1.symbol}
              </span>
              <span className="pool-list__fee">{formatFeeTier(pool.fee_tier)}</span>
              <span className="pool-list__tvl">TVL {formatUsd(pool.total_value_locked_usd)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
