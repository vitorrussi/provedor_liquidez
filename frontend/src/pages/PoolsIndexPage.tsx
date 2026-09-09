import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { IndexStatusResponse, PoolIndexRow, Protocol } from '../api/types';
import { IndexRefreshBar } from '../components/IndexRefreshBar';
import { SortableHeader } from '../components/SortableHeader';
import { formatFeeTier, formatUsd, protocolLabel } from '../format';

type SortKey = 'token0_symbol' | 'protocol' | 'fee_tier' | 'total_value_locked_usd' | 'volume_usd' | 'created_at';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE_OPTIONS = [25, 50, 100];
const PROTOCOLS: Protocol[] = ['v2', 'v3', 'v4', 'aerodrome'];

export function PoolsIndexPage() {
  const navigate = useNavigate();

  const [status, setStatus] = useState<IndexStatusResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [tokenAInput, setTokenAInput] = useState('');
  const [tokenBInput, setTokenBInput] = useState('');
  const [tokenA, setTokenA] = useState('');
  const [tokenB, setTokenB] = useState('');
  const [protocol, setProtocol] = useState('');
  const [exact, setExact] = useState(false);
  const [hideInactive, setHideInactive] = useState(false);
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
      setTokenA(tokenAInput.trim());
      setTokenB(tokenBInput.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [qInput, tokenAInput, tokenBInput]);

  useEffect(() => {
    api
      .getIndexStatus()
      .then(setStatus)
      .catch(() => {});
  }, []);

  const pairMode = Boolean(tokenA && tokenB);

  function fetchPage(currentOffset: number) {
    return api.listPoolsIndex({
      q: pairMode ? undefined : q || undefined,
      tokenA: pairMode ? tokenA : undefined,
      tokenB: pairMode ? tokenB : undefined,
      exact,
      hideInactive,
      protocol: protocol || undefined,
      sort: sortKey,
      order: sortDirection,
      limit: pageSize,
      offset: currentOffset,
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
  }, [q, tokenA, tokenB, exact, hideInactive, protocol, pageSize, sortKey, sortDirection, offset]);

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
          disabled={pairMode}
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
        <label>
          Token A (par)
          <input type="text" value={tokenAInput} onChange={(e) => setTokenAInput(e.target.value)} placeholder="ex: ETH" />
        </label>
        <label>
          Token B (par)
          <input type="text" value={tokenBInput} onChange={(e) => setTokenBInput(e.target.value)} placeholder="ex: TSLA" />
        </label>
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
          Buscando pools com {tokenA} e {tokenB} (em qualquer ordem) — o filtro de texto acima fica desativado
          enquanto os dois campos de par estiverem preenchidos.
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
