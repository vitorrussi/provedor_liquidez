const COMPACT_SCALES: Array<[number, string]> = [
  [1e12, 'T'], // trilhão
  [1e9, 'B'], // bilhão
  [1e6, 'M'], // milhão
  [1e3, 'k'], // mil
];

function fixed2(n: number): string {
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Sempre no máximo 3 dígitos antes da vírgula + 2 depois (ex: "1,23k", "999,99M").
// Escolhe a maior escala (T/B/M/k) que ainda deixa a parte inteira com <=3 dígitos.
function formatCompactNumber(value: number): string {
  const abs = Math.abs(value);
  for (let i = 0; i < COMPACT_SCALES.length; i++) {
    const [threshold, suffix] = COMPACT_SCALES[i];
    if (abs >= threshold) {
      const scaled = value / threshold;
      // Evita "1000,00k" no arredondamento -- promove pra escala de cima.
      if (Math.round(Math.abs(scaled) * 100) / 100 >= 1000 && i > 0) {
        const [biggerThreshold, biggerSuffix] = COMPACT_SCALES[i - 1];
        return `${fixed2(value / biggerThreshold)}${biggerSuffix}`;
      }
      return `${fixed2(scaled)}${suffix}`;
    }
  }
  return fixed2(value);
}

export function formatUsd(value: number): string {
  return `$${formatCompactNumber(value)}`;
}

export function formatPercent(value: number, digits = 2): string {
  // Alguns pools têm TVL tão baixo (ou economia de taxa fora do padrão, como
  // pools de taxa dinâmica) que o APR calculado (taxas/TVL) explode pra
  // valores de milhares de % -- tecnicamente é o que a conta dá, mas mostrar
  // "528603.53%" como se fosse um número preciso é enganoso, não informativo.
  if (Math.abs(value) > 100) return value > 0 ? '>10000%' : '<-10000%';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatRatio(value: number): string {
  if (value < 0.01 && value > 0) return '<0,01';
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatPrice(value: number): string {
  if (value === 0) return '0';
  if (Math.abs(value) < 0.0001) return value.toExponential(2);
  if (Math.abs(value) < 1) return value.toFixed(6);
  if (Math.abs(value) < 1000) return value.toFixed(4);
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
}

// Uniswap v4 usa esse valor (0x800000) como flag de "taxa dinâmica, definida
// por um hook" -- não é uma taxa fixa de verdade, então não faz sentido
// dividir por 10_000 e mostrar como "838.86%".
const DYNAMIC_FEE_SENTINEL = 8_388_608;

export function formatFeeTier(feeTier: number): string {
  if (feeTier === DYNAMIC_FEE_SENTINEL) return 'dinâmica';
  return `${(feeTier / 10_000).toFixed(2)}%`;
}

export function protocolLabel(protocol: 'v2' | 'v3' | 'v4' | 'aerodrome'): string {
  if (protocol === 'aerodrome') return 'Aerodrome Slipstream';
  return `Uniswap ${protocol}`;
}

export function formatDate(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleDateString('pt-BR');
}

export function truncateAddress(address: string): string {
  if (address.length <= 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

// Aerodrome Slipstream roda na Base, não em Ethereum mainnet -- o mesmo
// endereço de contrato significa coisas diferentes em cada chain, então o
// link do explorador tem que seguir o protocolo, não ser sempre etherscan.
export function explorerTokenUrl(address: string, protocol: 'v2' | 'v3' | 'v4' | 'aerodrome'): string {
  const base = protocol === 'aerodrome' ? 'https://basescan.org' : 'https://etherscan.io';
  return `${base}/token/${address}`;
}
