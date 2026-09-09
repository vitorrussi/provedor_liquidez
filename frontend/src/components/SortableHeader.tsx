interface SortableHeaderProps<K extends string> {
  className: string;
  label: string;
  title?: string;
  sortKey: K;
  activeKey: K;
  direction: 'asc' | 'desc';
  onSort: (key: K) => void;
}

export function SortableHeader<K extends string>({
  className,
  label,
  title,
  sortKey,
  activeKey,
  direction,
  onSort,
}: SortableHeaderProps<K>) {
  const active = sortKey === activeKey;
  return (
    <button
      type="button"
      className={`pool-list__header-btn ${className} ${active ? 'pool-list__header-btn--active' : ''}`}
      title={title}
      onClick={() => onSort(sortKey)}
    >
      {label}
      <span className="pool-list__sort-arrow">{active ? (direction === 'asc' ? '▲' : '▼') : ''}</span>
    </button>
  );
}
