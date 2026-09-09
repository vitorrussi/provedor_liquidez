export function formatUsd(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}k`;
  return `$${value.toFixed(2)}`;
}

export function formatPercent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatPrice(value: number): string {
  if (value === 0) return '0';
  if (Math.abs(value) < 0.0001) return value.toExponential(2);
  if (Math.abs(value) < 1) return value.toFixed(6);
  if (Math.abs(value) < 1000) return value.toFixed(4);
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
}

export function formatFeeTier(feeTier: number): string {
  return `${(feeTier / 10_000).toFixed(2)}%`;
}

export function formatDate(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleDateString('pt-BR');
}

export function truncateAddress(address: string): string {
  if (address.length <= 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

export function etherscanTokenUrl(address: string): string {
  return `https://etherscan.io/token/${address}`;
}
