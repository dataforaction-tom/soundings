import { describe, it, expect } from "vitest";

// Do NOT mock dom-polyfill — Observable Plot needs the linkedom DOM it installs.
// happy-dom alone doesn't provide document.documentElement in the way Plot expects.
import "../dom-polyfill";
import { PALETTE, formatFull, renderDistributionChart, renderCompositionChart, renderScatterPlot } from "../chart";

// ---------------------------------------------------------------------------
// formatFull
// ---------------------------------------------------------------------------

describe("formatFull", () => {
  it("returns em-dash for null", () => {
    expect(formatFull(null)).toBe("—");
  });

  it("returns em-dash for undefined", () => {
    expect(formatFull(undefined)).toBe("—");
  });

  it("returns em-dash for NaN", () => {
    expect(formatFull(NaN)).toBe("—");
  });

  it("returns em-dash for Infinity", () => {
    expect(formatFull(Infinity)).toBe("—");
  });

  it("formats integers with locale grouping", () => {
    expect(formatFull(123456)).toBe("123,456");
  });

  it("formats zero as 0", () => {
    expect(formatFull(0)).toBe("0");
  });

  it("formats large numbers with at most 1 decimal", () => {
    expect(formatFull(1234.56)).toBe("1,234.6");
  });

  it("formats medium decimals with at most 2 decimals", () => {
    expect(formatFull(12.345)).toBe("12.35");
  });

  it("formats small decimals without scientific notation", () => {
    const result = formatFull(0.0001234);
    expect(result).not.toContain("e");
    expect(result).not.toContain("E");
  });

  it("formats very small decimals without scientific notation", () => {
    const result = formatFull(0.00000123);
    expect(result).not.toContain("e");
    expect(result).not.toContain("E");
  });

  it("never produces scientific notation", () => {
    for (const v of [0.00001, 0.0000001, 1e-8, 1e-10, 123456789]) {
      const result = formatFull(v);
      expect(result).not.toContain("e-");
      expect(result).not.toContain("E-");
      expect(result).not.toContain("e+");
      expect(result).not.toContain("E+");
    }
  });
});

// ---------------------------------------------------------------------------
// renderDistributionChart
// ---------------------------------------------------------------------------

describe("renderDistributionChart", () => {
  it("returns empty string for empty peer_values", () => {
    const result = renderDistributionChart(
      { peer_values: [], focal_value: null, unit: "people", caption: null },
      {},
    );
    expect(result).toBe("");
  });

  it("returns an SVG string for valid input", () => {
    const result = renderDistributionChart(
      {
        peer_values: [100, 200, 300, 400, 500, 150, 250],
        focal_value: 250,
        unit: "people",
        caption: "Test distribution",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("</svg>");
    expect(result.length).toBeGreaterThan(100);
  });

  it("renders histogram bars (rectY + binX)", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
        focal_value: 50,
        unit: "score",
        caption: null,
      },
      {},
    );
    // Plot.rectY with Plot.binX emits <rect> elements for histogram bars.
    const rectCount = (result.match(/<rect/g) ?? []).length;
    expect(rectCount).toBeGreaterThanOrEqual(1);
  });

  it("marks the focal value with a green ruleX line", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      {},
    );
    // The focal rule uses the accent green from PALETTE[0] (#4a7c59).
    expect(result).toContain("#4a7c59");
  });

  it("annotates the focal value with a readable label", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      {},
    );
    // The focal annotation should include "This place:" and the formatted value.
    expect(result).toContain("This place: 30");
  });

  it("shows the peer count in the chart", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        peer_count: 5,
        caption: null,
      },
      {},
    );
    expect(result).toContain("5 peer places");
  });

  it("uses peer_values.length as peer_count fallback", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50, 60, 70],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      {},
    );
    expect(result).toContain("7 peer places");
  });

  it("renders without a focal rule when focal_value is null", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: null,
        unit: "score",
        caption: null,
      },
      {},
    );
    expect(result).toContain("<svg");
  });

  it("includes accessibility <title> and <desc>", () => {
    const result = renderDistributionChart(
      {
        peer_values: [1, 2, 3, 4, 5],
        focal_value: 3,
        unit: "score",
        caption: "Test",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("</title>");
    expect(result).toContain("<desc>");
    expect(result).toContain("</desc>");
  });

  it("respects containerWidth", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      { containerWidth: 600 },
    );
    expect(result).toContain('width="600"');
  });

  it("uses 'Number of places' as the y-axis label, not 'Peer places'", () => {
    const result = renderDistributionChart(
      {
        peer_values: [10, 20, 30, 40, 50],
        focal_value: 30,
        unit: "score",
        caption: null,
      },
      {},
    );
    expect(result).toContain("Number of places");
  });
});

// ---------------------------------------------------------------------------
// renderCompositionChart
// ---------------------------------------------------------------------------

