import { useState } from 'react';
import { api, ApiError } from '../api/client';
import type { ImpermanentLossResponse, PoolDetail } from '../api/types';
import { formatPercent, formatPrice } from '../format';

interface Props {
  pool: PoolDetail;
}

export function ImpermanentLossCalculator({ pool }: Props) {
  const isV2 = pool.protocol === 'v2';
  const currentPrice = pool.token0_price;
  const [entryPrice, setEntryPrice] = useState(currentPrice);
  const [priceLower, setPriceLower] = useState(currentPrice * 0.8);
  const [priceUpper, setPriceUpper] = useState(currentPrice * 1.2);
  const [projectedPrice, setProjectedPrice] = useState(currentPrice);
  const [result, setResult] = useState<ImpermanentLossResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleCalculate(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // v2 não tem faixa (é sempre full-range) -- manda uma faixa larga
      // qualquer só pra satisfazer a validação do endpoint; o resultado
      // exibido para v2 usa impermanent_loss_full_range_equivalent, que
      // independe de price_lower/price_upper (é o IL clássico da v2).
      const res = await api.computeImpermanentLoss({
        entry_price: entryPrice,
        current_price: projectedPrice,
        price_lower: isV2 ? entryPrice * 0.5 : priceLower,
        price_upper: isV2 ? entryPrice * 2 : priceUpper,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Falha ao calcular');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card">
      <div className="card__header">
        <h3>Calculadora de Impermanent Loss</h3>
      </div>
      <p className="muted">
        Preço = {pool.token1.symbol} em {pool.token0.symbol}. Preço atual: {formatPrice(currentPrice)}
      </p>

      <form onSubmit={handleCalculate} className="form-grid">
        <label>
          Preço de entrada
          <input
            type="number"
            step="any"
            value={entryPrice}
            onChange={(e) => setEntryPrice(Number(e.target.value))}
          />
        </label>
        <label>
          Preço projetado (cenário)
          <input
            type="number"
            step="any"
            value={projectedPrice}
            onChange={(e) => setProjectedPrice(Number(e.target.value))}
          />
        </label>
        {!isV2 && (
          <>
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
          </>
        )}
        <button type="submit" disabled={loading} className="btn btn--primary form-grid__submit">
          {loading ? 'Calculando...' : 'Calcular IL'}
        </button>
      </form>

      {error && <p className="error-text">{error}</p>}

      {result && isV2 && (
        <div className="stat-grid stat-grid--compact">
          <div className="stat stat--wide">
            <span className="stat__label">Impermanent Loss (full-range)</span>
            <span
              className={`stat__value ${result.impermanent_loss_full_range_equivalent < 0 ? 'stat__value--negative' : ''}`}
            >
              {formatPercent(result.impermanent_loss_full_range_equivalent)}
            </span>
          </div>
        </div>
      )}
      {result && !isV2 && (
        <div className="stat-grid stat-grid--compact">
          <div className="stat">
            <span className="stat__label">IL na faixa escolhida</span>
            <span className={`stat__value ${result.impermanent_loss < 0 ? 'stat__value--negative' : ''}`}>
              {formatPercent(result.impermanent_loss)}
            </span>
          </div>
          <div className="stat">
            <span className="stat__label">IL equivalente em full-range (v2)</span>
            <span className="stat__value">{formatPercent(result.impermanent_loss_full_range_equivalent)}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Multiplicador de concentração</span>
            <span className="stat__value">{result.concentration_multiplier.toFixed(2)}x</span>
          </div>
        </div>
      )}
      <p className="footnote">
        {isV2
          ? 'Posições em Uniswap v2 são sempre full-range — não há faixa para escolher, o IL acima é o clássico 2·√r/(1+r) - 1.'
          : 'Faixas mais estreitas concentram capital (mais taxas enquanto o preço está dentro), mas também ampliam o IL quando o preço se move — compare sempre com as taxas estimadas no simulador de faixa.'}
      </p>
    </div>
  );
}
