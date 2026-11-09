// WBS Gantt, a Streamlit component (app/ui.py: GANTT) drawn from the data of viz/gantt.py:
// gantt_data. Schedule text (activity and WBS names) comes from the XER file: it is only ever
// written with textContent or as a DOM property, never parsed as HTML.
export default function (component) {
  "use strict";
  const D = component.data;
  const { setTriggerValue } = component;
  const P = D.palette;
  const ROW = 26; // px, same as .row / .trow in gantt.css
  const GRID_W = 420; // px, tree grid width
  const DAY = 864e5;
  const root = component.parentElement.querySelector("#gantt");
  root.replaceChildren(); // drawn again from scratch when the data change
  root.style.height = D.height + "px";
  // page colours come from the theme in gantt.css; the bars' from the data
  root.style.setProperty("--Normal", P.Normal);
  root.style.setProperty("--grid-w", GRID_W + "px");

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
  // the branches opened by the viewer stay open across reruns (a pick, a toggle on the page): the
  // page sends the branches it needs open (the chosen node's, every one under a filter), the host
  // element keeps the viewer's, and the two are merged
  const host = component.parentElement;
  const open = new Set([...(host.xsOpen || []), ...D.open]);
  host.xsOpen = open;
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
      if (shift) lines.push(["Finish vs BL (baselined tasks)", shift]);
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
  // Only the rows in view (plus a margin) exist in the DOM: a 15,000-activity schedule
  // draws as fast as a small one. Events are handled once per column, not per row.
  const BUFFER = 30; // rows drawn above and below the visible ones
  const NS = "http://www.w3.org/2000/svg";
  for (const r of rows) {
    r.t0 = time(r.start); r.t1 = time(r.finish);
    r.c0 = time(r.cmp_start); r.c1 = time(r.cmp_finish);
  }
  let shown = [];
  let index = new Map();
  let drawn = [-1, -1];

  const gridLayer = el("div", "layer");
  const timeLayer = el("div", "layer");
  const gridLines = el("div", "layer");
  const linkSvg = document.createElementNS(NS, "svg");
  linkSvg.setAttribute("class", "links");
  gcol.append(gridLayer);
  tcol.append(gridLines, timeLayer, linkSvg);

  const toggle = (r) => {
    if (!children.has(r.id)) return;
    if (open.has(r.id)) open.delete(r.id); else open.add(r.id);
    render();
  };

  const gridRow = (r, i) => {
    const row = el("div", "row cols " + r.kind + (r.id === D.selected ? " sel" : ""));
    row.style.top = i * ROW + "px";
    row.dataset.i = String(i);
    const name = el("div", "name");
    name.style.paddingLeft = 8 + r.depth * 16 + "px";
    name.append(el("span", "toggle", children.has(r.id) ? (open.has(r.id) ? "▾" : "▸") : ""));
    if (r.code) name.append(el("span", "code", r.code));
    const text = el("span", "text", r.name);
    text.title = r.name;
    name.append(text);
    row.append(name, el("div", "num", r.pct === null ? "" : r.pct), el("div", "num", r.float_d === null ? "" : r.float_d));
    return row;
  };

  const box = (cls, a, b) => {
    const node = el("div", cls);
    const left = x(a);
    node.style.left = left + "px";
    node.style.width = Math.max(2, x(b) - left) + "px";
    return node;
  };

  const timelineRow = (r, i) => {
    const row = el("div", "trow " + r.kind + (r.id === D.selected ? " sel" : ""));
    row.style.top = i * ROW + "px";
    row.dataset.i = String(i);
    if (r.kind === "wbs") {
      if (r.t0 !== null && r.t1 !== null) row.append(box("summary", r.t0, r.t1));
      return row;
    }
    if (r.c0 !== null && r.c1 !== null && !r.milestone) row.append(box("outline", r.c0, r.c1));
    const colour = P[r.category] || P.Normal;
    if (r.milestone) {
      const at = r.milestone === "start" ? r.t0 : r.t1;
      if (at !== null) {
        const diamond = el("div", "diamond");
        diamond.style.left = x(at) + "px";
        diamond.style.background = colour;
        row.append(diamond);
      }
    } else if (r.t0 !== null && r.t1 !== null) {
      const bar = box("bar", r.t0, r.t1);
      bar.style.background = colour;
      row.append(bar);
    }
    return row;
  };

  const drawLinks = (first, last) => {
    linkSvg.replaceChildren();
    if (!D.links.length) return;
    const defs = document.createElementNS(NS, "defs");
    const marker = document.createElementNS(NS, "marker");
    for (const [k, v] of Object.entries({ id: "arrow", markerWidth: "6", markerHeight: "6", refX: "5", refY: "3", orient: "auto" })) marker.setAttribute(k, v);
    const head = document.createElementNS(NS, "path");
    head.setAttribute("d", "M0,0 L6,3 L0,6 Z");
    marker.append(head);
    defs.append(marker);
    linkSvg.append(defs);
    for (const [pred, succ, kind] of D.links) {
      const i0 = index.get(pred);
      const i1 = index.get(succ);
      if (i0 === undefined || i1 === undefined) continue;
      if (Math.max(i0, i1) < first || Math.min(i0, i1) > last) continue; // crosses no drawn row
      const p = byId.get(pred);
      const s = byId.get(succ);
      const x0 = x(kind === "SS" || kind === "SF" ? p.t0 : p.t1);
      const x1 = x(kind === "FF" || kind === "SF" ? s.t1 : s.t0);
      if (!isFinite(x0) || !isFinite(x1)) continue;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", `M${x0},${i0 * ROW + ROW / 2} H${x0 + 6} V${i1 * ROW + ROW / 2} H${x1}`);
      path.setAttribute("marker-end", "url(#arrow)");
      linkSvg.append(path);
    }
  };

  // rows from first to last (inclusive) that the scroll position shows, with a margin
  const windowRows = () => {
    const top = scroll.scrollTop - body.offsetTop;
    const first = Math.max(0, Math.floor(top / ROW) - BUFFER);
    const last = Math.min(shown.length - 1, Math.ceil((top + scroll.clientHeight) / ROW) + BUFFER);
    return [first, last];
  };

  const drawWindow = (force) => {
    const [first, last] = windowRows();
    if (!force && first === drawn[0] && last === drawn[1]) return;
    drawn = [first, last];
    const g = [];
    const t = [];
    for (let i = first; i <= last; i++) {
      g.push(gridRow(shown[i], i));
      t.push(timelineRow(shown[i], i));
    }
    gridLayer.replaceChildren(...g);
    timeLayer.replaceChildren(...t);
    drawLinks(first, last);
  };

  function render() {
    width = Math.max(1, tcol.clientWidth);
    shown = visibleRows();
    index = new Map(shown.map((r, i) => [r.id, i]));
    const height = shown.length * ROW;
    const marks = ticks();
    drawScale(marks);
    gcol.style.height = tcol.style.height = height + "px";
    linkSvg.setAttribute("width", String(width));
    linkSvg.setAttribute("height", String(height));
    const lines = marks.bottom.map((tick) => {
      const line = el("div", "vline");
      line.style.left = x(tick.t) + "px";
      line.style.height = height + "px";
      return line;
    });
    if (D.dataDate) {
      const line = el("div", "vline dd");
      line.style.left = x(time(D.dataDate)) + "px";
      line.style.height = height + "px";
      lines.push(line);
    }
    gridLines.replaceChildren(...lines);
    empty.style.display = shown.length ? "none" : "block";
    drawWindow(true);
  }

  const empty = el("div", "empty", "No activity matches the filters.");
  scroll.append(empty);

  // one listener per column: hover, tooltip and folding find their row through data-i
  let hovered = -1;
  const setHover = (i) => {
    if (i === hovered) return;
    for (const node of body.querySelectorAll(".hover")) node.classList.remove("hover");
    hovered = i;
    if (i >= 0) for (const node of body.querySelectorAll(`[data-i="${i}"]`)) node.classList.add("hover");
  };
  const rowAt = (event) => {
    const node = event.target.closest("[data-i]");
    return node ? Number(node.dataset.i) : -1;
  };
  body.addEventListener("mousemove", (event) => {
    const i = rowAt(event);
    setHover(i);
    if (i >= 0) showTip(shown[i], event); else hideTip();
  });
  body.addEventListener("mouseleave", () => { setHover(-1); hideTip(); });
  // the page scrolling under the pointer (wheel outside the chart's own scroll box): the tip would
  // stay where the row was
  window.addEventListener("scroll", hideTip, { passive: true });
  // a WBS row opens or closes; an activity row sends its row id ("a:<Activity ID>") and only
  // that: the page reads every value it shows from the loaded schedule (app/task_panel.py)
  body.addEventListener("click", (event) => {
    const i = rowAt(event);
    if (i < 0) return;
    const r = shown[i];
    if (r.kind === "task") setTriggerValue("picked", r.id); else toggle(r);
  });
  // a double click on a WBS row makes it the page's focus ("w:<wbs_id>"); the two single
  // clicks before it toggled the branch twice, so it is left as it was
  body.addEventListener("dblclick", (event) => {
    const i = rowAt(event);
    if (i >= 0 && shown[i].kind === "wbs") setTriggerValue("focus", shown[i].id);
  });

  let pending = false;
  scroll.addEventListener("scroll", () => {
    hideTip();
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; drawWindow(false); });
  });
  const onResize = () => render();
  window.addEventListener("resize", onResize);

  render();
  const selectedIndex = index.get(D.selected);
  if (selectedIndex > 1) {
    scroll.scrollTop = (selectedIndex - 1) * ROW;
    drawWindow(false);
  }
  return () => {
    window.removeEventListener("resize", onResize);
    window.removeEventListener("scroll", hideTip);
  };
}
