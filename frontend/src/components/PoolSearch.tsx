import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { AssetIndexRow, PoolSummary } from '../api/types';
import { formatFeeTier, formatPercent, formatRatio, formatUsd, protocolLabel } from '../format';
import { SortableHeader } from './SortableHeader';

type SortKey = 'pair' | 'tvl' | 'vol1d' | 'vol30d' | 'vol1dTvl' | 'apr' | 'volume';
type SortDirection = 'asc' | 'desc';

const DEFAULT_DIRECTION: Record<SortKey, SortDirection> = {
  pair: 'asc',
  tvl: 'desc',
  vol1d: 'desc',
  vol30d: 'desc',
  vol1dTvl: 'desc',
  apr: 'desc',
  volume: 'desc',
};

// Teto de resultados por busca -- cada busca é 1-3 chamadas ao gateway do Graph
// (a lista + até 2 páginas dos dados diários agregados) independente desse
// número, mas um valor muito alto deixaria a lista longa demais. Se bater
// nesse número, pode ter mais pools que não estão sendo mostrados.
const SEARCH_LIMIT = 50;

export function PoolSearch() {
  const navigate = useNavigate();
  // O termo buscado fica na URL (?q=...) pra sobreviver ao botão voltar do
  // navegador quando se abre um pool e volta -- sem isso, voltar da página do
  // pool perderia os resultados e obrigaria a buscar de novo.
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get('q') ?? '';

  const [query, setQuery] = useState(urlQuery);
  const [results, setResults] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('tvl');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [hideZeroVolume, setHideZeroVolume] = useState(false);

  // Sugestões de autocomplete vêm do índice local (SQLite, ver
  // backend/app/local_db.py), não do gateway do Graph -- por isso pode
  // consultar a cada tecla digitada sem custar cota. Se o índice nunca foi
  // construído (ver /assets), a lista de sugestões só fica vazia; a busca
  // "de verdade" (Enter/botão Buscar) continua funcionando normalmente.
  const [suggestions, setSuggestions] = useState<AssetIndexRow[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 1) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .suggestAssets(term, 8)
        .then((rows) => {
          if (!cancelled) setSuggestions(rows);
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    setQuery(urlQuery);
    if (!urlQuery.trim()) {
      setResults([]);
      setSearched(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .searchPools(urlQuery.trim(), SEARCH_LIMIT)
      .then((pools) => {
        if (cancelled) return;
        setResults(pools);
        setSearched(true);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Falha ao buscar pools');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [urlQuery]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection(DEFAULT_DIRECTION[key]);
    }
  }

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setShowSuggestions(false);
    setSearchParams({ q: query.trim() });
  }

  function handleSuggestionSelect(asset: AssetIndexRow) {
    setQuery(asset.symbol);
    setShowSuggestions(false);
    setSearchParams({ q: asset.symbol });
  }

  function handleSelect(pool: PoolSummary) {
    navigate(`/pool/${encodeURIComponent(pool.id)}`);
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
        case 'vol1d':
          return sign * (a.volume_1d_usd - b.volume_1d_usd);
        case 'vol30d':
          return sign * (a.volume_30d_usd - b.volume_30d_usd);
        case 'vol1dTvl':
          return sign * (a.volume_1d_over_tvl - b.volume_1d_over_tvl);
        case 'apr':
          return sign * (a.apr_pool_30d - b.apr_pool_30d);
        case 'volume':
          return sign * (a.volume_usd - b.volume_usd);
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
      <div className="pool-search__nav">
        <Link to="/assets" className="btn btn--secondary">
          Ver todos os ativos
        </Link>
        <Link to="/pools" className="btn btn--secondary">
          Ver todas as pools
        </Link>
      </div>

      <form onSubmit={handleSearch} className="pool-search__form">
        <div className="pool-search__input-wrap">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setShowSuggestions(true)}
            onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
            placeholder="Buscar por token (ex: ETH, USDC, WBTC)"
            className="pool-search__input"
            autoComplete="off"
          />
          {showSuggestions && suggestions.length > 0 && (
            <ul className="pool-search__suggestions">
              {suggestions.map((asset) => (
                <li key={asset.id}>
                  <button type="button" onMouseDown={() => handleSuggestionSelect(asset)}>
                    <span className="pool-search__suggestion-symbol">{asset.symbol}</span>
                    <span className="pool-search__suggestion-name muted">{asset.name}</span>
                    {asset.category && <span className="badge">{asset.category}</span>}
                    <span className="pool-search__suggestion-tvl muted">{formatUsd(asset.total_tvl_usd)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
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
            Busca em Uniswap v2, v3 e v4, e em Aerodrome Slipstream (Base). A busca casa qualquer token
            cujo símbolo ou nome contenha o termo. O mesmo par pode aparecer mais de uma vez: em
            v3/v4/Aerodrome cada taxa (0,01% / 0,05% / 0,30% / 1%) é um pool com contrato e liquidez
            próprios; em v2 a taxa é sempre fixa em 0,30% (não existe conceito de faixa de taxa nem de
            liquidez concentrada). "Vol. 30 dias" e "APR da pool" são estimados a partir dos últimos ~30
            dias de histórico — a Uniswap não expõe
            separadamente quanto da taxa vai para o LP e quanto vai para o protocolo, então o que vemos
            é sempre a taxa total. Para v2, como o subgraph não indexa taxas separadamente, elas são
            estimadas como 0,30% do volume diário. Ao abrir um pool v2, a página mostra uma versão
            simplificada (sem simulador de faixa e sem gráfico de preço, já que v2 não tem liquidez
            concentrada nem histórico OHLC indexado).
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

          <div className="pool-table">
            <div className="pool-list__header">
              <span className="pool-list__rank">#</span>
              <SortableHeader
                className="pool-list__pair"
                label="Pool"
                sortKey="pair"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="TVL"
                title="Valor total travado no pool agora"
                sortKey="tvl"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="Vol. 1d"
                title="Volume de trocas do dia mais recente com dados"
                sortKey="vol1d"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="Vol. 30 dias"
                title="Soma do volume de trocas dos últimos ~30 dias"
                sortKey="vol30d"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="Vol. 1d/TVL"
                title="Volume de 1 dia dividido pelo TVL -- giro diário do capital do pool"
                sortKey="vol1dTvl"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="APR da pool"
                title="APR de taxas full-range dos últimos ~30 dias (taxas / TVL, anualizado) -- não é o APR de uma posição concentrada"
                sortKey="apr"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="Volume (total)"
                title="Volume de trocas acumulado desde a criação do pool (não é 24h)"
                sortKey="volume"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
            </div>

            <ul className="pool-list">
              {sortedResults.map((pool, index) => {
                const noVolume = pool.volume_usd === 0;
                return (
                  <li key={pool.id} className="pool-list__item" onClick={() => handleSelect(pool)}>
                    <span className="pool-list__rank muted">{index + 1}</span>
                    <span className="pool-list__pair">
                      <span className="pool-list__pair-main">
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
                      <span className="pool-list__pair-sub muted">
                        {protocolLabel(pool.protocol)} · {formatFeeTier(pool.fee_tier)}
                        {pool.protocol === 'v2' && ' (fixa)'}
                      </span>
                    </span>
                    <span className="pool-list__col">{formatUsd(pool.total_value_locked_usd)}</span>
                    <span className="pool-list__col">{formatUsd(pool.volume_1d_usd)}</span>
                    <span className="pool-list__col">{formatUsd(pool.volume_30d_usd)}</span>
                    <span className="pool-list__col">{formatRatio(pool.volume_1d_over_tvl)}</span>
                    <span className="pool-list__col">{formatPercent(pool.apr_pool_30d)}</span>
                    <span className="pool-list__col">{formatUsd(pool.volume_usd)}</span>
                  </li>
                );
              })}
            </ul>
          </div>

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
