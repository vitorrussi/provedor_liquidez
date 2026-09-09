import { useNavigate } from 'react-router-dom';
import type { PoolSummary } from '../api/types';
import { formatFeeTier, formatPercent, formatUsd, protocolLabel } from '../format';

interface Props {
  pools: PoolSummary[];
}

export function RelatedPools({ pools }: Props) {
  const navigate = useNavigate();
  if (pools.length === 0) return null;

  return (
    <div className="card">
      <div className="card__header">
        <h3>Outras pools deste par</h3>
      </div>
      <p className="muted">
        Mesmo par de tokens em outras taxas ou protocolos — compare onde a liquidez está concentrada antes de
        escolher onde entrar.
      </p>
      <ul className="related-pools">
        {pools.map((p) => (
          <li key={p.id} className="related-pools__item" onClick={() => navigate(`/pool/${encodeURIComponent(p.id)}`)}>
            <span className="related-pools__label">
              {protocolLabel(p.protocol)} · {formatFeeTier(p.fee_tier)}
              {p.protocol === 'v2' && ' (fixa)'}
            </span>
            <span className="related-pools__stat">
              <span className="muted">TVL</span> {formatUsd(p.total_value_locked_usd)}
            </span>
            <span className="related-pools__stat">
              <span className="muted">APR 30d</span> {formatPercent(p.apr_pool_30d)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
