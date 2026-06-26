// Pure chart rendering — produces SVG strings that the Astro layer can drop
// straight into the page. All Plot.plot() calls happen inside Node SSR, so
// callers must have imported "./dom-polyfill" before this module loads.

import "./dom-polyfill";

import * as Plot from "@observablehq/plot";

import type { Comparison, ComparisonBasis, ComparisonValue, IncomeBucket, RegistrationCohort, TrendPoint } from "./types";

// Good Ship colour palette — aligned with CSS variables in global.css.
// Used for chart fills/strokes so server-rendered SVG matches the design
// system without depending on a CSS runtime. Order matters: index 0 is the
// default/primary chart colour (accent green).
export const PALETTE: readonly string[] = [
  "#4a7c59", // green  (--color-accent)
  "#1a2f4e", // navy   (--color-primary)
  "#8b6f47", // brown
  "#6b7280", // gray   (--color-muted)
  "#9c6644", // rust
  "#365314", // dark green
];

interface SparklineOptions {
  width?: number;
  height?: number;
  containerWidth?: number;
}

interface ChartPoint {
  index: number;
  period: string;
  value: number;
}

const DEFAULTS: Required<Pick<SparklineOptions, "width" | "height">> = {
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
  containerWidth?: number;
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

// Prepend <title> and <desc> accessibility elements to an SVG node returned
// by Plot.plot. Per SVG spec these must be the first children of the root
// <svg>. Returns the serialised outerHTML string.
function svgWithA11y(
  node: unknown,
  title: string,
  desc: string,
): string {
  const svg = node as SVGElement & {
    createElementNS?: (ns: string, tag: string) => SVGElement;
    insertBefore?: (newNode: Node, ref: Node | null) => Node;
    firstChild?: Node | null;
    ownerDocument?: Document;
  };
  const doc = svg.ownerDocument ?? (globalThis as { document?: Document }).document;
  if (doc && svg.insertBefore && svg.firstChild != null) {
    const ns = "http://www.w3.org/2000/svg";
    const titleEl = doc.createElementNS(ns, "title");
    titleEl.textContent = title;
    const descEl = doc.createElementNS(ns, "desc");
    descEl.textContent = desc;
    svg.insertBefore(descEl, svg.firstChild);
    svg.insertBefore(titleEl, descEl);
  }
  return (svg as unknown as { outerHTML: string }).outerHTML;
}

export function renderCompareBars(
  comparison: Comparison,
  opts: CompareBarsOptions = {},
): string {
  const basis = opts.basis ?? "percentile";
  let bars = toBarPoints(comparison.values, basis);
  if (bars.length === 0) {
    return "";
  }
  // Sort bars by value descending so the largest is first (leftmost).
  bars = [...bars].sort((a, b) => b.value - a.value);
  const width = opts.containerWidth ?? opts.width ?? COMPARE_DEFAULTS.width;
  const { height } = COMPARE_DEFAULTS;
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
        // Cycle through PALETTE so each bar can be distinguished.
        fill: (d: BarPoint, i: number) => PALETTE[i % PALETTE.length],
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
  return svgWithA11y(node, "Compare bars", "Bar chart comparing values across places, sorted by value.");
}

export function renderSparkline(
  points: TrendPoint[],
  opts: SparklineOptions = {},
): string {
  const chartPoints = toChartPoints(points);
  if (chartPoints.length === 0) {
    return "";
  }
  const { width: defaultWidth, height } = DEFAULTS;
  const width = opts.containerWidth ?? opts.width ?? defaultWidth;

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
  return svgWithA11y(node, "Sparkline", "Trend sparkline showing values over time.");
}

export function renderIncomeBuckets(
  buckets: IncomeBucket[],
  opts: { width?: number; height?: number; containerWidth?: number } = {},
): string {
  if (buckets.length === 0) return "";
  const width = opts.containerWidth ?? opts.width ?? 480;
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
      Plot.barY(buckets, { x: "label", y: "count", fill: "#4a7c59" }),
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
  return svgWithA11y(node, "Income buckets", "Bar chart of charity counts by income band.");
}

export function renderRegistrationTrend(
  cohort: RegistrationCohort[],
  opts: { width?: number; height?: number; containerWidth?: number } = {},
): string {
  if (cohort.length === 0) return "";
  const width = opts.containerWidth ?? opts.width ?? 480;
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
      Plot.lineY(cohort, { x: "year", y: "net", stroke: "#4a7c59", strokeWidth: 1.5 }),
      Plot.dot(cohort, { x: "year", y: "net", r: 2.5, fill: "#4a7c59" }),
    ],
  });
  return svgWithA11y(node, "Registration trend", "Line chart of net new charity registrations by year.");
}

