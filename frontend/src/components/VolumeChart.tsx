import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { DayDataPoint } from '../api/types';
import { formatDate, formatUsd } from '../format';

interface Props {
  data: DayDataPoint[];
}

export function VolumeChart({ data }: Props) {
  const chartData = data.map((d) => ({ date: d.date, volume: d.volume_usd }));

  return (
    <div className="card">
      <div className="card__header">
        <h3>Volume diário — 30 dias</h3>
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="date" tickFormatter={formatDate} stroke="var(--muted)" fontSize={12} minTickGap={40} />
          <YAxis dataKey="volume" tickFormatter={formatUsd} stroke="var(--muted)" fontSize={12} width={70} />
          <Tooltip
            formatter={(value) => formatUsd(Number(value))}
            labelFormatter={(label) => formatDate(Number(label))}
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
          />
          <Bar dataKey="volume" fill="var(--accent)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
