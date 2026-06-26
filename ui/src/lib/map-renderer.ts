// MapLibre GL JS map rendering helpers for Soundings.
//
// All functions are browser-only: MapLibre requires WebGL, so callers must
// dynamic-import this module on the client side (Astro `<script type="module">`
// or an SSE-driven `import()` when a map block arrives).
//
// Design tokens (Good Ship):
//   --color-accent  #4a7c59  (green)
//   --color-primary #1a2f4e  (navy)
//   --color-bg      #faf9f6  (cream)

import maplibregl, { type Map, type Popup } from "maplibre-gl";

const ACCENT_GREEN = "#4a7c59";
const CREAM = "#faf9f6";
const NAVY = "#1a2f4e";

// Shared base-map options: no tile source (solid background via CSS), no
// rotation, zoom controls in the bottom-right. When `tilesUrl` is provided, a
// raster OSM base layer is added; otherwise the map renders tile-less (as
// before) so existing tests and SSR keep working unchanged.
function baseMapOptions(
  container: HTMLElement,
  tilesUrl?: string,
): maplibregl.MapOptions {
  const sources: Record<string, any> = {};
  const layers: any[] = [];
  if (tilesUrl) {
    sources["base-tiles"] = {
      type: "raster",
      tiles: [tilesUrl],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    };
    layers.push({ id: "base", type: "raster", source: "base-tiles" });
  }
  return {
    container,
    // Minimal blank style (no external tiles — local-first). `glyphs` must be
    // omitted entirely: setting it to `undefined` fails MapLibre's style
    // validation ("glyphs: string expected, undefined found"), which aborts
    // the style load so the boundary layers are never added.
    style: {
      version: 8,
      sources,
      layers,
    },
    attributionControl: tilesUrl ? {} : false,
    dragRotate: false,
    touchZoomRotate: false,
    keyboard: false,
  };
}

function featureBounds(geojson: GeoJSON.GeoJSON): maplibregl.LngLatBoundsLike {
  // Compute bounds directly. (A previous version constructed a standalone
  // maplibregl.GeoJSONSource to do this, but that constructor needs a map
  // context and threw here — which aborted the load handler before fitBounds
  // ran, leaving the camera at world zoom 0 and the boundary an invisible
  // speck.) computeBounds handles Polygon/MultiPolygon/FeatureCollection.
  return computeBounds(geojson);
}

function computeBounds(geojson: GeoJSON.GeoJSON): maplibregl.LngLatBoundsLike {
  let minLng = Infinity;
  let minLat = Infinity;
  let maxLng = -Infinity;
  let maxLat = -Infinity;

  const walkCoords = (coords: number[][]) => {
    for (const c of coords) {
      if (Array.isArray(c[0])) {
        walkCoords(c as unknown as number[][]);
      } else if (typeof c[0] === "number" && typeof c[1] === "number") {
        const [lng, lat] = c;
        if (lng < minLng) minLng = lng;
        if (lat < minLat) minLat = lat;
        if (lng > maxLng) maxLng = lng;
        if (lat > maxLat) maxLat = lat;
      }
    }
  };

  const visit = (geom: GeoJSON.Geometry | undefined) => {
    if (!geom) return;
    switch (geom.type) {
      case "Point":
        walkCoords([geom.coordinates as unknown as number[]]);
        break;
      case "MultiPoint":
      case "LineString":
        walkCoords(geom.coordinates as unknown as number[][]);
        break;
      case "MultiLineString":
      case "Polygon":
        walkCoords(geom.coordinates as unknown as number[][]);
        break;
      case "MultiPolygon":
        for (const poly of geom.coordinates as unknown as number[][][][]) {
          walkCoords(poly as unknown as number[][]);
        }
        break;
      case "GeometryCollection":
        for (const g of geom.geometries) visit(g);
        break;
    }
  };

  if (geojson.type === "Feature") {
    visit(geojson.geometry);
  } else if (geojson.type === "FeatureCollection") {
    for (const f of geojson.features) visit(f.geometry);
  } else {
    visit(geojson);
  }

  if (!isFinite(minLng)) {
    return [[-1, 51], [1, 52]]; // fallback around England centroid
  }
  return [[minLng, minLat], [maxLng, maxLat]];
}

export interface RenderPlaceMapOptions {
  label?: string;
  tilesUrl?: string;
}

