import { Area, AreaChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { DayDataPoint, RangeScenario, RangeScenarioKey } from '../api/types';
import { formatDate, formatPrice } from '../format';

// Cor + rótulo por cenário -- reaproveitado pela tabela comparativa
// (RangeAnalysisPage.tsx) e pelo gráfico de barras (RangeAprIlChart.tsx) pra
// manter a mesma identidade visual em todo lugar que mostra um cenário.
export const SCENARIO_META: Record<RangeScenarioKey, { label: string; shortLabel: string; color: string }> = {
  custom: { label: 'Sua faixa', shortLabel: 'Sua faixa', color: 'var(--accent)' },
  narrow: { label: 'Estreita (~0,5σ)', shortLabel: 'Estreita', color: 'var(--scenario-narrow)' },
  medium: { label: 'Média (~1σ)', shortLabel: 'Média', color: 'var(--scenario-medium)' },
  wide: { label: 'Larga (~2σ)', shortLabel: 'Larga', color: 'var(--scenario-wide)' },
  realized: { label: 'Variação realizada', shortLabel: 'Realizada', color: 'var(--scenario-realized)' },
};

interface Props {
  dailyHistory: DayDataPoint[];
  scenarios: RangeScenario[];
  token0Symbol: string;
  token1Symbol: string;
}

export function RangeAnalysisChart({ dailyHistory, scenarios, token0Symbol, token1Symbol }: Props) {
  const chartData = dailyHistory.map((d) => ({ date: d.date, close: d.close }));

  return (
    <div className="card">
      <div className="card__header">
        <h3>
          Preço histórico e faixas ({token0Symbol}/{token1Symbol})
        </h3>
      </div>
      <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="rangeAnalysisPriceGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.25} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="date" tickFormatter={formatDate} stroke="var(--muted)" fontSize={12} minTickGap={40} />
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
          <Area
            type="monotone"
            dataKey="close"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#rangeAnalysisPriceGradient)"
          />
          {scenarios.map((s) => (
            <ReferenceArea
              key={s.key}
              y1={s.price_lower}
              y2={s.price_upper}
              stroke={SCENARIO_META[s.key].color}
              strokeOpacity={0.7}
              fill={SCENARIO_META[s.key].color}
              fillOpacity={0.07}
              ifOverflow="extendDomain"
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      <ul className="range-analysis-legend">
        {scenarios.map((s) => (
          <li key={s.key}>
            <span className="scenario-table__dot" style={{ background: SCENARIO_META[s.key].color }} />
            {SCENARIO_META[s.key].label}
          </li>
        ))}
      </ul>
    </div>
  );
}