describe("renderCompositionChart", () => {
  it("returns empty string for empty segments", () => {
    const result = renderCompositionChart(
      { title: "Test", segments: [], caption: null },
      {},
    );
    expect(result).toBe("");
  });

  it("returns an SVG string for valid segments", () => {
    const result = renderCompositionChart(
      {
        title: "Income distribution",
        segments: [
          { label: "Under £10k", value: 412 },
          { label: "£10k-£100k", value: 301 },
          { label: "£100k-£1m", value: 198 },
        ],
        caption: "Charity income bands",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("</svg>");
    expect(result.length).toBeGreaterThan(100);
  });

  it("emits one donut path per segment", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [
          { label: "A", value: 50 },
          { label: "B", value: 30 },
          { label: "C", value: 20 },
        ],
        caption: null,
      },
      {},
    );
    // Donut slices are drawn as <path> elements (SVG arc commands).
    const pathCount = (result.match(/<path/g) ?? []).length;
    expect(pathCount).toBeGreaterThanOrEqual(3);
  });

  it("uses PALETTE colours when no explicit colour provided", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50 }, { label: "B", value: 50 }],
        caption: null,
      },
      {},
    );
    // PALETTE[0] is the accent green used for the first segment.
    expect(result).toContain(PALETTE[0]);
  });

  it("respects an explicit segment colour override", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50, colour: "#ff0000" }],
        caption: null,
      },
      {},
    );
    expect(result).toContain("#ff0000");
  });

  it("includes accessibility <title> and <desc>", () => {
    const result = renderCompositionChart(
      {
        title: "Age structure",
        segments: [{ label: "Under 18", value: 22.5 }],
        caption: "Population by age band",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("</title>");
    expect(result).toContain("<desc>");
    expect(result).toContain("</desc>");
  });

  it("respects containerWidth", () => {
    const result = renderCompositionChart(
      {
        title: "Test",
        segments: [{ label: "A", value: 50 }, { label: "B", value: 50 }],
        caption: null,
      },
      { containerWidth: 500 },
    );
    expect(result).toContain('width="500"');
  });

  it("renders a legend with each segment label, value and percentage", () => {
    // total = 1000 → 41% / 30% / 29%
    const result = renderCompositionChart(
      {
        title: "Income distribution",
        segments: [
          { label: "Under £10k", value: 412 },
          { label: "£10k-£100k", value: 301 },
          { label: "£100k-£1m", value: 287 },
        ],
        caption: null,
      },
      { containerWidth: 480 },
    );
    // Every segment is named in the legend...
    expect(result).toContain("Under £10k");
    expect(result).toContain("£10k-£100k");
    expect(result).toContain("£100k-£1m");
    // ...with its value (locale-formatted, no scientific notation) and share.
    expect(result).toContain("412");
    expect(result).toContain("41%");
    // Legend swatches reuse the slice colours.
    expect(result).toContain(PALETTE[0]);
  });
});

// ---------------------------------------------------------------------------
// renderScatterPlot
// ---------------------------------------------------------------------------

describe("renderScatterPlot", () => {
  it("returns empty string for empty points", () => {
    const result = renderScatterPlot(
      {
        points: [],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    expect(result).toBe("");
  });

  it("returns an SVG string for valid points", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:B", x_value: 30, y_value: 75, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy (years)",
        caption: "Deprivation vs life expectancy",
      },
      { containerWidth: 480 },
    );
    expect(result).toContain("<svg");
    expect(result).toContain("</svg>");
    expect(result.length).toBeGreaterThan(100);
  });

  it("emits one circle per point (peer + focal)", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:B", x_value: 30, y_value: 75, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    // Plot.dot emits one <circle> per point: 2 peers + 1 focal = 3.
    const circleCount = (result.match(/<circle/g) ?? []).length;
    expect(circleCount).toBe(3);
  });

  it("uses navy for peer dots and green for the focal dot", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    // Navy for peers.
    expect(result).toContain("#1a2f4e");
    // Accent green for focal dot.
    expect(result).toContain("#4a7c59");
  });

  it("includes hover titles on dots", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      {},
    );
    // Plot renders title channels as <title> elements inside each dot's <g>.
    // Peer dot should have a <title> with the values.
    expect(result).toContain("<title>");
  });

  it("includes accessibility <title> and <desc>", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: "Test caption",
      },
      {},
    );
    expect(result).toContain("<title>");
    expect(result).toContain("</title>");
    expect(result).toContain("<desc>");
    expect(result).toContain("</desc>");
  });

  it("respects containerWidth", () => {
    const result = renderScatterPlot(
      {
        points: [
          { place_id: "ltla24:A", x_value: 10, y_value: 80, is_focal: false },
          { place_id: "ltla24:E06000047", x_value: 25, y_value: 78, is_focal: true },
        ],
        focal_place_id: "ltla24:E06000047",
        x_label: "IMD score",
        y_label: "Life expectancy",
        caption: null,
      },
      { containerWidth: 600 },
    );
    expect(result).toContain('width="600"');
  });
});
