import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { AssetIndexRow, Protocol, PoolSummary } from '../api/types';
import {
  formatChainLabel,
  formatFeeTier,
  formatPercent,
  formatRatio,
  formatUsd,
  protocolLabel,
  protocolOptionLabel,
} from '../format';
import { RangeFilter } from './RangeFilter';
import { SortableHeader } from './SortableHeader';
import { TokenMultiSelect } from './TokenMultiSelect';

// String vazia == sem filtro -- ver mesma função em PoolsIndexPage.tsx.
function toFilterNumber(value: string): number | undefined {
  return value.trim() === '' ? undefined : Number(value);
}

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

const ALL_PROTOCOLS: Protocol[] = ['v2', 'v3', 'v4', 'aerodrome', 'polygon', 'avalanche', 'robinhood', 'solana'];
const RESULT_LIMIT_OPTIONS = [25, 50, 100];

export function PoolSearch() {
  const navigate = useNavigate();
  // O termo buscado fica na URL (?q=...) pra sobreviver ao botão voltar do
  // navegador quando se abre um pool e volta -- sem isso, voltar da página do
  // pool perderia os resultados e obrigaria a buscar de novo. Os filtros
  // avançados abaixo não vão pra URL (mesma decisão já tomada pra ordenação
  // de coluna) -- resetam ao voltar, igual ordenação já fazia.
  const [searchParams, setSearchParams] = useSearchParams();
  const urlQuery = searchParams.get('q') ?? '';

  const [query, setQuery] = useState(urlQuery);
  const [results, setResults] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searched, setSearched] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('tvl');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');

  // Filtros avançados -- só são "aplicados" de verdade quando o formulário é
  // submetido (searchTrigger incrementa e força a busca a rodar de novo
  // mesmo se o texto de `q` não mudou, ex: busca só por par de tokens).
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [tokenA, setTokenA] = useState<string[]>([]);
  const [tokenB, setTokenB] = useState<string[]>([]);
  const [exact, setExact] = useState(false);
  const [hideInactive, setHideInactive] = useState(false);
  const [minTvl, setMinTvl] = useState('');
  const [minVol1d, setMinVol1d] = useState('');
  const [maxVol1d, setMaxVol1d] = useState('');
  const [minVol30d, setMinVol30d] = useState('');
  const [maxVol30d, setMaxVol30d] = useState('');
  const [minVol1dTvl, setMinVol1dTvl] = useState('');
  const [maxVol1dTvl, setMaxVol1dTvl] = useState('');
  const [minApr, setMinApr] = useState('');
  const [maxApr, setMaxApr] = useState('');
  const [selectedProtocols, setSelectedProtocols] = useState<Protocol[]>([]);
  const [resultLimit, setResultLimit] = useState(50);
  const [searchTrigger, setSearchTrigger] = useState(0);

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
    const hasTokenFilter = tokenA.length > 0 || tokenB.length > 0;
    if (!urlQuery.trim() && !hasTokenFilter) {
      setResults([]);
      setSearched(false);
      // Também limpa `loading` -- sem isso, cancelar uma busca em andamento
      // (ex: apagar o termo e buscar de novo) deixava o botão travado em
      // "Buscando..." pra sempre: o `finally` da promise anterior é pulado
      // de propósito quando `cancelled` já é true, e esse early return nunca
      // tocava em `loading`.
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .searchPools({
        q: hasTokenFilter ? undefined : urlQuery.trim(),
        tokenA: tokenA.length > 0 ? tokenA : undefined,
        tokenB: tokenB.length > 0 ? tokenB : undefined,
        exact,
        hideInactive,
        minTvlUsd: minTvl ? Number(minTvl) : undefined,
        protocols: selectedProtocols.length > 0 ? selectedProtocols : undefined,
        limit: resultLimit,
        minVolume1dUsd: toFilterNumber(minVol1d),
        maxVolume1dUsd: toFilterNumber(maxVol1d),
        minVolume30dUsd: toFilterNumber(minVol30d),
        maxVolume30dUsd: toFilterNumber(maxVol30d),
        minVolume1dOverTvl: toFilterNumber(minVol1dTvl),
        maxVolume1dOverTvl: toFilterNumber(maxVol1dTvl),
        // APR digitado em % (ex: "5" = 5%) -- convertido pra fração, mesma
        // convenção de PoolsIndexPage.tsx.
        minAprPool30d: toFilterNumber(minApr) !== undefined ? Number(minApr) / 100 : undefined,
        maxAprPool30d: toFilterNumber(maxApr) !== undefined ? Number(maxApr) / 100 : undefined,
      })
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
    // Os filtros avançados só devem disparar uma nova busca quando o
    // formulário é submetido (searchTrigger), não a cada tecla digitada
    // neles -- por isso não entram na lista de dependências (o valor lido
    // é sempre o mais atual da renderização que disparou o efeito).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlQuery, searchTrigger]);

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
    const hasTokenFilter = tokenA.length > 0 || tokenB.length > 0;
    if (!query.trim() && !hasTokenFilter) return;
    setShowSuggestions(false);
    if (query.trim() === urlQuery) {
      // Se o texto de `q` não mudou (ex: só mexeu nos filtros avançados, ou
      // busca só por chips de token sem preencher `q`), a URL não muda --
      // precisa desse empurrão extra pro efeito de busca rodar de novo.
      setSearchTrigger((n) => n + 1);
    } else {
      setSearchParams(query.trim() ? { q: query.trim() } : {});
    }
  }

  function handleSuggestionSelect(asset: AssetIndexRow) {
    setQuery(asset.symbol);
    setShowSuggestions(false);
    setTokenA([]);
    setTokenB([]);
    setSearchParams({ q: asset.symbol });
  }

  function toggleProtocol(protocol: Protocol) {
    setSelectedProtocols((current) =>
      current.includes(protocol) ? current.filter((p) => p !== protocol) : [...current, protocol],
    );
  }

  function handleSelect(pool: PoolSummary) {
    navigate(`/pool/${encodeURIComponent(pool.id)}`);
  }

  const sortedResults = useMemo(() => {
    const sorted = [...results];
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
  }, [results, sortKey, sortDirection]);

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
                    <span className="badge">{formatChainLabel(asset.chain)}</span>
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

      <button type="button" className="advanced-filters__toggle" onClick={() => setShowAdvanced((v) => !v)}>
        {showAdvanced ? '▾' : '▸'} Filtros avançados
      </button>

      {showAdvanced && (
        <form onSubmit={handleSearch} className="advanced-filters">
          <div className="advanced-filters__row">
            <TokenMultiSelect label="Token A (par)" placeholder="buscar ativo..." selected={tokenA} onChange={setTokenA} />
            <TokenMultiSelect label="Token B (par)" placeholder="buscar ativo..." selected={tokenB} onChange={setTokenB} />
          </div>
          <p className="footnote advanced-filters__hint">
            Digite pra ver sugestões e clique pra selecionar — dá pra escolher vários de cada lado. Preenchendo os
            dois, busca pools com qualquer combinação entre os dois grupos (em qualquer ordem) em vez de usar o
            campo de busca principal — ex: A = [ETH, BTC] + B = [USDC, USDT] acha pools de ETH ou BTC com USDC ou
            USDT. Preenchendo só um lado, busca pools com qualquer um dos tokens selecionados.
          </p>

          <div className="advanced-filters__row">
            <label className="advanced-filters__checkbox">
              <input type="checkbox" checked={exact} onChange={(e) => setExact(e.target.checked)} />
              Sigla/nome exato (em vez de "contém")
            </label>
            <label className="advanced-filters__checkbox">
              <input type="checkbox" checked={hideInactive} onChange={(e) => setHideInactive(e.target.checked)} />
              Ocultar pools sem atividade
            </label>
          </div>

          <div className="advanced-filters__row">
            <label>
              TVL mínimo (USD)
              <input
                type="number"
                min={0}
                value={minTvl}
                onChange={(e) => setMinTvl(e.target.value)}
                placeholder="0"
              />
            </label>
            <label>
              Nº de resultados
              <select value={resultLimit} onChange={(e) => setResultLimit(Number(e.target.value))}>
                {RESULT_LIMIT_OPTIONS.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="advanced-filters__row">
            <RangeFilter
              label="Volume 1d (USD)"
              min={minVol1d}
              max={maxVol1d}
              onMinChange={setMinVol1d}
              onMaxChange={setMaxVol1d}
            />
            <RangeFilter
              label="Volume 30d (USD)"
              min={minVol30d}
              max={maxVol30d}
              onMinChange={setMinVol30d}
              onMaxChange={setMaxVol30d}
            />
            <RangeFilter
              label="Vol. 1d/TVL"
              title="Volume de 1 dia dividido pelo TVL"
              min={minVol1dTvl}
              max={maxVol1dTvl}
              onMinChange={setMinVol1dTvl}
              onMaxChange={setMaxVol1dTvl}
            />
            <RangeFilter
              label="APR da pool (%)"
              title="APR de taxas full-range dos últimos ~30 dias"
              min={minApr}
              max={maxApr}
              onMinChange={setMinApr}
              onMaxChange={setMaxApr}
            />
          </div>
          {(minVol1d || maxVol1d || minVol30d || maxVol30d || minVol1dTvl || maxVol1dTvl || minApr || maxApr) && (
            <p className="footnote advanced-filters__hint">
              Esses quatro filtros são aplicados depois de já ter buscado (dependem de dados históricos por pool) --
              com algum preenchido, a busca amplia o conjunto de candidatos além do "Nº de resultados" antes de
              filtrar, mas ainda assim pode não pegar pools de TVL bem baixo que também passariam no filtro.
            </p>
          )}

          <div className="advanced-filters__row">
            <span className="advanced-filters__label">Protocolos</span>
            <div className="advanced-filters__protocols">
              {ALL_PROTOCOLS.map((p) => (
                <label key={p} className="advanced-filters__checkbox">
                  <input
                    type="checkbox"
                    checked={selectedProtocols.includes(p)}
                    onChange={() => toggleProtocol(p)}
                  />
                  {protocolOptionLabel(p)}
                </label>
              ))}
            </div>
            <span className="footnote">Nenhum marcado = todos.</span>
          </div>

          <button type="submit" disabled={loading} className="btn btn--primary">
            {loading ? 'Buscando...' : 'Aplicar filtros'}
          </button>
        </form>
      )}

      {error && <p className="error-text">{error}</p>}

      {searched && !loading && results.length === 0 && !error && (
        <p className="muted">
          {query.trim() ? `Nenhum pool encontrado para "${query}".` : 'Nenhum pool encontrado para esses filtros.'}
        </p>
      )}

      {results.length > 0 && (
        <>
          <p className="footnote pool-search__hint">
            Busca em Uniswap v2, v3 e v4 (Ethereum), Aerodrome Slipstream (Base) e Uniswap v3 em Polygon e
            Avalanche. A busca casa qualquer token cujo símbolo ou nome contenha o termo. O mesmo par pode
            aparecer mais de uma vez: em qualquer protocolo v3-like (v3, v4, Aerodrome, Polygon, Avalanche)
            cada taxa (0,01% / 0,05% / 0,30% / 1%) é um pool com contrato e liquidez
            próprios; em v2 a taxa é sempre fixa em 0,30% (não existe conceito de faixa de taxa nem de
            liquidez concentrada). "Vol. 30 dias" e "APR da pool" são estimados a partir dos últimos ~30
            dias de histórico — a Uniswap não expõe
            separadamente quanto da taxa vai para o LP e quanto vai para o protocolo, então o que vemos
            é sempre a taxa total. Para v2, como o subgraph não indexa taxas separadamente, elas são
            estimadas como 0,30% do volume diário. Ao abrir um pool v2, a página mostra uma versão
            simplificada (sem análise avançada de faixa e sem gráfico de preço, já que v2 não tem liquidez
            concentrada nem histórico OHLC indexado).
          </p>

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
                        {formatChainLabel(pool.chain)} · {protocolLabel(pool.protocol)} · {formatFeeTier(pool.fee_tier)}
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

          {results.length === resultLimit && (
            <p className="footnote">
              Mostrando os {resultLimit} pools de maior TVL que combinam com essa busca — pode haver mais que não
              estão sendo exibidos (ajuste "Nº de resultados" nos filtros avançados).
            </p>
          )}
        </>
      )}
    </div>
  );
}
