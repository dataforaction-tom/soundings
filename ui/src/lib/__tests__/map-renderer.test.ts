import { describe, it, expect } from "vitest";
import { colourDomain, amenityLayerLabel, amenityLegendItems } from "../map-renderer";
import { PALETTE } from "../chart";

describe("colourDomain", () => {
  it("returns [min, mid, max] from finite values", () => {
    expect(colourDomain([10, 20, 30])).toEqual([10, 20, 30]);
  });

  it("ignores null/undefined/NaN", () => {
    expect(colourDomain([5, null, 15, undefined, NaN])).toEqual([5, 10, 15]);
  });

  it("falls back to [0, 0.5, 1] when no finite values", () => {
    expect(colourDomain([null, undefined])).toEqual([0, 0.5, 1]);
  });

  it("handles a single value (min === max)", () => {
    expect(colourDomain([7])).toEqual([7, 7, 7]);
  });
});

describe("amenityLayerLabel", () => {
  it("humanises an infrastructure count key", () => {
    expect(amenityLayerLabel("infrastructure.food_banks_count")).toBe("Food banks");
    expect(amenityLayerLabel("infrastructure.gp_practices_count")).toBe("Gp practices");
  });
});

describe("amenityLegendItems", () => {
  it("assigns one PALETTE colour per layer", () => {
    const items = amenityLegendItems([
      "infrastructure.food_banks_count",
      "infrastructure.schools_count",
    ]);
    expect(items).toEqual([
      { label: "Food banks", colour: PALETTE[0] },
      { label: "Schools", colour: PALETTE[1] },
    ]);
  });
});
