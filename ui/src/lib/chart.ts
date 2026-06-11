// Pure chart rendering — produces SVG strings that the Astro layer can drop
// straight into the page. All Plot.plot() calls happen inside Node SSR, so
// callers must have imported "./dom-polyfill" before this module loads.

import "./dom-polyfill";

import * as Plot from "@observablehq/plot";

import type { Comparison, ComparisonBasis, ComparisonValue, IncomeBucket, RegistrationCohort, TrendPoint } from "./types";

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
  basis?: ComparisonBasis;
}

const COMPARE_DEFAULTS: Required<Pick<CompareBarsOptions, "width" | "height">> = {
  width: 480,
  height: 200,
};

interface BarPoint {
  place_id: string;
  value: number;
  label: string;
}

function formatShort(value: number): string {
  // Compact human-readable label: 196k, 1.5M, 0.14, 12.5
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (abs >= 10_000) return `${Math.round(value / 1000)}k`;
  if (abs >= 1000) return `${(value / 1000).toFixed(1)}k`;
  if (abs >= 10) return Math.round(value).toString();
  if (abs >= 1) return value.toFixed(1);
  return value.toFixed(3);
}

function makeBasisLabel(v: ComparisonValue, basis: ComparisonBasis): string {
  switch (basis) {
    case "rank":
      return v.rank != null ? `#${v.rank}` : "";
    case "absolute":
      return v.value != null ? formatShort(v.value) : "";
    case "rate":
      return v.value != null ? `${formatShort(v.value)}/1k` : "";
    case "percentile":
    default:
      return v.percentile != null ? `p${Math.round(v.percentile)}` : "";
  }
}

function toBarPoints(values: ComparisonValue[], basis: ComparisonBasis): BarPoint[] {
  const out: BarPoint[] = [];
  for (const v of values) {
    if (v.value === null || v.value === undefined) {
      continue;
    }
    out.push({
      place_id: v.place_id,
      value: v.value,
      label: makeBasisLabel(v, basis),
    });
  }
  return out;
}

export function renderCompareBars(
  comparison: Comparison,
  opts: CompareBarsOptions = {},
): string {
  const basis = opts.basis ?? "percentile";
  const bars = toBarPoints(comparison.values, basis);
  if (bars.length === 0) {
    return "";
  }
  const { width, height } = { ...COMPARE_DEFAULTS, width: opts.width ?? COMPARE_DEFAULTS.width, height: opts.height ?? COMPARE_DEFAULTS.height };
  const node = Plot.plot({
    width,
    height,
    marginTop: 20,
    marginRight: 12,
    marginBottom: 36,
    marginLeft: 60,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { label: null, tickRotate: -25 },
    y: { grid: true, label: comparison.unit, nice: true },
    marks: [
      Plot.barY(bars, {
        x: "place_id",
        y: "value",
        fill: "#4a7c59",
      }),
      Plot.text(bars, {
        x: "place_id",
        y: "value",
        text: "label",
        dy: -8,
        fontSize: 11,
        fill: "#2d2d2d",
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
    style: {
      background: "transparent",
      fontSize: "10px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { type: "point", label: null, tickFormat: (d: unknown) => String(d) },
    y: { grid: false, label: null, nice: true },
    marks: [
      Plot.line(chartPoints, { x: "period", y: "value", strokeWidth: 1.5, stroke: "#4a7c59" }),
      Plot.dot(chartPoints, { x: "period", y: "value", r: 2.5, fill: "#4a7c59" }),
    ],
  });
  // linkedom and the browser both expose outerHTML on SVG elements.
  return (node as unknown as { outerHTML: string }).outerHTML;
}

export function renderIncomeBuckets(
  buckets: IncomeBucket[],
  opts: { width?: number; height?: number } = {},
): string {
  if (buckets.length === 0) return "";
  const width = opts.width ?? 480;
  const height = opts.height ?? 200;
  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 12,
    marginBottom: 36,
    marginLeft: 48,
    x: { label: "Annual income band", tickRotate: -15 },
    y: { grid: true, label: "Charities", nice: true },
    marks: [
      Plot.barY(buckets, { x: "label", y: "count", fill: "#2a5bd7" }),
      Plot.text(buckets, {
        x: "label",
        y: "count",
        text: (d: IncomeBucket) => String(d.count),
        dy: -6,
        fontSize: 11,
        fill: "#333",
      }),
    ],
  });
  return (node as unknown as { outerHTML: string }).outerHTML;
}

export function renderRegistrationTrend(
  cohort: RegistrationCohort[],
  opts: { width?: number; height?: number } = {},
): string {
  if (cohort.length === 0) return "";
  const width = opts.width ?? 480;
  const height = opts.height ?? 180;
  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 12,
    marginBottom: 32,
    marginLeft: 40,
    x: { label: null, tickFormat: (d: unknown) => String(d) },
    y: { grid: true, label: "Net new charities", nice: true },
    marks: [
      Plot.ruleY([0]),
      Plot.lineY(cohort, { x: "year", y: "net", stroke: "#2a5bd7", strokeWidth: 1.5 }),
      Plot.dot(cohort, { x: "year", y: "net", r: 2.5, fill: "#2a5bd7" }),
    ],
  });
  return (node as unknown as { outerHTML: string }).outerHTML;
}
