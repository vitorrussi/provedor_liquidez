import { useState } from 'react';
import { api, ApiError } from '../api/client';
import type { PoolDetail, RangeSimulationResponse } from '../api/types';
import { formatPercent, formatPrice } from '../format';

interface Props {
  pool: PoolDetail;
}

export function RangeSimulator({ pool }: Props) {
  const currentPrice = pool.token0_price;
  const [priceLower, setPriceLower] = useState(currentPrice * 0.85);
  const [priceUpper, setPriceUpper] = useState(currentPrice * 1.15);
  const [historyDays, setHistoryDays] = useState(30);
  const [result, setResult] = useState<RangeSimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSimulate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await api.simulateRange({
        pool_id: pool.id,
        price_lower: priceLower,
        price_upper: priceUpper,
        history_days: historyDays,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao simular faixa');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <div className="card__header">
        <h3>Simulador de faixa (liquidez concentrada)</h3>
      </div>
      <p className="muted">
        Estimativa histórica: usa os preços horários reais dos últimos N dias para ver quanto tempo o
        preço ficaria dentro da sua faixa. Não é um backtest de execução (ignora gas e liquidez
        concorrente).
      </p>

      <form onSubmit={handleSimulate} className="form-grid">
        <label>
          Faixa mínima
          <input
            type="number"
            step="any"
            value={priceLower}
            onChange={(e) => setPriceLower(Number(e.target.value))}
          />
        </label>
        <label>
          Faixa máxima
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
            min={1}
            max={30}
            value={historyDays}
            onChange={(e) => setHistoryDays(Number(e.target.value))}
          />
        </label>
        <button type="submit" disabled={loading} className="btn btn--primary form-grid__submit">
          {loading ? 'Simulando...' : 'Simular'}
        </button>
      </form>

      {error && <p className="error-text">{error}</p>}

      {result && (
        <>
          <div className="stat-grid stat-grid--compact">
            <div className="stat">
              <span className="stat__label">Tempo dentro da faixa</span>
              <span className="stat__value">{formatPercent(result.in_range_fraction, 1)}</span>
            </div>
            <div className="stat">
              <span className="stat__label">Multiplicador de concentração</span>
              <span className="stat__value">{result.concentration_multiplier.toFixed(2)}x</span>
            </div>
            <div className="stat">
              <span className="stat__label">APR estimado da posição</span>
              <span className="stat__value stat__value--highlight">
                {formatPercent(result.estimated_position_apr)}
              </span>
            </div>
            <div className="stat">
              <span className="stat__label">IL no preço final</span>
              <span className={`stat__value ${result.impermanent_loss < 0 ? 'stat__value--negative' : ''}`}>
                {formatPercent(result.impermanent_loss)}
              </span>
            </div>
            <div className="stat">
              <span className="stat__label">Dias para taxas cobrirem o IL</span>
              <span className="stat__value">
                {result.breakeven_days !== null ? `${result.breakeven_days.toFixed(1)} dias` : '—'}
              </span>
            </div>
            <div className="stat">
              <span className="stat__label">Preço entrada → final</span>
              <span className="stat__value">
                {formatPrice(result.entry_price)} → {formatPrice(result.end_price)}
              </span>
            </div>
          </div>
          <p className="footnote">Amostra: {result.sample_count} horas de preço.</p>
        </>
      )}
    </div>
  );
}
