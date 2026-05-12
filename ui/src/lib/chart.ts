// Pure chart rendering — produces SVG strings that the Astro layer can drop
// straight into the page. All Plot.plot() calls happen inside Node SSR, so
// callers must have imported "./dom-polyfill" before this module loads.

import "./dom-polyfill";

import * as Plot from "@observablehq/plot";

import type { Comparison, ComparisonValue, TrendPoint } from "./types";

interface SparklineOptions {
  width?: number;
  height?: number;
}

interface ChartPoint {
  index: number;
  period: string;
  value: number;
}

const DEFAULTS: Required<SparklineOptions> = {
  width: 240,
  height: 64,
};

function toChartPoints(points: TrendPoint[]): ChartPoint[] {
  const out: ChartPoint[] = [];
  points.forEach((p, index) => {
    if (p.value === null || p.value === undefined) {
      return;
    }
    out.push({ index, period: p.period, value: p.value });
  });
  return out;
}

interface CompareBarsOptions {
  width?: number;
  height?: number;
}

const COMPARE_DEFAULTS: Required<CompareBarsOptions> = {
  width: 480,
  height: 200,
};

interface BarPoint {
  place_id: string;
  value: number;
  percentile: number | null;
  label: string;
}

function toBarPoints(values: ComparisonValue[]): BarPoint[] {
  const out: BarPoint[] = [];
  for (const v of values) {
    if (v.value === null || v.value === undefined) {
      continue;
    }
    const pct = v.percentile ?? null;
    const label = pct !== null ? `p${Math.round(pct)}` : "";
    out.push({
      place_id: v.place_id,
      value: v.value,
      percentile: pct,
      label,
    });
  }
  return out;
}

export function renderCompareBars(
  comparison: Comparison,
  opts: CompareBarsOptions = {},
): string {
  const bars = toBarPoints(comparison.values);
  if (bars.length === 0) {
    return "";
  }
  const { width, height } = { ...COMPARE_DEFAULTS, ...opts };
  const node = Plot.plot({
    width,
    height,
    marginTop: 20,
    marginRight: 12,
    marginBottom: 36,
    marginLeft: 60,
    x: { label: null, tickRotate: -25 },
    y: { grid: true, label: comparison.unit, nice: true },
    marks: [
      Plot.barY(bars, {
        x: "place_id",
        y: "value",
        fill: "#2a5bd7",
      }),
      Plot.text(bars, {
        x: "place_id",
        y: "value",
        text: "label",
        dy: -8,
        fontSize: 11,
        fill: "#333",
      }),
    ],
  });
  return (node as unknown as { outerHTML: string }).outerHTML;
}

export function renderSparkline(
  points: TrendPoint[],
  opts: SparklineOptions = {},
): string {
  const chartPoints = toChartPoints(points);
  if (chartPoints.length === 0) {
    return "";
  }
  const { width, height } = { ...DEFAULTS, ...opts };

  // `Plot.plot` returns an SVGSVGElement (linkedom-shaped under SSR). The
  // outerHTML is the serialised string ready to insert as `set:html`.
  const node = Plot.plot({
    width,
    height,
    marginTop: 4,
    marginRight: 4,
    marginBottom: 18,
    marginLeft: 28,
    x: { type: "point", label: null, tickFormat: (d: unknown) => String(d) },
    y: { grid: false, label: null, nice: true },
    marks: [
      Plot.line(chartPoints, { x: "period", y: "value", strokeWidth: 1.5 }),
      Plot.dot(chartPoints, { x: "period", y: "value", r: 2.5, fill: "currentColor" }),
    ],
  });
  // linkedom and the browser both expose outerHTML on SVG elements.
  return (node as unknown as { outerHTML: string }).outerHTML;
}
