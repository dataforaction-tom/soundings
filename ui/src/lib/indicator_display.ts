// Display helpers for IndicatorCard. Pure functions, unit-tested.

import { formatFull } from "./chart";

export type HigherIs = "better" | "worse" | "neutral" | null;

export type ContextType = "percentile" | "rank";

export function prettyKey(key: string): string {
  const [head, ...rest] = key.split(".");
  const headPretty = head ? head[0]!.toUpperCase() + head.slice(1) : key;
  const tail = rest.join(" · ").replaceAll("_", " ");
  return tail ? `${headPretty}: ${tail}` : headPretty;
}

export function formatValue(value: number | null): string {
  return formatFull(value);
}

export function formatContext(value: number | null, type: ContextType): string {
  if (value === null) return "";
  const rounded = Math.round(value);
  if (type === "percentile") {
    return `p${rounded}`;
  }
  return `#${rounded}`;
}

export function formatDirection(higherIs: HigherIs): string {
  if (higherIs === "better") return "↑";
  if (higherIs === "worse") return "↓";
  return "";
}

export function domainOf(indicatorKey: string): string {
  return indicatorKey.split(".")[0] ?? indicatorKey;
}