interface TrendChartOptions {
  width?: number;
  height?: number;
  containerWidth?: number;
}

interface TrendChartInput {
  points: TrendPoint[];
  unit: string;
  caption?: string;
}

const TREND_CHART_DEFAULTS: Required<Pick<TrendChartOptions, "width" | "height">> = {
  width: 480,
  height: 220,
};

export function renderTrendChart(
  input: TrendChartInput,
  opts: TrendChartOptions = {},
): string {
  const chartPoints = toChartPoints(input.points);
  if (chartPoints.length === 0) {
    return "";
  }
  const width = opts.containerWidth ?? opts.width ?? TREND_CHART_DEFAULTS.width;
  const height = opts.height ?? TREND_CHART_DEFAULTS.height;
  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 16,
    marginBottom: 36,
    marginLeft: 48,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { type: "point", label: "Period", tickFormat: (d: unknown) => String(d) },
    y: { grid: true, label: input.unit, nice: true },
    marks: [
      Plot.line(chartPoints, { x: "period", y: "value", strokeWidth: 2, stroke: PALETTE[0] }),
      Plot.dot(chartPoints, { x: "period", y: "value", r: 3, fill: PALETTE[0] }),
    ],
  });
  return svgWithA11y(
    node,
    "Trend chart",
    `Line chart showing ${input.unit} over time${input.caption ? ": " + input.caption : ""}.`,
  );
}

// --- Distribution chart -------------------------------------------------

export interface DistributionChartInput {
  peer_values: number[];
  focal_value: number | null;
  unit: string;
  caption?: string | null;
}

export function renderDistributionChart(
  input: DistributionChartInput,
  opts: { containerWidth?: number; width?: number; height?: number } = {},
): string {
  if (input.peer_values.length === 0) return "";

  const width = opts.containerWidth ?? opts.width ?? 480;
  const height = opts.height ?? 220;

  const data = input.peer_values.map((v) => ({ value: v }));

  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 16,
    marginBottom: 36,
    marginLeft: 48,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { label: input.unit, nice: true },
    y: { grid: true, label: "Peer places", nice: true },
    marks: [
      Plot.rectY(
        data,
        // Plot's TS types don't allow fill/fillOpacity in the second binX arg,
        // but the runtime accepts it. Cast to suppress the type error.
        Plot.binX({ y: "count" }, { x: "value", fill: "#1a2f4e", fillOpacity: 0.6 } as Record<string, unknown>),
      ),
      ...(input.focal_value !== null
        ? [Plot.ruleX([input.focal_value], { stroke: "#4a7c59", strokeWidth: 2.5 })]
        : []),
    ],
  });

  return svgWithA11y(
    node,
    "Distribution chart",
    `Histogram of peer values for ${input.unit}${input.caption ? ": " + input.caption : ""}.`,
  );
}

// --- Composition chart (donut) ------------------------------------------

export interface CompositionSegmentInput {
  label: string;
  value: number;
  colour?: string | null;
}

export interface CompositionChartInput {
  title: string;
  segments: CompositionSegmentInput[];
  caption?: string | null;
}

function polarToCartesian(cx: number, cy: number, r: number, angleRad: number): { x: number; y: number } {
  return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
}

function donutSlicePath(
  cx: number,
  cy: number,
  outerR: number,
  innerR: number,
  startAngle: number,
  endAngle: number,
): string {
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
  const outerStart = polarToCartesian(cx, cy, outerR, startAngle);
  const outerEnd = polarToCartesian(cx, cy, outerR, endAngle);
  const innerStart = polarToCartesian(cx, cy, innerR, endAngle);
  const innerEnd = polarToCartesian(cx, cy, innerR, startAngle);
  return [
    `M ${outerStart.x.toFixed(2)} ${outerStart.y.toFixed(2)}`,
    `A ${outerR} ${outerR} 0 ${largeArc} 1 ${outerEnd.x.toFixed(2)} ${outerEnd.y.toFixed(2)}`,
    `L ${innerStart.x.toFixed(2)} ${innerStart.y.toFixed(2)}`,
    `A ${innerR} ${innerR} 0 ${largeArc} 0 ${innerEnd.x.toFixed(2)} ${innerEnd.y.toFixed(2)}`,
    "Z",
  ].join(" ");
}

