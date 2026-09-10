import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { IndexStatusResponse, PoolIndexRow, Protocol } from '../api/types';
import { IndexRefreshBar } from '../components/IndexRefreshBar';
import { RangeFilter } from '../components/RangeFilter';
import { SortableHeader } from '../components/SortableHeader';
import { TokenMultiSelect } from '../components/TokenMultiSelect';
import { formatFeeTier, formatRatio, formatUsd, protocolLabel } from '../format';

type SortKey =
  | 'token0_symbol'
  | 'protocol'
  | 'fee_tier'
  | 'total_value_locked_usd'
  | 'volume_usd'
  | 'created_at'
  | 'volume_1d_usd'
  | 'volume_30d_usd'
  | 'volume_1d_over_tvl'
  | 'apr_pool_30d';
type SortDirection = 'asc' | 'desc';

// String vazia == sem filtro (undefined na chamada à API); Number(str) de
// string vazia daria 0, que é um mínimo/máximo válido diferente de "sem
// filtro" -- por isso essa conversão explícita em vez de `Number(v) || undefined`.
function toFilterNumber(value: string): number | undefined {
  return value.trim() === '' ? undefined : Number(value);
}

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const PROTOCOLS: Protocol[] = ['v2', 'v3', 'v4', 'aerodrome'];

