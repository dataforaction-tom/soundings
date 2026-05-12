// Pure chart rendering — produces SVG strings that the Astro layer can drop
// straight into the page. All Plot.plot() calls happen inside Node SSR, so
// callers must have imported "./dom-polyfill" before this module loads.

import "./dom-polyfill";

import * as Plot from "@observablehq/plot";

import type { TrendPoint } from "./types";

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
