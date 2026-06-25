      import { streamAsk } from "../lib/answer_stream";

      const surface = document.getElementById("answer-surface");
      if (surface) {
        const apiBase = surface.dataset.apiBase ?? "";
        const mode = surface.dataset.mode || "summary";
        const placeId = surface.dataset.placeId || undefined;
        // Read the question from the surface's data attribute — NOT
        // `querySelector("h1")`, which returns the layout's "Soundings" header
        // (the first h1 on the page) instead of the question.
        const query = surface.dataset.query || "";

        function setStatus(message: string) {
          let el = surface.querySelector<HTMLElement>(".answer-status");
          if (!el) {
            el = document.createElement("p");
            el.className = "answer-status";
            surface.appendChild(el);
          }
          el.textContent = message;
        }

        function renderMarkdown(text: string): string {
          // Minimal markdown: paragraphs, **bold**, *italic*, `code`, line breaks.
          const esc = (s: string) =>
            s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
          const lines = esc(text).split("\n");
          const out: string[] = [];
          let inList = false;
          for (const line of lines) {
            if (/^\s*[-*]\s+/.test(line)) {
              if (!inList) {
                out.push("<ul>");
                inList = true;
              }
              out.push("<li>" + line.replace(/^\s*[-*]\s+/, "") + "</li>");
            } else {
              if (inList) {
                out.push("</ul>");
                inList = false;
              }
              if (line.trim().length === 0) {
                out.push("");
              } else {
                out.push("<p>" + line + "</p>");
              }
            }
          }
          if (inList) out.push("</ul>");
          return out
            .join("\n")
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/\*([^*]+)\*/g, "<em>$1</em>")
            .replace(
              /`([^`]+)`/g,
              '<code class="inline-code">$1</code>',
            );
        }

        // --- Block renderers -------------------------------------------------

        // Shared POST helper for the /v1/tools/* endpoints. The browser
        // cookie jar is used automatically via `credentials: "include"`.
        async function postJSON<T>(
          path: string,
          body: unknown,
          base: string,
        ): Promise<T> {
          const response = await fetch(base + path, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/json",
            },
            body: JSON.stringify(body),
            credentials: "include",
          });
          if (!response.ok) {
            throw new Error(`${path} ${response.status} ${response.statusText}`);
          }
          return (await response.json()) as T;
        }

        async function getJSON<T>(path: string, base: string): Promise<T> {
          const response = await fetch(base + path, {
            headers: { Accept: "application/json" },
            credentials: "include",
          });
          if (!response.ok) {
            throw new Error(`${path} ${response.status} ${response.statusText}`);
          }
          return (await response.json()) as T;
        }

        function showBlockError(host: HTMLElement, message: string) {
          const el = document.createElement("p");
          el.className = "block-error";
          el.textContent = message;
          host.appendChild(el);
        }

        function asString(v: unknown): string {
          return typeof v === "string" ? v : "";
        }

        function asStringOrUndef(v: unknown): string | undefined {
          return typeof v === "string" && v.length > 0 ? v : undefined;
        }

        function asStringArray(v: unknown): string[] {
          return Array.isArray(v)
            ? v.filter((x): x is string => typeof x === "string")
            : [];
        }

        function formatValue(value: number | null): string {
          if (value === null) return "—";
          if (!Number.isFinite(value)) return String(value);
          if (Number.isInteger(value)) return value.toLocaleString("en-GB");
          return value.toPrecision(3);
        }

        function prettyKey(key: string): string {
          const [head, ...rest] = key.split(".");
          const headPretty = head
            ? head[0]!.toUpperCase() + head.slice(1)
            : key;
          const tail = rest.join(" · ").replaceAll("_", " ");
          return tail ? `${headPretty}: ${tail}` : headPretty;
        }

        // indicator-card -----------------------------------------------------

        interface IndicatorValueLike {
          place_id: string;
          indicator: string;
          value: number | null;
          unit: string;
          period: string;
          source: { source_label: string; cache_status?: string };
          confidence?: string;
          higher_is?: string | null;
          benchmark_percentile?: number | null;
          caveats?: string[];
        }

        interface PlaceProfileResponse {
          place: { id: string; name: string; type: string };
          indicators: IndicatorValueLike[];
        }

        async function renderIndicatorCard(
          host: HTMLElement,
          block: { type: string; [k: string]: unknown },
          apiBase: string,
        ) {
          const indicatorKey = asString(block.indicator_key);
          const placeId = asString(block.place_id);
          const period = asStringOrUndef(block.period);
          if (!indicatorKey || !placeId) {
            showBlockError(host, "Indicator card missing indicator_key or place_id.");
            return;
          }
          let profile: PlaceProfileResponse;
          try {
            profile = await postJSON<PlaceProfileResponse>(
              "/v1/tools/get_place_profile",
              { place_id: placeId, include: [] },
              apiBase,
            );
          } catch (err) {
            showBlockError(
              host,
              "Could not load indicator: " +
                (err instanceof Error ? err.message : String(err)),
            );
            return;
          }
          const matches = profile.indicators.filter(
            (iv) => iv.indicator === indicatorKey,
          );
          const ind =
            matches.length > 1 && period
              ? matches.find((iv) => iv.period === period) ?? matches[0]
              : matches[0];
          if (!ind) {
            showBlockError(
              host,
              `No data for indicator "${indicatorKey}" at ${placeId}.`,
            );
            return;
          }
          host.appendChild(buildIndicatorCard(ind));
        }

        function buildIndicatorCard(ind: IndicatorValueLike): HTMLElement {
          const article = document.createElement("article");
          article.className = "indicator-card";
          const header = document.createElement("header");
          const h4 = document.createElement("h4");
          h4.textContent = prettyKey(ind.indicator);
          header.appendChild(h4);
          if (ind.source.cache_status) {
            const cache = document.createElement("span");
            cache.className = "cache-status cache-" + ind.source.cache_status;
            cache.textContent = ind.source.cache_status;
            header.appendChild(cache);
          }
          article.appendChild(header);

          const valueRow = document.createElement("div");
          valueRow.className = "value-row";
          const valueP = document.createElement("p");
          valueP.className = "value";
          const numberSpan = document.createElement("span");
          numberSpan.className = "number";
          numberSpan.textContent = formatValue(ind.value);
          valueP.appendChild(numberSpan);
          if (ind.unit) {
            const unitSpan = document.createElement("span");
            unitSpan.className = "unit";
            unitSpan.textContent = ind.unit;
            valueP.appendChild(unitSpan);
          }
          valueRow.appendChild(valueP);

          const benchmark =
            typeof ind.benchmark_percentile === "number"
              ? ind.benchmark_percentile
              : null;
          if (benchmark !== null) {
            const bench = document.createElement("div");
            bench.className = "benchmark";
            const ctx = document.createElement("span");
            ctx.className = "context";
            ctx.textContent = "p" + Math.round(benchmark);
            bench.appendChild(ctx);
            const higherIs = ind.higher_is ?? null;
            if (higherIs === "better" || higherIs === "worse") {
              const dir = document.createElement("span");
              dir.className =
                "direction " +
                (higherIs === "better" ? "good" : "bad");
              dir.textContent = higherIs === "better" ? "↑" : "↓";
              bench.appendChild(dir);
            }
            valueRow.appendChild(bench);
          }
          article.appendChild(valueRow);

          const metaRow = document.createElement("div");
          metaRow.className = "meta-row";
          const periodP = document.createElement("p");
          periodP.className = "period";
          periodP.textContent = ind.period + " · ";
          const sourceLabel = document.createElement("span");
          sourceLabel.className = "source-label";
          sourceLabel.textContent = ind.source.source_label;
          periodP.appendChild(sourceLabel);
          metaRow.appendChild(periodP);
          if (ind.confidence) {
            const badge = document.createElement("span");
            badge.className = "confidence-badge " + ind.confidence;
            badge.textContent = ind.confidence;
            metaRow.appendChild(badge);
          }
          article.appendChild(metaRow);

          if (ind.caveats && ind.caveats.length > 0) {
            const ul = document.createElement("ul");
            ul.className = "caveats";
            for (const c of ind.caveats) {
              const li = document.createElement("li");
              li.textContent = c;
              ul.appendChild(li);
            }
            article.appendChild(ul);
          }
          return article;
        }

        // trend-chart --------------------------------------------------------

        interface TrendResponse {
          trend: {
            place_id: string;
            indicator: string;
            unit: string;
            points: { period: string; value: number | null; revised?: boolean }[];
          } | null;
        }

        async function renderTrendChartBlock(
          host: HTMLElement,
          block: { type: string; [k: string]: unknown },
          apiBase: string,
        ) {
          const indicatorKey = asString(block.indicator_key);
          const caption = asStringOrUndef(block.caption);
          if (!indicatorKey) {
            showBlockError(host, "Trend chart missing indicator_key.");
            return;
          }
          // The block carries place_id; fall back to the page-level place
          // context if the server omitted it.
          const trendPlaceId = asStringOrUndef(block.place_id) ?? placeId;
          if (!trendPlaceId) {
            showBlockError(host, "Trend chart missing place_id.");
            return;
          }
          let trend: TrendResponse;
          try {
            trend = await postJSON<TrendResponse>(
              "/v1/tools/get_trend",
              { place_id: trendPlaceId, indicator: indicatorKey },
              apiBase,
            );
          } catch (err) {
            showBlockError(
              host,
              "Could not load trend: " +
                (err instanceof Error ? err.message : String(err)),
            );
            return;
          }
          if (!trend.trend || trend.trend.points.length === 0) {
            showBlockError(host, "No trend data available.");
            return;
          }
          const { renderTrendChart } = await import("../lib/chart");
          const svg = renderTrendChart(
            {
              points: trend.trend.points,
              unit: trend.trend.unit,
              caption,
            },
            { containerWidth: host.clientWidth || 480 },
          );
          if (!svg) {
            showBlockError(host, "No trend data available.");
            return;
          }
          const figure = document.createElement("figure");
          figure.className = "trend-chart-block";
          const chartDiv = document.createElement("div");
          chartDiv.className = "chart";
          chartDiv.innerHTML = svg;
          figure.appendChild(chartDiv);
          if (caption) {
            const figcaption = document.createElement("figcaption");
            figcaption.textContent = caption;
            figure.appendChild(figcaption);
          }
          host.appendChild(figure);
        }

        // compare-chart ------------------------------------------------------

        interface CompareResponse {
          results: {
            indicator: string;
            unit: string;
            period: string;
            values: {
              place_id: string;
              value: number | null;
              rank?: number | null;
              percentile?: number | null;
            }[];
          }[];
        }

        async function renderCompareChartBlock(
          host: HTMLElement,
          block: { type: string; [k: string]: unknown },
          apiBase: string,
        ) {
          const indicatorKey = asString(block.indicator_key);
          const placeIds = asStringArray(block.place_ids);
          const basis = asStringOrUndef(block.basis) ?? "percentile";
          if (!indicatorKey || placeIds.length < 2) {
            showBlockError(
              host,
              "Compare chart needs an indicator_key and at least two place_ids.",
            );
            return;
          }
          let compare: CompareResponse;
          try {
            compare = await postJSON<CompareResponse>(
              "/v1/tools/compare_places",
              {
                place_ids: placeIds,
                indicators: [indicatorKey],
                comparison_basis: basis,
              },
              apiBase,
            );
          } catch (err) {
            showBlockError(
              host,
              "Could not load comparison: " +
                (err instanceof Error ? err.message : String(err)),
            );
            return;
          }
          const comparison = compare.results.find(
            (r) => r.indicator === indicatorKey,
          );
          if (!comparison || comparison.values.length === 0) {
            showBlockError(host, "No comparison data available.");
            return;
          }
          const heading = document.createElement("h4");
          heading.className = "compare-heading";
          heading.textContent = prettyKey(comparison.indicator);
          host.appendChild(heading);
          const { renderCompareBars } = await import("../lib/chart");
          const svg = renderCompareBars(comparison, {
            basis: basis as "percentile" | "rank" | "absolute" | "rate",
            containerWidth: host.clientWidth || 480,
          });
          if (!svg) {
            showBlockError(host, "No comparison data available.");
            return;
          }
          const chartDiv = document.createElement("div");
          chartDiv.className = "chart";
          chartDiv.innerHTML = svg;
          host.appendChild(chartDiv);
        }

        // organisations -------------------------------------------------------

        interface OrganisationsResponse {
          organisations: {
            id: string;
            name: string;
            classification: string[];
            recent_grants: {
              funder: string;
              amount: number;
              currency: string;
              date: string;
              purpose: string | null;
            }[];
          }[];
        }

        async function renderOrganisationsBlock(
          host: HTMLElement,
          block: { type: string; [k: string]: unknown },
          apiBase: string,
        ) {
          const placeId = asString(block.place_id);
          const limit =
            typeof block.limit === "number" && block.limit > 0
              ? Math.floor(block.limit)
              : 5;
          if (!placeId) {
            showBlockError(host, "Organisations block missing place_id.");
            return;
          }
          let orgs: OrganisationsResponse;
          try {
            orgs = await postJSON<OrganisationsResponse>(
              "/v1/tools/find_organisations_in_place",
              { place_id: placeId, limit },
              apiBase,
            );
          } catch (err) {
            showBlockError(
              host,
              "Could not load organisations: " +
                (err instanceof Error ? err.message : String(err)),
            );
            return;
          }
          if (orgs.organisations.length === 0) {
            const p = document.createElement("p");
            p.className = "text-muted";
            p.textContent = "No organisations found for this place.";
            host.appendChild(p);
            return;
          }
          const list = document.createElement("div");
          list.className = "org-list";
          for (const org of orgs.organisations) {
            const card = document.createElement("article");
            card.className = "card org-card";
            const h4 = document.createElement("h4");
            h4.textContent = org.name;
            card.appendChild(h4);
            if (org.classification.length > 0) {
              const cls = document.createElement("p");
              cls.className = "text-muted text-small";
              cls.textContent = org.classification.join(", ");
              card.appendChild(cls);
            }
            if (org.recent_grants.length > 0) {
              const grants = document.createElement("ul");
              grants.className = "org-grants";
              for (const g of org.recent_grants) {
                const li = document.createElement("li");
                const amount = g.amount.toLocaleString("en-GB", {
                  style: "currency",
                  currency: g.currency || "GBP",
                  maximumFractionDigits: 0,
                });
                li.textContent = `${g.funder}: ${amount} (${g.date})`;
                if (g.purpose) {
                  const purpose = document.createElement("span");
                  purpose.className = "text-muted";
                  purpose.textContent = " — " + g.purpose;
                  li.appendChild(purpose);
                }
                grants.appendChild(li);
              }
              card.appendChild(grants);
            }
            list.appendChild(card);
          }
          host.appendChild(list);
        }

        // map -----------------------------------------------------------------

        let maplibreCssLoaded = false;
        function ensureMaplibreCss() {
          if (maplibreCssLoaded) return;
          maplibreCssLoaded = true;
          const link = document.createElement("link");
          link.rel = "stylesheet";
          link.href =
            "https://unpkg.com/maplibre-gl@5/dist/maplibre-gl.css";
          document.head.appendChild(link);
        }

        async function renderMapBlock(
          host: HTMLElement,
          block: { type: string; [k: string]: unknown },
          apiBase: string,
        ) {
          const placeId = asString(block.place_id);
          const indicatorKey = asStringOrUndef(block.indicator_key);
          const period = asStringOrUndef(block.period);
          const caption = asStringOrUndef(block.caption);
          if (!placeId) {
            showBlockError(host, "Map block missing place_id.");
            return;
          }
          ensureMaplibreCss();
          const container = document.createElement("div");
          container.className = "map-container";
          host.appendChild(container);
          try {
            // Dynamic-import the map renderer (which in turn pulls in
            // maplibre-gl) only when a map block is encountered.
            const { renderPlaceMap, renderChoroplethMap } = await import(
              "../lib/map-renderer"
            );
            if (indicatorKey) {
              const fc = await getJSON<GeoJSON.FeatureCollection>(
                `/v1/place/${encodeURIComponent(placeId)}/peers/geometry` +
                  `?indicator=${encodeURIComponent(indicatorKey)}` +
                  (period ? `&period=${encodeURIComponent(period)}` : ""),
                apiBase,
              );
              renderChoroplethMap(container, fc, "value", {
                label: prettyKey(indicatorKey),
              });
            } else {
              const feature = await getJSON<GeoJSON.Feature>(
                `/v1/place/${encodeURIComponent(placeId)}/geometry`,
                apiBase,
              );
              renderPlaceMap(container, feature);
            }
          } catch (err) {
            container.remove();
            showBlockError(
              host,
              "Could not load map: " +
                (err instanceof Error ? err.message : String(err)),
            );
            return;
          }
          if (caption) {
            const figcaption = document.createElement("p");
            figcaption.className = "map-caption text-muted text-small";
            figcaption.textContent = caption;
            host.appendChild(figcaption);
          }
        }

        function renderBlock(block: { type: string; [k: string]: unknown }) {
          const host = document.createElement("div");
          host.className = "answer-block block-" + block.type;
          switch (block.type) {
            case "text": {
              // Server schema (TextBlock) names this field `markdown`, not `text`.
              const text =
                typeof block.markdown === "string" ? block.markdown : "";
              const div = document.createElement("div");
              div.className = "answer-text";
              div.innerHTML = renderMarkdown(text);
              host.appendChild(div);
              break;
            }
            case "insight-callout": {
              const severity =
                typeof block.severity === "string" ? block.severity : "notable";
              const headline =
                typeof block.headline === "string" ? block.headline : "";
              const evidence =
                typeof block.evidence === "string" ? block.evidence : "";
              const callout = document.createElement("div");
              callout.className =
                "insight-callout severity-" + severity;
              const h = document.createElement("p");
              h.className = "callout-headline";
              h.textContent = headline;
              callout.appendChild(h);
              if (evidence) {
                const e = document.createElement("p");
                e.className = "callout-evidence";
                e.textContent = evidence;
                callout.appendChild(e);
              }
              host.appendChild(callout);
              break;
            }
            case "indicator-card": {
              renderIndicatorCard(host, block, apiBase);
              break;
            }
            case "trend-chart": {
              renderTrendChartBlock(host, block, apiBase);
              break;
            }
            case "compare-chart": {
              renderCompareChartBlock(host, block, apiBase);
              break;
            }
            case "map": {
              renderMapBlock(host, block, apiBase);
              break;
            }
            case "organisations": {
              renderOrganisationsBlock(host, block, apiBase);
              break;
            }
            default: {
              const ph = document.createElement("div");
              ph.className = "block-placeholder block-unknown";
              ph.textContent = "Unknown block: " + JSON.stringify(block);
              host.appendChild(ph);
            }
          }
          surface.appendChild(host);
        }

        function renderSources(sources: { source_id?: string; source_label?: string; publisher?: string; dataset_url?: string }[]) {
          const footer = document.getElementById("answer-sources");
          if (!footer) return;
          footer.innerHTML = "";
          if (sources.length === 0) return;
          const sec = document.createElement("section");
          sec.className = "sources-footer";
          const h = document.createElement("h3");
          h.textContent = "Sources";
          sec.appendChild(h);
          const ul = document.createElement("ul");
          for (const ref of sources) {
            const li = document.createElement("li");
            if (ref.dataset_url) {
              const a = document.createElement("a");
              a.href = ref.dataset_url;
              a.target = "_blank";
              a.rel = "noopener";
              a.textContent = ref.source_label || ref.source_id || "source";
              li.appendChild(a);
            } else {
              li.textContent = ref.source_label || ref.source_id || "source";
            }
            if (ref.publisher) {
              const span = document.createElement("span");
              span.className = "source-publisher";
              span.textContent = " · " + ref.publisher;
              li.appendChild(span);
            }
            ul.appendChild(li);
          }
          sec.appendChild(ul);
          footer.appendChild(sec);
        }

        function renderError(message: string) {
          surface.innerHTML = "";
          const div = document.createElement("div");
          div.className = "answer-error";
          const p = document.createElement("p");
          p.textContent = "Sorry — something went wrong: " + message;
          div.appendChild(p);
          const retry = document.createElement("a");
          retry.href = window.location.pathname + window.location.search;
          retry.textContent = "Retry";
          div.appendChild(retry);
          surface.appendChild(div);
        }

        const body: Record<string, unknown> = { query, mode };
        if (placeId) body.place_id = placeId;

        // Clear the "Thinking…" status placeholder once first event arrives.
        let firstEvent = true;

        streamAsk(apiBase + "/v1/ask", body, (event) => {
          if (firstEvent && event.type !== "status") {
            const s = surface.querySelector(".answer-status");
            if (s) s.remove();
            firstEvent = false;
          }
          switch (event.type) {
            case "status":
              setStatus(event.message);
              break;
            case "block":
              if (firstEvent) {
                const s = surface.querySelector(".answer-status");
                if (s) s.remove();
                firstEvent = false;
              }
              renderBlock(event.block);
              break;
            case "sources":
              renderSources(event.sources);
              break;
            case "done":
              setStatus("");
              const s = surface.querySelector(".answer-status");
              if (s && s.textContent === "") s.remove();
              break;
            case "error":
              renderError(event.message);
              break;
          }
        }).catch((err) => {
          renderError(err instanceof Error ? err.message : String(err));
        });
      }
