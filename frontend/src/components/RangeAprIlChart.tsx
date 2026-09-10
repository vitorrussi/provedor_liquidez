import { Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { RangeScenario } from '../api/types';
import { formatPercent } from '../format';
import { SCENARIO_META } from './RangeAnalysisChart';

interface Props {
  scenarios: RangeScenario[];
}

export function RangeAprIlChart({ scenarios }: Props) {
  const chartData = scenarios.map((s) => ({
    label: SCENARIO_META[s.key].shortLabel,
    apr: s.estimated_position_apr,
    il: s.impermanent_loss,
  }));

  return (
    <div className="card">
      <div className="card__header">
        <h3>APR estimado vs. Impermanent Loss por cenário</h3>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="label" stroke="var(--muted)" fontSize={12} />
          <YAxis tickFormatter={(v) => formatPercent(Number(v))} stroke="var(--muted)" fontSize={12} width={60} />
          <ReferenceLine y={0} stroke="var(--border)" />
          <Tooltip
            formatter={(value, name) => [formatPercent(Number(value)), name]}
            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8 }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="apr" name="APR estimado" fill="var(--positive)" radius={[3, 3, 0, 0]} />
          <Bar dataKey="il" name="Impermanent Loss" fill="var(--negative)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
