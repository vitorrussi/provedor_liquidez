import type { DayDataPoint, PoolDetail } from '../api/types';
import { explorerTokenUrl, formatDate, formatFeeTier, formatPercent, formatPrice, formatUsd, truncateAddress } from '../format';
import { PriceRangeBar } from './PriceRangeBar';

interface IndicatorStats {
  fee_apr_7d: number;
  fee_apr_30d: number;
  annualized_volatility_7d?: number;
  annualized_volatility_30d?: number;
  volume_7d_usd: number;
  volume_30d_usd: number;
}

interface Props {
  pool: PoolDetail;
  indicators: IndicatorStats | null;
  indicatorsNote: string | null;
  history: DayDataPoint[];
}

export function PoolOverview({ pool, indicators, indicatorsNote, history }: Props) {
  const estimatedSuffix = pool.protocol === 'v2' ? ' — estimado' : '';
  const rangeLow = history.length > 0 ? Math.min(...history.map((d) => d.low)) : null;
  const rangeHigh = history.length > 0 ? Math.max(...history.map((d) => d.high)) : null;

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
          <span className="stat__label">
            TVL{' '}
            {pool.tvl_verified_onchain ? (
              <span
                className="badge"
                title="Recalculado a partir do saldo real dos tokens no contrato do pool (on-chain), não do campo do subgraph -- que pode divergir bastante do real em alguns pools."
              >
                verificado on-chain
              </span>
            ) : (
              <span
                className="badge badge--warning"
                title="A verificação on-chain falhou (RPC indisponível no momento) -- este valor vem direto do subgraph da Uniswap e pode divergir do real em alguns pools."
              >
                não verificado
              </span>
            )}
          </span>
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
          <span className="stat__label">Taxas geradas (total histórico){estimatedSuffix}</span>
          <span className="stat__value">{formatUsd(pool.fees_usd_lifetime)}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Transações</span>
          <span className="stat__value">{pool.tx_count.toLocaleString('pt-BR')}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Tick atual</span>
          <span className="stat__value">{pool.tick ?? '—'}</span>
        </div>
        <div className="stat">
          <span className="stat__label">Criado em</span>
          <span className="stat__value">{pool.created_at !== null ? formatDate(pool.created_at) : '—'}</span>
        </div>
      </div>

      {rangeLow !== null && rangeHigh !== null && (
        <PriceRangeBar low={rangeLow} high={rangeHigh} current={pool.token0_price} />
      )}

      <div className="overview__section-header">
        <h3>Desempenho recente</h3>
      </div>

      {indicators ? (
        <div className="stat-grid stat-grid--compact">
          <div className="stat">
            <span className="stat__label">APR de taxas — 7d{estimatedSuffix}</span>
            <span className="stat__value stat__value--highlight">{formatPercent(indicators.fee_apr_7d)}</span>
          </div>
          <div className="stat">
            <span className="stat__label">APR de taxas — 30d{estimatedSuffix}</span>
            <span className="stat__value stat__value--highlight">{formatPercent(indicators.fee_apr_30d)}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Volume — 7d</span>
            <span className="stat__value">{formatUsd(indicators.volume_7d_usd)}</span>
          </div>
          <div className="stat">
            <span className="stat__label">Volume — 30d</span>
            <span className="stat__value">{formatUsd(indicators.volume_30d_usd)}</span>
          </div>
          {indicators.annualized_volatility_7d !== undefined && (
            <div className="stat">
              <span className="stat__label">Volatilidade anualizada — 7d</span>
              <span className="stat__value">{formatPercent(indicators.annualized_volatility_7d)}</span>
            </div>
          )}
          {indicators.annualized_volatility_30d !== undefined && (
            <div className="stat">
              <span className="stat__label">Volatilidade anualizada — 30d</span>
              <span className="stat__value">{formatPercent(indicators.annualized_volatility_30d)}</span>
            </div>
          )}
        </div>
      ) : (
        <p className="stat__value--muted">indisponível</p>
      )}

      {indicatorsNote && (
        <p className="status-box status-box--note">
          Não deu para calcular APR/volatilidade dos últimos dias para este pool: {indicatorsNote} Isso é comum
          em pools com pouquíssimo TVL/negociação — os dados básicos acima (TVL, preço, taxas, transações) ainda
          são os valores reais do contrato.
        </p>
      )}

      <div className="token-addresses">
        <span className="muted">
          Contrato {pool.token0.symbol}:{' '}
          <a href={explorerTokenUrl(pool.token0.id, pool.protocol)} target="_blank" rel="noopener noreferrer">
            {truncateAddress(pool.token0.id)}
          </a>
        </span>
        <span className="muted">
          Contrato {pool.token1.symbol}:{' '}
          <a href={explorerTokenUrl(pool.token1.id, pool.protocol)} target="_blank" rel="noopener noreferrer">
            {truncateAddress(pool.token1.id)}
          </a>
        </span>
      </div>
      <p className="footnote">
        {pool.protocol === 'v2'
          ? 'Uniswap v2 não tem liquidez concentrada: toda posição é full-range por natureza, então não há simulação de faixa nem taxa configurável para este pool. '
          : 'O APR acima é o retorno de uma posição em faixa completa (full-range). Uma posição concentrada rende mais enquanto o preço estiver dentro da sua faixa — veja a análise avançada de faixa abaixo. '}
        Qualquer um pode criar um token com nome/símbolo parecido com o de uma empresa ou moeda
        conhecida — antes de confiar num pool, confira o endereço do contrato acima contra a fonte
        oficial do projeto (não confie só no nome).
      </p>
    </div>
  );
}
