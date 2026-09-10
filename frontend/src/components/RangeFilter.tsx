interface RangeFilterProps {
  label: string;
  title?: string;
  min: string;
  max: string;
  onMinChange: (value: string) => void;
  onMaxChange: (value: string) => void;
  step?: string;
}

// Par de campos "mínimo"/"máximo" pra um filtro numérico -- reaproveitado
// nos filtros avançados da busca principal, /assets e /pools (volume 1d/30d,
// vol1d/TVL, APR). Os valores ficam como string (não number) pra permitir
// campo vazio sem virar 0 -- a conversão pra número só acontece na hora de
// montar a chamada à API (undefined quando vazio == sem filtro).
export function RangeFilter({ label, title, min, max, onMinChange, onMaxChange, step = 'any' }: RangeFilterProps) {
  return (
    <div className="advanced-filters__range" title={title}>
      <span className="advanced-filters__label">{label}</span>
      <div className="advanced-filters__range-inputs">
        <input
          type="number"
          step={step}
          placeholder="mín"
          value={min}
          onChange={(e) => onMinChange(e.target.value)}
        />
        <span className="advanced-filters__range-sep">–</span>
        <input
          type="number"
          step={step}
          placeholder="máx"
          value={max}
          onChange={(e) => onMaxChange(e.target.value)}
        />
      </div>
    </div>
  );
}