export function renderCompositionChart(
  input: CompositionChartInput,
  opts: { containerWidth?: number; width?: number; height?: number } = {},
): string {
  if (input.segments.length === 0) return "";

  const width = opts.containerWidth ?? opts.width ?? 480;
  const height = opts.height ?? 260;
  const cx = width / 2;
  const cy = height / 2;
  const outerR = Math.min(width, height) / 2 - 40;
  const innerR = outerR * 0.55;

  // Assign colours: explicit override → PALETTE cycle.
  const coloured = input.segments.map((s, i) => ({
    ...s,
    colour: s.colour ?? PALETTE[i % PALETTE.length],
  }));

  const total = coloured.reduce((sum, s) => sum + s.value, 0);

  // Build donut slice <path> elements manually — Observable Plot 0.6.x has no
  // arc mark, so we emit SVG arc paths directly and wrap them in an <svg>.
  let currentAngle = -Math.PI / 2; // start at 12 o'clock
  const slices = coloured.map((s) => {
    const angleSpan = total > 0 ? (s.value / total) * 2 * Math.PI : 0;
    const startAngle = currentAngle;
    const endAngle = currentAngle + angleSpan;
    currentAngle = endAngle;
    return {
      ...s,
      startAngle,
      endAngle,
      path: donutSlicePath(cx, cy, outerR, innerR, startAngle, endAngle),
    };
  });

  // Build the donut as a standalone <svg> element — Observable Plot 0.6.x has
  // no arc mark, so we emit SVG arc paths directly and then reuse svgWithA11y
  // to prepend <title>/<desc> and serialise the outerHTML.
  const ns = "http://www.w3.org/2000/svg";
  const doc = (globalThis as { document?: Document }).document;
  if (!doc) {
    // No DOM available — cannot build the SVG. Return empty rather than throw.
    return "";
  }
  const root = doc.createElementNS(ns, "svg");
  root.setAttribute("width", String(width));
  root.setAttribute("height", String(height));
  root.setAttribute("viewBox", `0 0 ${width} ${height}`);
  root.setAttribute("xmlns", ns);
  for (const s of slices) {
    const p = doc.createElementNS(ns, "path");
    p.setAttribute("d", s.path);
    p.setAttribute("fill", s.colour);
    p.setAttribute("stroke", "#faf9f6");
    p.setAttribute("stroke-width", "2");
    root.appendChild(p);
  }
  return svgWithA11y(
    root,
    "Composition chart",
    `Donut chart showing ${input.title}${input.caption ? ": " + input.caption : ""}.`,
  );
}

// --- Scatter plot --------------------------------------------------------

export interface ScatterPoint {
  place_id: string;
  x_value: number;
  y_value: number;
  is_focal: boolean;
}

export interface ScatterPlotInput {
  points: ScatterPoint[];
  focal_place_id: string;
  x_label: string;
  y_label: string;
  caption?: string | null;
}

export function renderScatterPlot(
  input: ScatterPlotInput,
  opts: { containerWidth?: number; width?: number; height?: number } = {},
): string {
  if (input.points.length === 0) return "";

  const width = opts.containerWidth ?? opts.width ?? 480;
  const height = opts.height ?? 320;

  const peerPoints = input.points.filter((p) => !p.is_focal);
  const focalPoints = input.points.filter((p) => p.is_focal);

  const node = Plot.plot({
    width,
    height,
    marginTop: 16,
    marginRight: 16,
    marginBottom: 40,
    marginLeft: 56,
    style: {
      background: "transparent",
      fontSize: "12px",
      fontFamily: "system-ui, sans-serif",
    },
    x: { label: input.x_label, nice: true },
    y: { label: input.y_label, grid: true, nice: true },
    marks: [
      Plot.dot(peerPoints, {
        x: "x_value",
        y: "y_value",
        fill: "#1a2f4e",
        fillOpacity: 0.4,
        r: 4,
      }),
      Plot.dot(focalPoints, {
        x: "x_value",
        y: "y_value",
        fill: "#4a7c59",
        r: 7,
        stroke: "#faf9f6",
        strokeWidth: 1.5,
      }),
    ],
  });

  return svgWithA11y(
    node,
    "Scatter plot",
    `Scatter plot of ${input.x_label} vs ${input.y_label}${input.caption ? ": " + input.caption : ""}.`,
  );
}
