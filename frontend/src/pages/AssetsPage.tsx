import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { AssetIndexRow, IndexStatusResponse } from '../api/types';
import { IndexRefreshBar } from '../components/IndexRefreshBar';
import { SortableHeader } from '../components/SortableHeader';
import { ASSET_CATEGORIES, formatUsd } from '../format';

type SortKey = 'symbol' | 'name' | 'category' | 'pools_count' | 'total_tvl_usd';
type SortDirection = 'asc' | 'desc';

const PAGE_SIZE = 50;

export function AssetsPage() {
  const [status, setStatus] = useState<IndexStatusResponse | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('total_tvl_usd');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<AssetIndexRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQ(qInput.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [qInput]);

  function loadStatus() {
    api
      .getIndexStatus()
      .then(setStatus)
      .catch(() => {
        // Status é só informativo -- se falhar, a lista ainda tenta carregar normalmente.
      });
  }

  useEffect(() => {
    loadStatus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listAssets({ q: q || undefined, category: category || undefined, sort: sortKey, order: sortDirection, limit: PAGE_SIZE, offset })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setTotal(res.total);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Falha ao carregar a lista de ativos');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [q, category, sortKey, sortDirection, offset]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection(key === 'symbol' || key === 'name' || key === 'category' ? 'asc' : 'desc');
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
      const res = await api.listAssets({
        q: q || undefined, category: category || undefined, sort: sortKey, order: sortDirection, limit: PAGE_SIZE, offset: 0,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setRefreshError(err instanceof ApiError ? err.message : 'Falha ao atualizar o índice');
    } finally {
      setRefreshing(false);
    }
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="index-page">
      <Link to="/" className="pool-page__back">
        ← Voltar à busca
      </Link>

      <h2>Todos os ativos</h2>
      <p className="muted">
        Lista local dos ativos com TVL/reserva relevante em pelo menos uma pool indexada (Uniswap v2/v3/v4 e
        Aerodrome Slipstream). "Categoria" e "Principais pares" são uma aproximação de correlação: categoria vem de
        um mapeamento fixo por símbolo (stablecoins, ETH/LST, BTC, ...); principais pares é calculado a partir das
        próprias pools indexadas -- não é uma correlação de preço calculada.
      </p>

      <IndexRefreshBar status={status} refreshing={refreshing} onRefresh={handleRefresh} />
      {refreshError && <p className="error-text">{refreshError}</p>}

      <div className="index-page__controls">
        <input
          type="text"
          value={qInput}
          onChange={(e) => setQInput(e.target.value)}
          placeholder="Filtrar por símbolo ou nome"
          className="pool-search__input"
        />
        <select value={category} onChange={(e) => { setCategory(e.target.value); setOffset(0); }}>
          <option value="">Todas as categorias</option>
          {ASSET_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="error-text">{error}</p>}

      {!error && (
        <>
          <div className="pool-table">
            <div className="pool-list__header pool-list__header--assets">
              <SortableHeader className="pool-list__pair" label="Ativo" sortKey="symbol" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="Categoria" sortKey="category" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="Nº pools" sortKey="pools_count" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <SortableHeader className="pool-list__col" label="TVL total" title="Soma do TVL das pools onde esse ativo aparece" sortKey="total_tvl_usd" activeKey={sortKey} direction={sortDirection} onSort={handleSort} />
              <span className="pool-list__col">Principais pares</span>
            </div>

            <ul className="pool-list">
              {items.map((asset) => (
                <li key={asset.id} className="pool-list__item pool-list__item--assets pool-list__item--static">
                  <span className="pool-list__pair">
                    <span className="pool-list__pair-main">{asset.symbol}</span>
                    <span className="pool-list__pair-sub muted">
                      {asset.name} · {asset.chain === 'base' ? 'Base' : 'Ethereum'}
                    </span>
                  </span>
                  <span className="pool-list__col">{asset.category ?? '—'}</span>
                  <span className="pool-list__col">{asset.pools_count}</span>
                  <span className="pool-list__col">{formatUsd(asset.total_tvl_usd)}</span>
                  <span className="pool-list__col muted">
                    {asset.top_pairs.map((p) => p.symbol).join(', ') || '—'}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {loading && <p className="muted">Carregando...</p>}
          {!loading && items.length === 0 && <p className="muted">Nenhum ativo encontrado.</p>}

          <div className="index-page__pagination">
            <button type="button" className="btn btn--secondary" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}>
              Anterior
            </button>
            <span className="muted">
              Página {page} de {totalPages} · {total.toLocaleString('pt-BR')} ativos
            </span>
            <button
              type="button"
              className="btn btn--secondary"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset((o) => o + PAGE_SIZE)}
            >
              Próxima
            </button>
          </div>
        </>
      )}
    </div>
  );
}
