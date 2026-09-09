import { useMemo, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { PoolSummary } from '../api/types';
import { formatFeeTier, formatUsd } from '../format';

interface Props {
  onSelect: (pool: PoolSummary) => void;
}

type SortKey = 'pair' | 'fee' | 'tvl' | 'volume';
type SortDirection = 'asc' | 'desc';

const DEFAULT_DIRECTION: Record<SortKey, SortDirection> = {
  pair: 'asc',
  fee: 'asc',
  tvl: 'desc',
  volume: 'desc',
};

// Teto de resultados por busca -- cada busca é 1 chamada ao gateway do Graph
// independente desse número, mas um valor muito alto deixaria a lista longa
// demais. Se bater nesse número, pode ter mais pools que não estão sendo
// mostrados (ver aviso abaixo da lista).
const SEARCH_LIMIT = 50;

export function PoolSearch({ onSelect }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('tvl');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [hideZeroVolume, setHideZeroVolume] = useState(false);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection(DEFAULT_DIRECTION[key]);
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const pools = await api.searchPools(query.trim(), SEARCH_LIMIT);
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
    const sign = sortDirection === 'asc' ? 1 : -1;
    sorted.sort((a, b) => {
      switch (sortKey) {
        case 'tvl':
          return sign * (a.total_value_locked_usd - b.total_value_locked_usd);
        case 'volume':
          return sign * (a.volume_usd - b.volume_usd);
        case 'fee':
          return sign * (a.fee_tier - b.fee_tier);
        case 'pair':
          return sign * `${a.token0.symbol}/${a.token1.symbol}`.localeCompare(`${b.token0.symbol}/${b.token1.symbol}`);
        default:
          return 0;
      }
    });
    return sorted;
  }, [results, sortKey, sortDirection, hideZeroVolume]);

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

          {zeroVolumeCount > 0 && (
            <div className="pool-list__controls">
              <label className="pool-list__toggle">
                <input
                  type="checkbox"
                  checked={hideZeroVolume}
                  onChange={(e) => setHideZeroVolume(e.target.checked)}
                />
                Ocultar sem volume histórico ({zeroVolumeCount})
              </label>
            </div>
          )}

          <div className="pool-list__header">
            <SortableHeader
              className="pool-list__pair"
              label="Pool"
              sortKey="pair"
              activeKey={sortKey}
              direction={sortDirection}
              onSort={handleSort}
            />
            <SortableHeader
              className="pool-list__fee"
              label="Taxa"
              title="Taxa cobrada em cada troca, dividida entre os LPs"
              sortKey="fee"
              activeKey={sortKey}
              direction={sortDirection}
              onSort={handleSort}
            />
            <SortableHeader
              className="pool-list__tvl"
              label="TVL"
              title="Valor total travado no pool agora"
              sortKey="tvl"
              activeKey={sortKey}
              direction={sortDirection}
              onSort={handleSort}
            />
            <SortableHeader
              className="pool-list__volume"
              label="Volume (total)"
              title="Volume de trocas acumulado desde a criação do pool (não é 24h)"
              sortKey="volume"
              activeKey={sortKey}
              direction={sortDirection}
              onSort={handleSort}
            />
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

          {results.length === SEARCH_LIMIT && (
            <p className="footnote">
              Mostrando os {SEARCH_LIMIT} pools de maior TVL que combinam com "{query}" — pode haver mais que não
              estão sendo exibidos.
            </p>
          )}
        </>
      )}
    </div>
  );
}

interface SortableHeaderProps {
  className: string;
  label: string;
  title?: string;
  sortKey: SortKey;
  activeKey: SortKey;
  direction: SortDirection;
  onSort: (key: SortKey) => void;
}

function SortableHeader({ className, label, title, sortKey, activeKey, direction, onSort }: SortableHeaderProps) {
  const active = sortKey === activeKey;
  return (
    <button
      type="button"
      className={`pool-list__header-btn ${className} ${active ? 'pool-list__header-btn--active' : ''}`}
      title={title}
      onClick={() => onSort(sortKey)}
    >
      {label}
      <span className="pool-list__sort-arrow">{active ? (direction === 'asc' ? '▲' : '▼') : ''}</span>
    </button>
  );
}
