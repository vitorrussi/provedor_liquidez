import { useMemo, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { PoolSummary } from '../api/types';
import { formatFeeTier, formatUsd } from '../format';

interface Props {
  onSelect: (pool: PoolSummary) => void;
}

type SortKey = 'tvl' | 'volume' | 'fee';

const SORT_LABELS: Record<SortKey, string> = {
  tvl: 'TVL',
  volume: 'Volume (total)',
  fee: 'Taxa',
};

export function PoolSearch({ onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('tvl');
  const [hideZeroVolume, setHideZeroVolume] = useState(false);

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

  const zeroVolumeCount = useMemo(() => results.filter((p) => p.volume_usd === 0).length, [results]);

  const sortedResults = useMemo(() => {
    const visible = hideZeroVolume ? results.filter((p) => p.volume_usd > 0) : results;
    const sorted = [...visible];
    sorted.sort((a, b) => {
      if (sortKey === 'tvl') return b.total_value_locked_usd - a.total_value_locked_usd;
      if (sortKey === 'volume') return b.volume_usd - a.volume_usd;
      return a.fee_tier - b.fee_tier;
    });
    return sorted;
  }, [results, sortKey, hideZeroVolume]);

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
        <>
          <p className="footnote pool-search__hint">
            A busca casa qualquer token cujo símbolo contenha o termo — por isso "ETH" também traz
            tokens com "ETH" no meio do nome (ex: WETH, ou tokens sem relação nenhuma com Ethereum
            que só têm essas letras no símbolo). O mesmo par de tokens pode aparecer mais de uma vez:
            cada taxa (0,01% / 0,05% / 0,30% / 1%) é um pool com contrato e liquidez próprios, a
            Uniswap não mistura eles.
          </p>

          <div className="pool-list__controls">
            <div className="pool-list__sort">
              <span className="muted">Ordenar por:</span>
              {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
                <button
                  key={key}
                  type="button"
                  className={`sort-btn ${sortKey === key ? 'sort-btn--active' : ''}`}
                  onClick={() => setSortKey(key)}
                >
                  {SORT_LABELS[key]}
                </button>
              ))}
            </div>
            {zeroVolumeCount > 0 && (
              <label className="pool-list__toggle">
                <input
                  type="checkbox"
                  checked={hideZeroVolume}
                  onChange={(e) => setHideZeroVolume(e.target.checked)}
                />
                Ocultar sem volume histórico ({zeroVolumeCount})
              </label>
            )}
          </div>

          <div className="pool-list__header">
            <span className="pool-list__pair">Pool</span>
            <span className="pool-list__fee" title="Taxa cobrada em cada troca, dividida entre os LPs">
              Taxa
            </span>
            <span className="pool-list__tvl" title="Valor total travado no pool agora">
              TVL
            </span>
            <span className="pool-list__volume" title="Volume de trocas acumulado desde a criação do pool (não é 24h)">
              Volume (total)
            </span>
          </div>

          <ul className="pool-list">
            {sortedResults.map((pool) => {
              const noVolume = pool.volume_usd === 0;
              return (
                <li key={pool.id} className="pool-list__item" onClick={() => onSelect(pool)}>
                  <span className="pool-list__pair">
                    {pool.token0.symbol} / {pool.token1.symbol}
                    {noVolume && (
                      <span
                        className="badge badge--warning"
                        title="Este pool nunca teve volume de trocas registrado — TVL alto com volume zero costuma indicar liquidez artificial/token sem negociação real, não necessariamente uma oportunidade."
                      >
                        sem atividade
                      </span>
                    )}
                  </span>
                  <span className="pool-list__fee">{formatFeeTier(pool.fee_tier)}</span>
                  <span className="pool-list__tvl">{formatUsd(pool.total_value_locked_usd)}</span>
                  <span className="pool-list__volume">{formatUsd(pool.volume_usd)}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