export function PoolsIndexPage() {
  const navigate = useNavigate();

  const [status, setStatus] = useState<IndexStatusResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  // Chips selecionados (ver TokenMultiSelect) -- diferente de `qInput`/
  // `minVol1dInput`/etc, não precisam de debounce: selecionar um chip já é
  // uma ação discreta (clique), não texto sendo digitado, então aplica o
  // filtro na hora.
  const [tokenA, setTokenA] = useState<string[]>([]);
  const [tokenB, setTokenB] = useState<string[]>([]);
  const [protocol, setProtocol] = useState('');
  const [exact, setExact] = useState(false);
  const [hideInactive, setHideInactive] = useState(false);

  const [minVol1dInput, setMinVol1dInput] = useState('');
  const [maxVol1dInput, setMaxVol1dInput] = useState('');
  const [minVol30dInput, setMinVol30dInput] = useState('');
  const [maxVol30dInput, setMaxVol30dInput] = useState('');
  const [minVol1dTvlInput, setMinVol1dTvlInput] = useState('');
  const [maxVol1dTvlInput, setMaxVol1dTvlInput] = useState('');
  const [minAprInput, setMinAprInput] = useState('');
  const [maxAprInput, setMaxAprInput] = useState('');
  const [minVol1d, setMinVol1d] = useState('');
  const [maxVol1d, setMaxVol1d] = useState('');
  const [minVol30d, setMinVol30d] = useState('');
  const [maxVol30d, setMaxVol30d] = useState('');
  const [minVol1dTvl, setMinVol1dTvl] = useState('');
  const [maxVol1dTvl, setMaxVol1dTvl] = useState('');
  const [minApr, setMinApr] = useState('');
  const [maxApr, setMaxApr] = useState('');

  const [pageSize, setPageSize] = useState(50);
  const [sortKey, setSortKey] = useState<SortKey>('total_value_locked_usd');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<PoolIndexRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(qInput.trim());
      setMinVol1d(minVol1dInput);
      setMaxVol1d(maxVol1dInput);
      setMinVol30d(minVol30dInput);
      setMaxVol30d(maxVol30dInput);
      setMinVol1dTvl(minVol1dTvlInput);
      setMaxVol1dTvl(maxVol1dTvlInput);
      setMinApr(minAprInput);
      setMaxApr(maxAprInput);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [
    qInput,
    minVol1dInput,
    maxVol1dInput,
    minVol30dInput,
    maxVol30dInput,
    minVol1dTvlInput,
    maxVol1dTvlInput,
    minAprInput,
    maxAprInput,
  ]);

  useEffect(() => {
    api
      .getIndexStatus()
      .then(setStatus)
      .catch(() => {});
  }, []);

  const pairMode = tokenA.length > 0 && tokenB.length > 0;
  const hasTokenFilter = tokenA.length > 0 || tokenB.length > 0;

  function fetchPage(currentOffset: number) {
    return api.listPoolsIndex({
      q: hasTokenFilter ? undefined : q || undefined,
      tokenA: tokenA.length > 0 ? tokenA : undefined,
      tokenB: tokenB.length > 0 ? tokenB : undefined,
      exact,
      hideInactive,
      protocol: protocol || undefined,
      sort: sortKey,
      order: sortDirection,
      limit: pageSize,
      offset: currentOffset,
      minVolume1dUsd: toFilterNumber(minVol1d),
      maxVolume1dUsd: toFilterNumber(maxVol1d),
      minVolume30dUsd: toFilterNumber(minVol30d),
      maxVolume30dUsd: toFilterNumber(maxVol30d),
      minVolume1dOverTvl: toFilterNumber(minVol1dTvl),
      maxVolume1dOverTvl: toFilterNumber(maxVol1dTvl),
      // APR digitado em % (ex: "5" = 5%) -- convertido pra fração porque é
      // assim que apr_pool_30d é armazenado/filtrado no backend (mesma
      // convenção de formatPercent em format.ts).
      minAprPool30d: toFilterNumber(minApr) !== undefined ? Number(minApr) / 100 : undefined,
      maxAprPool30d: toFilterNumber(maxApr) !== undefined ? Number(maxApr) / 100 : undefined,
    });
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchPage(offset)
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Falha ao carregar a lista de pools');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    q,
    tokenA,
    tokenB,
    exact,
    hideInactive,
    protocol,
    pageSize,
    sortKey,
    sortDirection,
    offset,
    minVol1d,
    maxVol1d,
    minVol30d,
    maxVol30d,
    minVol1dTvl,
    maxVol1dTvl,
    minApr,
    maxApr,
  ]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection(key === 'token0_symbol' || key === 'protocol' ? 'asc' : 'desc');
    }
    setOffset(0);
  }

  async function handleRefresh() {
    setRefreshing(true);
    setRefreshError(null);
    try {
      const newStatus = await api.refreshIndex();
      setStatus(newStatus);
      setOffset(0);
      const res = await fetchPage(0);
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setRefreshError(err instanceof ApiError ? err.message : 'Falha ao atualizar o índice');
    } finally {
      setRefreshing(false);
    }
  }

  const page = Math.floor(offset / pageSize) + 1;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="index-page">
      <Link to="/" className="pool-page__back">
        ← Voltar à busca
      </Link>

      <h2>Todas as pools</h2>
      <p className="muted">
        Lista local de todas as pools com TVL/reserva relevante (Uniswap v2/v3/v4 e Aerodrome Slipstream). Clique
        numa linha pra abrir o detalhe da pool.
      </p>

      <IndexRefreshBar status={status} refreshing={refreshing} onRefresh={handleRefresh} />
      {refreshError && <p className="error-text">{refreshError}</p>}

      <div className="index-page__controls">
        <input
          type="text"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Filtrar por símbolo do token"
          className="pool-search__input"
          disabled={hasTokenFilter}
        />
        <select
          value={protocol}
          onChange={(e) => {
            setProtocol(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">Todos os protocolos</option>
          {PROTOCOLS.map((p) => (
            <option key={p} value={p}>
              {protocolLabel(p)}
            </option>
          ))}
        </select>
      </div>

      <div className="advanced-filters advanced-filters--inline">
        <TokenMultiSelect
          label="Token A (par)"
          placeholder="buscar ativo..."
          selected={tokenA}
          onChange={(v) => {
            setTokenA(v);
            setOffset(0);
          }}
        />
        <TokenMultiSelect
          label="Token B (par)"
          placeholder="buscar ativo..."
          selected={tokenB}
          onChange={(v) => {
            setTokenB(v);
            setOffset(0);
          }}
        />
        <label className="advanced-filters__checkbox">
          <input
            type="checkbox"
            checked={exact}
            onChange={(e) => {
              setExact(e.target.checked);
              setOffset(0);
            }}
          />
          Sigla exata
        </label>
        <label className="advanced-filters__checkbox">
          <input
            type="checkbox"
            checked={hideInactive}
            onChange={(e) => {
              setHideInactive(e.target.checked);
              setOffset(0);
            }}
          />
          Ocultar sem atividade
        </label>
        <RangeFilter
          label="Volume 1d (USD)"
          min={minVol1dInput}
          max={maxVol1dInput}
          onMinChange={setMinVol1dInput}
          onMaxChange={setMaxVol1dInput}
        />
        <RangeFilter
          label="Volume 30d (USD)"
          min={minVol30dInput}
          max={maxVol30dInput}
          onMinChange={setMinVol30dInput}
          onMaxChange={setMaxVol30dInput}
        />
        <RangeFilter
          label="Vol. 1d/TVL"
          title="Volume de 1 dia dividido pelo TVL"
          min={minVol1dTvlInput}
          max={maxVol1dTvlInput}
          onMinChange={setMinVol1dTvlInput}
          onMaxChange={setMaxVol1dTvlInput}
        />
        <RangeFilter
          label="APR da pool (%)"
          title="APR de taxas full-range dos últimos ~30 dias"
          min={minAprInput}
          max={maxAprInput}
          onMinChange={setMinAprInput}
          onMaxChange={setMaxAprInput}
        />
        <label>
          Itens por página
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setOffset(0);
            }}
          >
            {PAGE_SIZE_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
      {pairMode && (
        <p className="footnote">
          Buscando pools com qualquer combinação entre [{tokenA.join(', ')}] e [{tokenB.join(', ')}] (em qualquer
          ordem) — o filtro de texto acima fica desativado enquanto houver algum token selecionado.
        </p>
      )}
      {hasTokenFilter && !pairMode && (
        <p className="footnote">
          Buscando pools com qualquer um de [{[...tokenA, ...tokenB].join(', ')}] (em qualquer posição) — o filtro
          de texto acima fica desativado enquanto houver algum token selecionado.
        </p>
      )}
      {(minVol1d || maxVol1d || minVol30d || maxVol30d || minVol1dTvl || maxVol1dTvl || minApr || maxApr) && (
        <p className="footnote">
          Volume 1d/30d, Vol. 1d/TVL e APR não são medidos para pools Uniswap v2 (o subgraph não indexa esse
          histórico por pool) — com qualquer um desses filtros preenchido, pools v2 ficam de fora da lista.
        </p>
      )}

      {error && <p className="error-text">{error}</p>}

      {!error && (
        <>
          <div className="pool-table">
            <div className="pool-list__header pool-list__header--pools-index">
              <SortableHeader className="pool-list__pair" label="Pool" sortKey="token0_symbol" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="Protocolo" sortKey="protocol" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="Taxa" sortKey="fee_tier" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="TVL" sortKey="total_value_locked_usd" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="Volume (total)" sortKey="volume_usd" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader
                className="pool-list__col"
                label="Vol. 1d"
                title="Volume de trocas do dia mais recente com dados -- não medido para v2"
                sortKey="volume_1d_usd"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="Vol. 30d"
                title="Soma do volume de trocas dos últimos ~30 dias -- não medido para v2"
                sortKey="volume_30d_usd"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader
                className="pool-list__col"
                label="Vol. 1d/TVL"
                title="Volume de 1 dia dividido pelo TVL -- não medido para v2"
                sortKey="volume_1d_over_tvl"
                activeKey={sortKey}
                direction={sortDirection}
                onSort={handleSort}
              />
              <SortableHeader className="pool-list__col" label="Criado em" sortKey="created_at" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
            </div>

            <ul className="pool-list">
              {items.map((pool) => (
                <li
                  key={pool.id}
                  className="pool-list__item pool-list__item--pools-index"
                  onClick={() => navigate(`/pool/${encodeURIComponent(pool.id)}`)}
                >
                  <span className="pool-list__pair">
                    <span className="pool-list__pair-main">
                      {pool.token0_symbol} / {pool.token1_symbol}
                    </span>
                    <span className="pool-list__pair-sub muted">{pool.chain === 'base' ? 'Base' : 'Ethereum'}</span>
                  </span>
                  <span className="pool-list__col">{protocolLabel(pool.protocol)}</span>
                  <span className="pool-list__col">{formatFeeTier(pool.fee_tier)}</span>
                  <span className="pool-list__col">{formatUsd(pool.total_value_locked_usd)}</span>
                  <span className="pool-list__col">{formatUsd(pool.volume_usd)}</span>
                  <span className="pool-list__col">{pool.volume_1d_usd !== null ? formatUsd(pool.volume_1d_usd) : '—'}</span>
                  <span className="pool-list__col">{pool.volume_30d_usd !== null ? formatUsd(pool.volume_30d_usd) : '—'}</span>
                  <span className="pool-list__col">
                    {pool.volume_1d_over_tvl !== null ? formatRatio(pool.volume_1d_over_tvl) : '—'}
                  </span>
                  <span className="pool-list__col muted">
                    {pool.created_at !== null ? new Date(pool.created_at * 1000).toLocaleDateString('pt-BR') : '—'}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {loading && <p className="muted">Carregando...</p>}
          {!loading && items.length === 0 && <p className="muted">Nenhuma pool encontrada.</p>}

          <div className="index-page__pagination">
            <button type="button" className="btn btn--secondary" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - pageSize))}>
              Anterior
            </button>
            <span className="muted">
              Página {page} de {totalPages} · {total.toLocaleString('pt-BR')} pools
            </span>
            <button
              type="button"
              className="btn btn--secondary"
              disabled={offset + pageSize >= total}
              onClick={() => setOffset((o) => o + pageSize)}
            >
              Próxima
            </button>
          </div>
        </>
      )}
    </div>
  );
}
