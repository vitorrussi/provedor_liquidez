import { useEffect, useRef, useState } from 'react';
import './App.css';
import { api, ApiError } from './api/client';
import type { DayDataPoint, PoolDetail, PoolSummary } from './api/types';
import { ImpermanentLossCalculator } from './components/ImpermanentLossCalculator';
import { PoolOverview } from './components/PoolOverview';
import { PoolSearch } from './components/PoolSearch';
import { PriceChart } from './components/PriceChart';
import { RangeSimulator } from './components/RangeSimulator';
import { UsageBadge } from './components/UsageBadge';

interface IndicatorStats {
  fee_apr_full_range_30d: number;
  annualized_volatility_30d: number;
}

function App() {
  const [selectedPool, setSelectedPool] = useState<PoolSummary | null>(null);
  const [pool, setPool] = useState<PoolDetail | null>(null);
  const [indicators, setIndicators] = useState<IndicatorStats | null>(null);
  const [indicatorsNote, setIndicatorsNote] = useState<string | null>(null);
  const [history, setHistory] = useState<DayDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const statusRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectedPool) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setPool(null);
    setIndicators(null);
    setIndicatorsNote(null);
    setHistory([]);
    // O clique pode ter sido numa linha bem abaixo, no fim de uma lista longa de
    // resultados -- rola até o status pra deixar claro que algo aconteceu.
    statusRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });

    // O detalhe básico do pool (TVL, preço, volume, taxas) quase sempre funciona --
    // é só um repasse dos campos do subgraph, sem contas que possam falhar. APR/
    // volatilidade e o histórico de preço já exigem dias de dados e podem não estar
    // disponíveis (pool novo ou pouco negociado) -- tratamos como "melhor esforço"
    // em vez de derrubar a tela inteira quando faltam.
    api
      .getPool(selectedPool.id)
      .then((p) => {
        if (cancelled) return;
        setPool(p);
        setLoading(false);

        api
          .getPoolIndicators(selectedPool.id)
          .then((ind) => {
            if (cancelled) return;
            setIndicators({
              fee_apr_full_range_30d: ind.fee_apr_full_range_30d,
              annualized_volatility_30d: ind.annualized_volatility_30d,
            });
          })
          .catch((err) => {
            if (cancelled) return;
            setIndicatorsNote(
              err instanceof ApiError
                ? err.message
                : 'Não foi possível calcular APR/volatilidade para este pool.',
            );
          });

        api
          .getDailyHistory(selectedPool.id, 30)
          .then((hist) => {
            if (!cancelled) setHistory(hist);
          })
          .catch(() => {
            // Sem histórico de preço -> o gráfico simplesmente não aparece.
          });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Falha ao carregar dados do pool');
        setLoading(false);
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

        {pool && !loading && (
          <div className="dashboard">
            <PoolOverview pool={pool} indicators={indicators} indicatorsNote={indicatorsNote} />
            {history.length > 1 && (
              <PriceChart data={history} token0Symbol={pool.token0.symbol} token1Symbol={pool.token1.symbol} />
            )}
            <div className="dashboard__row">
              <ImpermanentLossCalculator pool={pool} />
              <RangeSimulator pool={pool} />
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
