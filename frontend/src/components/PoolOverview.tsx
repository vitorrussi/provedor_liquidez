import type { PoolIndicatorsResponse } from '../api/types';
import { etherscanTokenUrl, formatFeeTier, formatPercent, formatPrice, formatUsd, truncateAddress } from '../format';

interface Props {
  data: PoolIndicatorsResponse;
}

export function PoolOverview({ data }: Props) {
  const { pool, fee_apr_full_range_30d, annualized_volatility_30d } = data;

  return (
    <div className="card">
      <div className="card__header">
        <h2>
          {pool.token0.symbol} / {pool.token1.symbol}
          <span className="badge">{formatFeeTier(pool.fee_tier)}</span>
        </h2>
      </div>

      <div className="stat-grid">
        <div className="stat">
          <span className="stat__label">TVL</span>
          <span className="stat__value">{formatUsd(pool.total_value_locked_usd)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Volume (total histórico)</span>
          <span className="stat__value">{formatUsd(pool.volume_usd)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">
            Preço ({pool.token1.symbol} em {pool.token0.symbol})
          </span>
          <span className="stat__value">{formatPrice(pool.token0_price)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">APR de taxas (full-range, 30d)</span>
          <span className="stat__value stat__value--highlight">{formatPercent(fee_apr_full_range_30d)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Volatilidade anualizada (30d)</span>
          <span className="stat__value">{formatPercent(annualized_volatility_30d)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Transações</span>
          <span className="stat__value">{pool.tx_count.toLocaleString('pt-BR')}</span>
        </div>
      </div>
      <div className="token-addresses">
        <span className="muted">
          Contrato {pool.token0.symbol}:{' '}
          <a href={etherscanTokenUrl(pool.token0.id)} target="_blank" rel="noopener noreferrer">
            {truncateAddress(pool.token0.id)}
          </a>
        </span>
        <span className="muted">
          Contrato {pool.token1.symbol}:{' '}
          <a href={etherscanTokenUrl(pool.token1.id)} target="_blank" rel="noopener noreferrer">
            {truncateAddress(pool.token1.id)}
          </a>
        </span>
      </div>
      <p className="footnote">
        O APR acima é o retorno de uma posição em faixa completa (full-range). Uma posição concentrada
        rende mais enquanto o preço estiver dentro da sua faixa — veja o simulador de faixa abaixo.
        Qualquer um pode criar um token com nome/símbolo parecido com o de uma empresa ou moeda
        conhecida — antes de confiar num pool, confira o endereço do contrato acima contra a fonte
        oficial do projeto (não confie só no nome).
      </p>
    </div>
  );
}
