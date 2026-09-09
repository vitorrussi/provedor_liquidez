import { useEffect, useRef, useState } from 'react';
import './App.css';
import { api, ApiError } from './api/client';
import type { DayDataPoint, PoolIndicatorsResponse, PoolSummary } from './api/types';
import { ImpermanentLossCalculator } from './components/ImpermanentLossCalculator';
import { PoolOverview } from './components/PoolOverview';
import { PoolSearch } from './components/PoolSearch';
import { PriceChart } from './components/PriceChart';
import { RangeSimulator } from './components/RangeSimulator';
import { UsageBadge } from './components/UsageBadge';

function App() {
  const [selectedPool, setSelectedPool] = useState<PoolSummary | null>(null);
  const [indicators, setIndicators] = useState<PoolIndicatorsResponse | null>(null);
  const [history, setHistory] = useState<DayDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectedPool) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setIndicators(null);
    // O clique pode ter sido numa linha bem abaixo, no fim de uma lista longa de
    // resultados -- rola até o status pra deixar claro que algo aconteceu.
    statusRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });

    Promise.all([api.getPoolIndicators(selectedPool.id), api.getDailyHistory(selectedPool.id, 30)])
      .then(([ind, hist]) => {
        if (cancelled) return;
        setIndicators(ind);
        setHistory(hist);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Falha ao carregar dados do pool');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedPool]);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Provedor de Liquidez</h1>
        <p className="muted">Indicadores de risco e retorno para pools da Uniswap v3</p>
      </header>

      <main className="app__main">
        <PoolSearch onSelect={setSelectedPool} />

        <div ref={statusRef}>
          {loading && <p className="status-box muted">Carregando dados do pool...</p>}
          {error && <p className="status-box status-box--error error-text">{error}</p>}
        </div>

        {indicators && !loading && (
          <div className="dashboard">
            <PoolOverview data={indicators} />
            {history.length > 1 && (
              <PriceChart
                data={history}
                token0Symbol={indicators.pool.token0.symbol}
                token1Symbol={indicators.pool.token1.symbol}
              />
            )}
            <div className="dashboard__row">
              <ImpermanentLossCalculator pool={indicators.pool} />
              <RangeSimulator pool={indicators.pool} />
            </div>
          </div>
        )}
      </main>

      <footer className="app__footer">
        <p className="footnote">
          Ferramenta educacional. Dados via subgraph da Uniswap v3 (The Graph). Não é recomendação de
          investimento — DeFi envolve risco real de perda de capital.
        </p>
      </footer>

      <UsageBadge />
    </div>
  );
}

export default App;
