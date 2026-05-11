// Display helpers for IndicatorCard. Pure functions, unit-tested.

export function prettyKey(key: string): string {
  const [head, ...rest] = key.split(".");
  const headPretty = head ? head[0]!.toUpperCase() + head.slice(1) : key;
  const tail = rest.join(" · ").replaceAll("_", " ");
  return tail ? `${headPretty}: ${tail}` : headPretty;
}

export function formatValue(value: number | null): string {
  if (value === null) return "—";
  if (!Number.isFinite(value)) return String(value);
  if (Number.isInteger(value)) return value.toLocaleString("en-GB");
  return value.toPrecision(3);
}

export function domainOf(indicatorKey: string): string {
  return indicatorKey.split(".")[0] ?? indicatorKey;
}
