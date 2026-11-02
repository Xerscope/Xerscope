// WBS Gantt drawn from DATA (built by viz/gantt.py: gantt_html).
// Schedule text (activity and WBS names) comes from the XER file: it is only ever written
// with textContent or as a DOM property, never parsed as HTML.
(() => {
  "use strict";
  const D = DATA;
  const P = D.palette;
  const ROW = 26; // px, same as .row / .trow in gantt.css
  const GRID_W = 420; // px, tree grid width
  const DAY = 864e5;
  const root = document.getElementById("gantt");

  const cssVars = {
    "--ink": P.ink, "--secondary": P.secondary, "--muted": P.muted, "--grid": P.grid,
    "--axis": P.axis, "--background": P.background, "--band": P.band, "--Normal": P.Normal,
    "--grid-w": GRID_W + "px",
  };
  for (const [name, value] of Object.entries(cssVars)) document.documentElement.style.setProperty(name, value);

  // --- helpers -------------------------------------------------------------------------
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const time = (iso) => {
    if (!iso) return null;
    const [d, t] = iso.split("T");
    const [y, m, day] = d.split("-").map(Number);
    const [h, min] = (t || "00:00").split(":").map(Number);
    return Date.UTC(y, m - 1, day, h, min);
  };
  const day = (iso) => (iso ? iso.slice(0, 10) : "–");
  const signed = (v, unit) => (v === null || v === undefined ? null : (v > 0 ? "+" : "") + v + " " + unit);

  // --- tree ----------------------------------------------------------------------------
  const rows = D.rows;
  const byId = new Map(rows.map((r) => [r.id, r]));
  const children = new Map();
  for (const r of rows) {
    if (!r.parent) continue;
    if (!children.has(r.parent)) children.set(r.parent, []);
    children.get(r.parent).push(r.id);
  }
  const open = new Set(D.open);
  const maxDepth = Math.max(0, ...rows.filter((r) => r.kind === "wbs").map((r) => r.depth));

  const visibleRows = () => {
    const shown = new Set();
    const out = [];
    for (const r of rows) {
      if (!r.parent || (shown.has(r.parent) && open.has(r.parent))) {
        shown.add(r.id);
        out.push(r);
      }
    }
    return out;
  };

  // --- skeleton ------------------------------------------------------------------------
  const toolbar = el("div", "toolbar");
  const button = (label, onClick) => {
    const b = el("button", null, label);
    b.type = "button";
    b.addEventListener("click", onClick);
    toolbar.append(b);
    return b;
  };
  button("Collapse all", () => { open.clear(); render(); });
  button("Expand all", () => { for (const id of children.keys()) open.add(id); render(); });
  toolbar.append(el("span", "sep"), el("span", "label", "Level"));
  for (let level = 1; level <= Math.min(maxDepth + 1, 6); level++) {
    button(String(level), () => {
      open.clear();
      for (const r of rows) if (r.kind === "wbs" && r.depth < level) open.add(r.id);
      render();
    });
  }
  const legend = el("div", "legend");
  for (const cat of D.categories) {
    const item = el("span");
    const swatch = el("i");
    swatch.style.background = P[cat];
    item.append(swatch, el("span", null, cat));
    legend.append(item);
  }
  if (D.compareLabel) {
    const item = el("span");
    item.append(el("i", "ring"), el("span", null, D.compareLabel));
    legend.append(item);
  }
  if (D.dataDate) {
    const item = el("span");
    item.append(el("i", "dd"), el("span", null, "Data date " + day(D.dataDate)));
    legend.append(item);
  }
  toolbar.append(legend);

  const scroll = el("div", "scroll");
  const head = el("div", "head");
  const ghead = el("div", "ghead cols");
  ghead.append(el("div", null, "Activity / WBS"), el("div", null, "%"), el("div", null, "Float"));
  const scale = el("div", "scale");
  head.append(ghead, scale);
  const body = el("div", "body");
  const gcol = el("div", "gcol");
  const tcol = el("div", "tcol");
  body.append(gcol, tcol);
  scroll.append(head, body);
  const tip = el("div", "tip");
  root.append(toolbar, scroll, tip);

  // --- time axis -----------------------------------------------------------------------
  const t0 = time(D.window[0]);
  const t1 = time(D.window[1]);
  let width = 1;
  const x = (t) => ((t - t0) / (t1 - t0)) * width;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const monthStarts = () => {
    const out = [];
    const start = new Date(t0);
    let y = start.getUTCFullYear();
    let m = start.getUTCMonth() + 1; // the first month boundary inside the window
    for (;;) {
      if (m === 12) { m = 0; y++; }
      const t = Date.UTC(y, m, 1);
      if (t > t1) return out;
      out.push({ t, y, m });
      m++;
    }
  };
  const mondays = () => {
    const out = [];
    const first = new Date(t0);
    const offset = (8 - first.getUTCDay()) % 7 || 7; // days to the next Monday
    for (let t = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate() + offset); t <= t1; t += 7 * DAY) {
      out.push({ t, label: String(new Date(t).getUTCDate()).padStart(2, "0") });
    }
    return out;
  };
  // Two tiers, as in P6: month timescale = years over months, week timescale = months over weeks.
  const ticks = () => {
    const months = monthStarts();
    const startDate = new Date(t0);
    if (D.timescale === "week") {
      const top = [{ t: t0, label: MONTHS[startDate.getUTCMonth()] + " " + startDate.getUTCFullYear() }];
      for (const s of months) top.push({ t: s.t, label: MONTHS[s.m] + " " + s.y });
      return { top, bottom: mondays() };
    }
    const top = [{ t: t0, label: String(startDate.getUTCFullYear()) }];
    for (const s of months) if (s.m === 0) top.push({ t: s.t, label: String(s.y) });
    return { top, bottom: months.map((s) => ({ t: s.t, label: MONTHS[s.m] })) };
  };

  const drawScale = ({ top, bottom }) => {
    scale.replaceChildren();
    const place = (list, cls, minGap) => {
      let last = -Infinity;
      for (const tick of list) {
        const left = x(tick.t);
        if (left - last < minGap) continue; // too close to the previous label
        const node = el("div", cls, tick.label);
        node.style.left = left + "px";
        scale.append(node);
        last = left;
      }
    };
    place(top, "tick", 70);
    place(bottom, "tick tier2", 26);
  };

  // --- tooltip -------------------------------------------------------------------------
  const tooltipLines = (r) => {
    const lines = [["Start", day(r.start)], ["Finish", day(r.finish)]];
    if (r.kind === "task") {
      lines.push(["Status", r.status], ["% complete", r.pct === null ? "–" : r.pct + " %"]);
      lines.push(["Total float", r.float_d === null ? "–" : r.float_d + " d"]);
      if (D.compareLabel) {
        const shift = signed(r.shift_wd, "wd");
        lines.push(["Finish vs " + D.compareLabel, r.cmp_finish ? shift || "–" : "not in " + D.compareLabel]);
      }
    } else {
      lines.push(["% complete", r.pct === null ? "–" : r.pct + " %"], ["Activities", r.activities]);
      const shift = signed(r.shift_wd, "wd");
      if (shift) lines.push(["Finish vs BL", shift]);
    }
    return lines;
  };
  const showTip = (r, event) => {
    tip.replaceChildren(el("div", "title", (r.code ? r.code + "  " : "") + r.name));
    for (const [label, value] of tooltipLines(r)) tip.append(el("div", "line", label + ": " + value));
    tip.style.display = "block";
    const box = tip.getBoundingClientRect();
    const left = Math.min(event.clientX + 14, window.innerWidth - box.width - 8);
    const top = event.clientY + 14 + box.height > window.innerHeight ? event.clientY - box.height - 10 : event.clientY + 14;
    tip.style.left = Math.max(4, left) + "px";
    tip.style.top = Math.max(4, top) + "px";
  };
  const hideTip = () => { tip.style.display = "none"; };

  // --- rows ----------------------------------------------------------------------------
  const toggle = (r) => {
    if (!children.has(r.id)) return;
    if (open.has(r.id)) open.delete(r.id); else open.add(r.id);
    render();
  };

  const gridRow = (r) => {
    const row = el("div", "row cols " + r.kind + (r.id === D.selected ? " sel" : ""));
    const name = el("div", "name");
    name.style.paddingLeft = 8 + r.depth * 16 + "px";
    const hasChildren = children.has(r.id);
    name.append(el("span", "toggle", hasChildren ? (open.has(r.id) ? "▾" : "▸") : ""));
    if (r.code) name.append(el("span", "code", r.code));
    const text = el("span", "text", r.name);
    text.title = r.name;
    name.append(text);
    row.append(name, el("div", "num", r.pct === null ? "" : r.pct), el("div", "num", r.float_d === null ? "" : r.float_d));
    if (r.kind === "wbs") row.addEventListener("click", () => toggle(r));
    return row;
  };

  const box = (cls, a, b) => {
    const node = el("div", cls);
    const left = x(a);
    node.style.left = left + "px";
    node.style.width = Math.max(2, x(b) - left) + "px";
    return node;
  };

  const timelineRow = (r, index) => {
    const row = el("div", "trow " + r.kind + (r.id === D.selected ? " sel" : ""));
    row.style.top = index * ROW + "px";
    const start = time(r.start);
    const finish = time(r.finish);
    if (r.kind === "wbs") {
      if (start !== null && finish !== null) row.append(box("summary", start, finish));
      return row;
    }
    const cs = time(r.cmp_start);
    const cf = time(r.cmp_finish);
    if (cs !== null && cf !== null && !r.milestone) row.append(box("outline", cs, cf));
    const colour = P[r.category] || P.Normal;
    if (r.milestone) {
      const at = r.milestone === "start" ? start : finish;
      if (at !== null) {
        const diamond = el("div", "diamond");
        diamond.style.left = x(at) + "px";
        diamond.style.background = colour;
        row.append(diamond);
      }
    } else if (start !== null && finish !== null) {
      const bar = box("bar", start, finish);
      bar.style.background = colour;
      row.append(bar);
    }
    return row;
  };

  const linkLayer = (shown) => {
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "links");
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(shown.length * ROW));
    const defs = document.createElementNS(NS, "defs");
    const marker = document.createElementNS(NS, "marker");
    for (const [k, v] of Object.entries({ id: "arrow", markerWidth: "6", markerHeight: "6", refX: "5", refY: "3", orient: "auto" })) marker.setAttribute(k, v);
    const head = document.createElementNS(NS, "path");
    head.setAttribute("d", "M0,0 L6,3 L0,6 Z");
    marker.append(head);
    defs.append(marker);
    svg.append(defs);
    const index = new Map(shown.map((r, i) => [r.id, i]));
    for (const [pred, succ, kind] of D.links) {
      if (!index.has(pred) || !index.has(succ)) continue;
      const p = byId.get(pred);
      const s = byId.get(succ);
      const x0 = x(time(kind === "SS" || kind === "SF" ? p.start : p.finish));
      const x1 = x(time(kind === "FF" || kind === "SF" ? s.finish : s.start));
      const y0 = index.get(pred) * ROW + ROW / 2;
      const y1 = index.get(succ) * ROW + ROW / 2;
      if (!isFinite(x0) || !isFinite(x1)) continue;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", `M${x0},${y0} H${x0 + 6} V${y1} H${x1}`);
      path.setAttribute("marker-end", "url(#arrow)");
      svg.append(path);
    }
    return svg;
  };

  // --- render --------------------------------------------------------------------------
  function render() {
    width = Math.max(1, tcol.clientWidth);
    const shown = visibleRows();
    const marks = ticks();
    drawScale(marks);
    gcol.replaceChildren();
    tcol.replaceChildren();
    tcol.style.height = shown.length * ROW + "px";
    if (!shown.length) {
      gcol.append(el("div", "empty", "No activity matches the filters."));
      return;
    }
    for (const t of marks.bottom) {
      const line = el("div", "vline");
      line.style.left = x(t.t) + "px";
      line.style.height = shown.length * ROW + "px";
      tcol.append(line);
    }
    if (D.dataDate) {
      const line = el("div", "vline dd");
      line.style.left = x(time(D.dataDate)) + "px";
      line.style.height = shown.length * ROW + "px";
      tcol.append(line);
    }
    shown.forEach((r, i) => {
      const g = gridRow(r);
      const t = timelineRow(r, i);
      for (const node of [g, t]) {
        node.addEventListener("mousemove", (event) => showTip(r, event));
        node.addEventListener("mouseenter", () => { g.classList.add("hover"); t.classList.add("hover"); });
        node.addEventListener("mouseleave", () => { g.classList.remove("hover"); t.classList.remove("hover"); hideTip(); });
      }
      t.addEventListener("click", () => toggle(r));
      gcol.append(g);
      tcol.append(t);
    });
    if (D.links.length) tcol.append(linkLayer(shown));
  }

  render();
  const selectedIndex = visibleRows().findIndex((r) => r.id === D.selected);
  if (selectedIndex > 1) scroll.scrollTop = (selectedIndex - 1) * ROW;
  window.addEventListener("resize", render);
})();
