// Client logic for the map explorer (/explore). Picks an indicator + geography
// level, fetches the national choropleth, and (re)renders it. Rebuild-on-change
// is fine for the skeleton; an in-place stateful map is a later refinement.

interface ExploreIndicator {
  key: string;
  label: string;
  available_at: string[];
}

const LEVEL_LABELS: Record<string, string> = {
  lsoa21: "Neighbourhood (LSOA)",
  ltla24: "Local authority",
  utla24: "Upper-tier authority",
  region: "Region",
};
// Preferred order for the level dropdown (coarse → fine reads best as options).
const LEVEL_ORDER = ["ltla24", "utla24", "region", "lsoa21"];

let maplibreCssLoaded = false;
function ensureMaplibreCss(): void {
  if (maplibreCssLoaded) return;
  maplibreCssLoaded = true;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.css";
  document.head.appendChild(link);
}

function init(): void {
  const surface = document.getElementById("explore-map");
  const indicatorSel = document.getElementById("explore-indicator") as HTMLSelectElement | null;
  const levelSel = document.getElementById("explore-level") as HTMLSelectElement | null;
  const status = document.getElementById("explore-status");
  const dataEl = document.getElementById("explore-indicators-data");
  if (!surface || !indicatorSel || !levelSel || !dataEl) return;

  const apiBase = surface.dataset.apiBase || "";
  const tilesUrl = surface.dataset.mapTiles || undefined;
  const indicators = JSON.parse(dataEl.textContent || "[]") as ExploreIndicator[];
  const byKey = new Map(indicators.map((i) => [i.key, i]));

  let cleanup: (() => void) | null = null;

  function levelsFor(key: string): string[] {
    const avail = byKey.get(key)?.available_at ?? [];
    return LEVEL_ORDER.filter((l) => avail.includes(l));
  }

  function refreshLevelOptions(): void {
    const levels = levelsFor(indicatorSel!.value);
    levelSel!.innerHTML = levels
      .map((l) => `<option value="${l}">${LEVEL_LABELS[l] ?? l}</option>`)
      .join("");
  }

  async function render(): Promise<void> {
    const key = indicatorSel!.value;
    const level = levelSel!.value;
    if (!key || !level) return;

    cleanup?.();
    cleanup = null;
    if (status) status.textContent = "Loading…";

    const large = level === "lsoa21" ? "&large=true" : "";
    let fc: GeoJSON.FeatureCollection;
    try {
      const res = await fetch(
        `${apiBase}/v1/geographies/${encodeURIComponent(level)}/geometry` +
          `?indicator=${encodeURIComponent(key)}${large}`,
      );
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      fc = (await res.json()) as GeoJSON.FeatureCollection;
    } catch (err) {
      if (status) {
        status.textContent =
          "Could not load map: " + (err instanceof Error ? err.message : String(err));
      }
      return;
    }

    ensureMaplibreCss();
    surface!.innerHTML = "";
    const { renderChoroplethMap } = await import("../lib/map-renderer");
    cleanup = renderChoroplethMap(surface!, fc, "value", {
      label: byKey.get(key)?.label ?? key,
      tilesUrl,
    });
    const n = (fc.features ?? []).filter(
      (f) => typeof f.properties?.value === "number",
    ).length;
    if (status) {
      status.textContent = `${n} ${LEVEL_LABELS[level] ?? level} areas with data · click an area for details`;
    }
  }

  indicatorSel.addEventListener("change", () => {
    refreshLevelOptions();
    void render();
  });
  levelSel.addEventListener("change", () => void render());

  refreshLevelOptions();
  void render();
}

init();
