import { describe, expect, it } from "vitest";
import { domainOf, formatValue, prettyKey } from "../src/lib/indicator_display";

describe("prettyKey", () => {
  it("renders a flat key with leading capital", () => {
    expect(prettyKey("population")).toBe("Population");
  });

  it("renders dotted keys as head + colon + dotted tail", () => {
    expect(prettyKey("population.total")).toBe("Population: total");
  });

  it("converts underscores to spaces in the tail", () => {
    expect(prettyKey("population.age_structure.over_65")).toBe(
      "Population: age structure · over 65",
    );
  });
});

describe("formatValue", () => {
  it("returns em-dash for null", () => {
    expect(formatValue(null)).toBe("—");
  });

  it("formats integers with locale separators", () => {
    expect(formatValue(206800)).toBe("206,800");
  });

  it("formats fractions to 3 sig figs", () => {
    expect(formatValue(0.12345)).toBe("0.123");
  });
});

describe("domainOf", () => {
  it("returns the prefix segment", () => {
    expect(domainOf("population.total")).toBe("population");
    expect(domainOf("deprivation.imd.score")).toBe("deprivation");
  });

  it("returns the whole key when no dot", () => {
    expect(domainOf("population")).toBe("population");
  });
});
