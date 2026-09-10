import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { PoolDetail, RangeAnalysisResponse, RangeScenario } from '../api/types';
import { RangeAnalysisChart, SCENARIO_META } from '../components/RangeAnalysisChart';
import { RangeAprIlChart } from '../components/RangeAprIlChart';
import { formatPercent, formatPrice, formatUsd } from '../format';

// Teto da janela histórica -- espelha
// backend/app/routers/indicators.py::_MAX_HISTORY_DAYS (limite real de ~41
// dias imposto pelo `first` do Graph nos dados horários, ver CLAUDE.md).
const MAX_HISTORY_DAYS = 41;

type SortKey = 'width' | 'in_range' | 'multiplier' | 'apr' | 'il' | 'breakeven' | 'net';

function scenarioWidthFraction(s: RangeScenario): number {
  return s.price_upper / s.price_lower - 1;
}

// `historyDays` deve vir de `result.history_days` (o que o backend REALMENTE
// usou), não do campo de formulário -- o backend clampa a MAX_HISTORY_DAYS, e
// editar o campo sem reenviar não deve reescrever esse cálculo com um valor
// que os cenários exibidos não refletem.
function scenarioNetUsd(s: RangeScenario, investment: number, historyDays: number): number {
  const feesUsd = investment * s.estimated_position_apr * (historyDays / 365);
  const ilUsd = investment * s.impermanent_loss;
  return feesUsd + ilUsd;
}