/**
 * Render a single GeoJSON Feature as a filled polygon on a tile-less map.
 * Returns a cleanup function that calls `map.remove()`.
 */
export function renderPlaceMap(
  container: HTMLElement,
  geojson: GeoJSON.Feature,
  options: RenderPlaceMapOptions = {},
): () => void {
  const map = new maplibregl.Map(
    baseMapOptions(container, options.tilesUrl),
  );

  const sourceId = "place";
  const fillId = "place-fill";
  const outlineId = "place-outline";

  map.on("load", () => {
    map.addSource(sourceId, { type: "geojson", data: geojson });

    map.addLayer({
      id: fillId,
      type: "fill",
      source: sourceId,
      paint: {
        "fill-color": ACCENT_GREEN,
        "fill-opacity": 0.3,
      },
    });

    map.addLayer({
      id: outlineId,
      type: "line",
      source: sourceId,
      paint: {
        "line-color": ACCENT_GREEN,
        "line-width": 1,
      },
    });

    map.fitBounds(featureBounds(geojson), { padding: 20 });
  });

  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  return () => map.remove();
}

export interface RenderChoroplethMapOptions {
  /** Two-stop colour scale [low, high]. Default: cream → navy via green. */
  colourScale?: [string, string];
  label?: string;
  tilesUrl?: string;
}

/**
 * Render a FeatureCollection as a choropleth, interpolating fill colour from
 * the `valueKey` property on each feature. Hover shows place name + value.
 * Returns a cleanup function that calls `map.remove()`.
 */
export function renderChoroplethMap(
  container: HTMLElement,
  featureCollection: GeoJSON.FeatureCollection,
  valueKey: string,
  options: RenderChoroplethMapOptions = {},
): () => void {
  const map = new maplibregl.Map(
    baseMapOptions(container, options.tilesUrl),
  );

  const sourceId = "choropleth";
  const fillId = "choropleth-fill";

  // Default three-stop ramp: cream → green → navy.
  const stops: [string, string] = options.colourScale ?? [CREAM, NAVY];

  map.on("load", () => {
    map.addSource(sourceId, { type: "geojson", data: featureCollection });

    map.addLayer({
      id: fillId,
      type: "fill",
      source: sourceId,
      paint: {
        "fill-color": [
          "interpolate",
          ["linear"],
          ["get", valueKey],
          0,
          stops[0],
          0.5,
          ACCENT_GREEN,
          1,
          stops[1],
        ],
        "fill-opacity": 0.85,
      },
    });

    map.addLayer({
      id: "choropleth-outline",
      type: "line",
      source: sourceId,
      paint: {
        "line-color": "#ffffff",
        "line-width": 0.5,
      },
    });

    map.fitBounds(featureBounds(featureCollection), { padding: 20 });
  });

  // Hover popup with place name + value.
  const popup: Popup = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
  });

  let hoveredId: string | number | undefined;

  map.on("mousemove", fillId, (e) => {
    const features = map.queryRenderedFeatures(e.point, { layers: [fillId] });
    if (features.length === 0) return;
    const f = features[0];
    const props = (f.properties ?? {}) as Record<string, unknown>;
    const placeName =
      (props.name as string | undefined) ??
      (props.place_name as string | undefined) ??
      (props.place_id as string | undefined) ??
      "—";
    const rawValue = props[valueKey];
    const displayValue =
      typeof rawValue === "number" ? rawValue.toLocaleString("en-GB") : String(rawValue ?? "—");
    const label = options.label ?? valueKey;
    popup.setHTML(
      `<div style="font-family:system-ui,sans-serif"><strong>${escapeHtml(placeName)}</strong><br/>${escapeHtml(label)}: ${escapeHtml(displayValue)}</div>`,
    );
    const coords = (f.geometry as GeoJSON.Point | undefined)?.coordinates;
    if (coords) {
      popup.setLngLat(coords as [number, number]);
    } else {
      popup.setLngLat(e.lngLat);
    }
    popup.addTo(map);
    hoveredId = f.id;
    map.getCanvas().style.cursor = "pointer";
  });

  map.on("mouseleave", fillId, () => {
    popup.remove();
    hoveredId = undefined;
    map.getCanvas().style.cursor = "";
  });

  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

  return () => {
    popup.remove();
    map.remove();
  };
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
