import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { DayDataPoint } from '../api/types';
import { formatDate, formatPrice } from '../format';

interface Props {
  data: DayDataPoint[];
  token0Symbol: string;
  token1Symbol: string;
}

export function PriceChart({ data, token0Symbol, token1Symbol }: Props) {
  const chartData = data.map((d) => ({ date: d.date, close: d.close }));

  return (
    <div className="card">
      <div className="card__header">
        <h3>
          Histórico de preço ({token0Symbol}/{token1Symbol}) — 30 dias
        </h3>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            stroke="var(--muted)"
            fontSize={12}
            minTickGap={40}
          />
          <YAxis
            dataKey="close"
            tickFormatter={formatPrice}
            stroke="var(--muted)"
            fontSize={12}
            domain={['auto', 'auto']}
            width={70}
          />
          <Tooltip
            formatter={(value) => formatPrice(Number(value))}
            labelFormatter={(label) => formatDate(Number(label))}
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
          />
          <Area type="monotone" dataKey="close" stroke="var(--accent)" strokeWidth={2} fill="url(#priceGradient)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
