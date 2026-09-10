import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { AssetIndexRow } from '../api/types';

interface TokenMultiSelectProps {
  label: string;
  placeholder?: string;
  selected: string[];
  onChange: (symbols: string[]) => void;
}

// Máximo de chips por campo -- cada combinação token_a x token_b vira uma
// query `symbol_in` só (não multiplica aliases, ver services/pools.py), mas
// um número muito grande de símbolos ainda infla o payload da resposta (mais
// pools batendo no `where`) sem ganho real de UX. 8 é generoso o bastante
// pra qualquer uso real e barato o bastante pra não preocupar.
const MAX_TOKENS = 8;

// Campo de "escrever -> aparece lista -> clicar -> vira chip com x pra
// remover" pros filtros de Token A/Token B (busca por par). Diferente do
// autocomplete do campo de busca principal (que preenche o próprio campo de
// texto ao selecionar), aqui a seleção nunca preenche o campo de texto --
// list de símbolos escolhidos é o próprio estado do filtro. Sugestões vêm do
// índice local (mesmo endpoint do autocomplete principal), então não custa
// cota do Graph a cada tecla digitada.
export function TokenMultiSelect({ label, placeholder, selected, onChange }: TokenMultiSelectProps) {
  const [input, setInput] = useState('');
  const [suggestions, setSuggestions] = useState<AssetIndexRow[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);

  useEffect(() => {
    const term = input.trim();
    if (term.length < 1) {
      setSuggestions([]);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api
        .suggestAssets(term, 8)
        .then((rows) => {
          if (!cancelled) setSuggestions(rows.filter((r) => !selected.includes(r.symbol)));
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input]);

  function addToken(symbol: string) {
    if (selected.includes(symbol) || selected.length >= MAX_TOKENS) return;
    onChange([...selected, symbol]);
    setInput('');
    setShowSuggestions(false);
  }

  function removeToken(symbol: string) {
    onChange(selected.filter((s) => s !== symbol));
  }

  return (
    <div className="token-multiselect">
      <span className="advanced-filters__label">{label}</span>
      {selected.length > 0 && (
        <div className="token-multiselect__chips">
          {selected.map((symbol) => (
            <span key={symbol} className="token-multiselect__chip">
              {symbol}
              <button type="button" onClick={() => removeToken(symbol)} aria-label={`Remover ${symbol}`}>
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="token-multiselect__input-wrap">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onFocus={() => setShowSuggestions(true)}
          onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
          placeholder={selected.length >= MAX_TOKENS ? `máx. ${MAX_TOKENS}` : placeholder}
          disabled={selected.length >= MAX_TOKENS}
          autoComplete="off"
        />
        {showSuggestions && suggestions.length > 0 && (
          <ul className="pool-search__suggestions token-multiselect__suggestions">
            {suggestions.map((asset) => (
              <li key={asset.id}>
                <button type="button" onMouseDown={() => addToken(asset.symbol)}>
                  <span className="pool-search__suggestion-symbol">{asset.symbol}</span>
                  <span className="pool-search__suggestion-name muted">{asset.name}</span>
                  {asset.category && <span className="badge">{asset.category}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