export function RangeAnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const poolId = id ? decodeURIComponent(id) : '';

  const [pool, setPool] = useState<PoolDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // String, não number: vazio = "deixa o backend decidir" (preço no início da
  // janela histórica, mesmo default do simulador antigo). Pré-preencher com o
  // preço atual pareceria razoável, mas faz entry_price == end_price na
  // maioria dos casos -- IL fica zerado pra todo cenário (impermanent_loss_v3
  // é 0 quando entrada == saída), matando justamente as colunas de IL/
  // break-even e a metade "vermelha" do gráfico APR×IL que a página existe
  // pra mostrar. Ver CLAUDE.md.
  const [entryPriceInput, setEntryPriceInput] = useState('');
  const [priceLower, setPriceLower] = useState(0);
  const [priceUpper, setPriceUpper] = useState(0);
  const [historyDays, setHistoryDays] = useState(30);
  const [investment, setInvestment] = useState(10000);
  const [includeSuggested, setIncludeSuggested] = useState(true);

  const [result, setResult] = useState<RangeAnalysisResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  const [sortKey, setSortKey] = useState<SortKey | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  useEffect(() => {
    if (!poolId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setPool(null);
    setResult(null);
    window.scrollTo({ top: 0 });

    api
      .getPool(poolId)
      .then((p) => {
        if (cancelled) return;
        setPool(p);
        setLoading(false);
        const currentPrice = p.token0_price;
        setPriceLower(currentPrice * 0.85);
        setPriceUpper(currentPrice * 1.15);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Falha ao carregar dados do pool');
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [poolId]);

  async function handleAnalyze(e: React.FormEvent) {
    e.preventDefault();
    if (!pool) return;
    setAnalyzing(true);
    setAnalyzeError(null);
    setSortKey(null);
    try {
      const trimmedEntryPrice = entryPriceInput.trim();
      const res = await api.analyzeRange({
        pool_id: pool.id,
        price_lower: priceLower,
        price_upper: priceUpper,
        entry_price: trimmedEntryPrice === '' ? undefined : Number(trimmedEntryPrice),
        investment_usd: investment,
        history_days: historyDays,
        include_suggested: includeSuggested,
      });
      setResult(res);
    } catch (err) {
      setAnalyzeError(err instanceof ApiError ? err.message : 'Falha ao analisar faixas');
    } finally {
      setAnalyzing(false);
    }
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  function sortValue(s: RangeScenario, key: SortKey): number {
    switch (key) {
      case 'width':
        return scenarioWidthFraction(s);
      case 'in_range':
        return s.in_range_fraction;
      case 'multiplier':
        return s.concentration_multiplier;
      case 'apr':
        return s.estimated_position_apr;
      case 'il':
        return s.impermanent_loss;
      case 'breakeven':
        return s.breakeven_days ?? Number.POSITIVE_INFINITY;
      case 'net':
        return scenarioNetUsd(s, investment, result?.history_days ?? historyDays);
    }
  }

  const scenarios = result?.scenarios ?? [];
  const sortedScenarios =
    sortKey === null
      ? scenarios
      : [...scenarios].sort((a, b) => {
          // "Sem break-even" (null -- IL já não-negativo, ou APR <= 0) não é
          // "infinitamente bom" nem "infinitamente ruim", é "não se aplica" --
          // fica sempre por último, nas duas direções, em vez de virar +Infinity
          // e colar no topo quando ordenado desc.
          if (sortKey === 'breakeven') {
            if (a.breakeven_days === null && b.breakeven_days === null) return 0;
            if (a.breakeven_days === null) return 1;
            if (b.breakeven_days === null) return -1;
          }
          return (sortValue(a, sortKey) - sortValue(b, sortKey)) * (sortDir === 'asc' ? 1 : -1);
        });

  function sortArrow(key: SortKey) {
    if (sortKey !== key) return '';
    return sortDir === 'asc' ? ' ▲' : ' ▼';
  }

  return (
    <div className="pool-page">
      <Link to={`/pool/${encodeURIComponent(poolId)}`} className="pool-page__back">
        ← Voltar ao pool
      </Link>

      {loading && <p className="status-box muted">Carregando dados do pool...</p>}
      {error && <p className="status-box status-box--error error-text">{error}</p>}

      {pool && !loading && pool.protocol === 'v2' && (
        <p className="status-box status-box--note">
          Análise avançada de faixa não se aplica a pools Uniswap v2 -- posições v2 são sempre
          full-range, sem faixa de liquidez concentrada pra simular.{' '}
          <Link to={`/pool/${encodeURIComponent(poolId)}`}>Voltar ao pool</Link>.
        </p>
      )}

      {pool && !loading && pool.protocol !== 'v2' && (
        <div className="dashboard">
          <div className="card">
            <div className="card__header">
              <h2>
                Análise de faixa — {pool.token0.symbol}/{pool.token1.symbol}
              </h2>
            </div>
            <p className="muted">
              Preço = {pool.token1.symbol} em {pool.token0.symbol}. Preço atual:{' '}
              {formatPrice(pool.token0_price)}
            </p>

            <form onSubmit={handleAnalyze} className="form-grid">
              <label>
                Preço de entrada (opcional)
                <input
                  type="number"
                  step="any"
                  placeholder="padrão: preço no início da janela"
                  value={entryPriceInput}
                  onChange={(e) => setEntryPriceInput(e.target.value)}
                />
              </label>
              <label>
                Dinheiro investido (USD)
                <input
                  type="number"
                  step="any"
                  min={0}
                  value={investment}
                  onChange={(e) => setInvestment(Number(e.target.value))}
                />
              </label>
              <label>
                Sua faixa — mínima
                <input
                  type="number"
                  step="any"
                  value={priceLower}
                  onChange={(e) => setPriceLower(Number(e.target.value))}
                />
              </label>
              <label>
                Sua faixa — máxima
                <input
                  type="number"
                  step="any"
                  value={priceUpper}
                  onChange={(e) => setPriceUpper(Number(e.target.value))}
                />
              </label>
              <label>
                Janela histórica (dias)
                <input
                  type="number"
                  min={7}
                  max={MAX_HISTORY_DAYS}
                  value={historyDays}
                  onChange={(e) => setHistoryDays(Number(e.target.value))}
                />
              </label>
              <label>
                <span>
                  <input
                    type="checkbox"
                    checked={includeSuggested}
                    onChange={(e) => setIncludeSuggested(e.target.checked)}
                  />{' '}
                  Incluir faixas sugeridas (volatilidade + variação realizada)
                </span>
              </label>
              <button type="submit" disabled={analyzing} className="btn btn--primary form-grid__submit">
                {analyzing ? 'Analisando...' : 'Analisar'}
              </button>
            </form>

            {analyzeError && <p className="error-text">{analyzeError}</p>}
          </div>

          {result && (
            <>
              <div className="card">
                <div className="card__header">
                  <h3>Resumo do período analisado</h3>
                </div>
                <div className="stat-grid stat-grid--compact">
                  <div className="stat">
                    <span className="stat__label">Preço atual</span>
                    <span className="stat__value">{formatPrice(result.current_price)}</span>
                  </div>
                  <div className="stat">
                    <span className="stat__label">Preço de entrada usado</span>
                    <span className="stat__value">{formatPrice(result.entry_price)}</span>
                  </div>
                  <div className="stat">
                    <span className="stat__label">Volatilidade anualizada</span>
                    <span className="stat__value">{formatPercent(result.annualized_volatility)}</span>
                  </div>
                  <div className="stat">
                    <span className="stat__label">APR do pool (full-range)</span>
                    <span className="stat__value">{formatPercent(result.fee_apr_full_range)}</span>
                  </div>
                  <div className="stat">
                    <span className="stat__label">Janela / amostra</span>
                    <span className="stat__value">
                      {result.history_days}d ({result.sample_count}h)
                    </span>
                  </div>
                </div>
              </div>

              <div className="card">
                <div className="card__header">
                  <h3>Comparação de faixas</h3>
                </div>
                <div className="scenario-table-wrap">
                  <table className="scenario-table">
                    <thead>
                      <tr>
                        <th>Faixa</th>
                        <th onClick={() => toggleSort('width')}>Largura{sortArrow('width')}</th>
                        <th onClick={() => toggleSort('in_range')}>Tempo em faixa{sortArrow('in_range')}</th>
                        <th onClick={() => toggleSort('multiplier')}>Concentração{sortArrow('multiplier')}</th>
                        <th onClick={() => toggleSort('apr')}>APR estimado{sortArrow('apr')}</th>
                        <th onClick={() => toggleSort('il')}>IL{sortArrow('il')}</th>
                        <th onClick={() => toggleSort('breakeven')}>Break-even{sortArrow('breakeven')}</th>
                        {investment > 0 && <th onClick={() => toggleSort('net')}>Líquido (USD){sortArrow('net')}</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedScenarios.map((s) => (
                        <tr key={s.key}>
                          <td>
                            <span className="scenario-table__key">
                              <span
                                className="scenario-table__dot"
                                style={{ background: SCENARIO_META[s.key].color }}
                              />
                              {SCENARIO_META[s.key].label}
                            </span>
                            <div className="muted">
                              {formatPrice(s.price_lower)} – {formatPrice(s.price_upper)}
                            </div>
                          </td>
                          <td>{formatPercent(scenarioWidthFraction(s), 0)}</td>
                          <td>{formatPercent(s.in_range_fraction, 1)}</td>
                          <td>{s.concentration_multiplier.toFixed(2)}x</td>
                          <td>{formatPercent(s.estimated_position_apr)}</td>
                          <td className={s.impermanent_loss < 0 ? 'error-text' : ''}>
                            {formatPercent(s.impermanent_loss)}
                          </td>
                          <td>{s.breakeven_days !== null ? `${s.breakeven_days.toFixed(1)}d` : '—'}</td>
                          {investment > 0 && (
                            <td>{formatUsd(scenarioNetUsd(s, investment, result.history_days))}</td>
                          )}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="footnote">
                  Estimativa histórica (não é um backtest de execução): usa preços horários reais dos últimos{' '}
                  {result.history_days} dias pra ver quanto tempo cada faixa ficaria dentro do range e qual APR de
                  taxas ela geraria. Ignora gas, rebalanceamento manual quando o preço sai da faixa, e liquidez
                  concorrente de outros LPs. "Líquido" = taxas estimadas + IL, sobre o investimento informado, sem
                  reinvestimento.
                </p>
              </div>

              <div className="dashboard__row">
                <RangeAnalysisChart
                  dailyHistory={result.daily_history}
                  scenarios={result.scenarios}
                  token0Symbol={pool.token0.symbol}
                  token1Symbol={pool.token1.symbol}
                />
                <RangeAprIlChart scenarios={result.scenarios} />
              </div>

              {includeSuggested && (
                <p className="footnote">
                  Faixas "estreita/média/larga" partem da volatilidade histórica anualizada e assumem
                  log-normalidade dos retornos -- uma aproximação, não uma previsão. A faixa "variação realizada"
                  não faz essa suposição: é literalmente o mínimo e o máximo de preço observado na janela
                  escolhida, então nunca fica maior que o que já aconteceu -- útil como contraponto às três
                  baseadas em volatilidade.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
