import { formatPrice } from '../format';

interface Props {
  low: number;
  high: number;
  current: number;
}

export function PriceRangeBar({ low, high, current }: Props) {
  if (high <= low) return null;
  const clamped = Math.min(Math.max(current, low), high);
  const pct = ((clamped - low) / (high - low)) * 100;

  return (
    <div className="price-range-bar">
      <span className="price-range-bar__caption">Preço atual na faixa dos últimos 30 dias</span>
      <div className="price-range-bar__track">
        <div className="price-range-bar__marker" style={{ left: `${pct}%` }} title={formatPrice(current)} />
      </div>
      <div className="price-range-bar__labels">
        <span>{formatPrice(low)}</span>
        <span>{formatPrice(high)}</span>
      </div>
    </div>
  );
}
