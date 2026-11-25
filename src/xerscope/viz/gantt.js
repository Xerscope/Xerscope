// WBS Gantt, a Streamlit component (app/ui.py: GANTT) drawn from the data of viz/gantt.py:
// gantt_data. Schedule text (activity and WBS names) comes from the XER file: it is only ever
// written with textContent or as a DOM property, never parsed as HTML.
export default function (component) {
  "use strict";
  const payload = component.data;
  const { setTriggerValue } = component;
  const palette = payload.palette;
  const DAY_MS = 864e5;
  const root = component.parentElement.querySelector("#gantt");
  root.replaceChildren(); // drawn again from scratch when the data change
  root.style.height = payload.height + "px";
  // page colours come from the theme in gantt.css; the bars' from the data
  root.style.setProperty("--Normal", palette.Normal);
  root.style.setProperty("--row", payload.rowPx + "px"); // the row height gantt.css reads

  // --- helpers -------------------------------------------------------------------------
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const timestampMs = (iso) => {
    if (!iso) return null;
    const [datePart, timePart] = iso.split("T");
    const [year, month, dayOfMonth] = datePart.split("-").map(Number);
    const [hour, minute] = (timePart || "00:00").split(":").map(Number);
    return Date.UTC(year, month - 1, dayOfMonth, hour, minute);
  };
  const dayText = (iso) => (iso ? iso.slice(0, 10) : "–");
  const signedText = (value, unit) => {
    if (value === null || value === undefined) return null;
    const sign = value > 0 ? "+" : "";
    return sign + value + " " + unit;
  };

  // --- tree ----------------------------------------------------------------------------
  const rows = payload.rows;
  const byId = new Map(rows.map((row) => [row.id, row]));
  const children = new Map();
  for (const row of rows) {
    if (!row.parent) continue;
    if (!children.has(row.parent)) children.set(row.parent, []);
    children.get(row.parent).push(row.id);
  }
  // the branches opened by the viewer stay open across reruns (a pick, a toggle on the page): the
  // page sends the branches it needs open (the chosen node's, every one under a filter), the host
  // element keeps the viewer's, and the two are merged; the page's epoch changes when it recomputed
  // the open branches (a filter flips, the Ask text changes) and what the browser kept is dropped
  const host = component.parentElement;
  if (host.xsEpoch !== payload.openEpoch) host.xsOpen = null;
  host.xsEpoch = payload.openEpoch;
  const open = new Set([...(host.xsOpen || []), ...payload.open]);
  host.xsOpen = open;
  const maxDepth = Math.max(0, ...rows.filter((row) => row.kind === "wbs").map((row) => row.depth));

  const visibleRows = () => {
    const shownIds = new Set();
    const visible = [];
    for (const row of rows) {
      if (!row.parent || (shownIds.has(row.parent) && open.has(row.parent))) {
        shownIds.add(row.id);
        visible.push(row);
      }
    }
    return visible;
  };

  // --- skeleton ------------------------------------------------------------------------
  const toolbar = element("div", "toolbar");
  const button = (label, onClick) => {
    const buttonElement = element("button", null, label);
    buttonElement.type = "button";
    buttonElement.addEventListener("click", onClick);
    toolbar.append(buttonElement);
    return buttonElement;
  };
  button("Collapse all", () => { open.clear(); render(); });
  button("Expand all", () => { for (const id of children.keys()) open.add(id); render(); });
  toolbar.append(element("span", "sep"), element("span", "label", "Level"));
  for (let level = 1; level <= Math.min(maxDepth + 1, 6); level++) {
    button(String(level), () => {
      open.clear();
      for (const row of rows) if (row.kind === "wbs" && row.depth < level) open.add(row.id);
      render();
    });
  }
  const legend = element("div", "legend");
  const legendItem = (swatchClass, text) => {
    const item = element("span");
    const swatch = element("i", swatchClass);
    item.append(swatch, element("span", null, text));
    legend.append(item);
    return swatch;
  };
  for (const category of payload.categories) {
    const swatch = legendItem(null, category);
    swatch.style.background = palette[category];
  }
  if (payload.compareLabel) legendItem("ring", payload.compareLabel);
  if (payload.dataDate) legendItem("dd", "Data date " + dayText(payload.dataDate));
  toolbar.append(legend);

  const scroll = element("div", "scroll");
  scroll.tabIndex = 0; // the rows scroll from the keyboard (arrow and page keys)
  const header = element("div", "head");
  const gridHeader = element("div", "ghead cols");
  gridHeader.append(element("div", null, "Activity / WBS"), element("div", null, "% complete"), element("div", null, "Float (wd)"));
  const scale = element("div", "scale");
  header.append(gridHeader, scale);
  const body = element("div", "body");
  const gridColumn = element("div", "gcol");
  const timelineColumn = element("div", "tcol");
  body.append(gridColumn, timelineColumn);
  scroll.append(header, body);
  const tip = element("div", "tip");
  root.append(toolbar, scroll, tip);

  // --- time axis -----------------------------------------------------------------------
  const windowStartMs = timestampMs(payload.window[0]);
  const windowEndMs = timestampMs(payload.window[1]);
  let width = 1;
  const pixelX = (timeMs) => ((timeMs - windowStartMs) / (windowEndMs - windowStartMs)) * width;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const monthStarts = () => {
    const starts = [];
    const start = new Date(windowStartMs);
    let year = start.getUTCFullYear();
    let month = start.getUTCMonth() + 1; // the first month boundary inside the window
    for (;;) {
      if (month === 12) { month = 0; year++; }
      const timeMs = Date.UTC(year, month, 1);
      if (timeMs > windowEndMs) return starts;
      starts.push({ timeMs, year, month });
      month++;
    }
  };
  const mondays = () => {
    const weekTicks = [];
    const first = new Date(windowStartMs);
    const daysToMonday = (8 - first.getUTCDay()) % 7 || 7;
    const firstMondayMs = Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), first.getUTCDate() + daysToMonday);
    for (let timeMs = firstMondayMs; timeMs <= windowEndMs; timeMs += 7 * DAY_MS) {
      weekTicks.push({ timeMs, label: String(new Date(timeMs).getUTCDate()).padStart(2, "0") });
    }
    return weekTicks;
  };
  // Two tiers, as in P6: month timescale = years over months, week timescale = months over weeks.
  const ticks = () => {
    const months = monthStarts();
    const startDate = new Date(windowStartMs);
    if (payload.timescale === "week") {
      const top = [{ timeMs: windowStartMs, label: MONTHS[startDate.getUTCMonth()] + " " + startDate.getUTCFullYear() }];
      for (const start of months) top.push({ timeMs: start.timeMs, label: MONTHS[start.month] + " " + start.year });
      return { top, bottom: mondays() };
    }
    const top = [{ timeMs: windowStartMs, label: String(startDate.getUTCFullYear()) }];
    for (const start of months) if (start.month === 0) top.push({ timeMs: start.timeMs, label: String(start.year) });
    return { top, bottom: months.map((start) => ({ timeMs: start.timeMs, label: MONTHS[start.month] })) };
  };

  const drawScale = ({ top, bottom }) => {
    scale.replaceChildren();
    const place = (tickList, className, minGapPx) => {
      let lastLeft = -Infinity;
      for (const tick of tickList) {
        const left = pixelX(tick.timeMs);
        if (left - lastLeft < minGapPx) continue; // too close to the previous label
        const node = element("div", className, tick.label);
        node.style.left = left + "px";
        scale.append(node);
        lastLeft = left;
      }
    };
    place(top, "tick", 70);
    place(bottom, "tick tier2", 26);
  };

  // --- tooltip -------------------------------------------------------------------------
  const tooltipLines = (row) => {
    const lines = [["Start", dayText(row.start)], ["Finish", dayText(row.finish)]];
    if (row.kind === "task") {
      lines.push(["Status", row.status], ["% complete", row.pct === null ? "–" : row.pct + " %"]);
      lines.push(["Total float", row.float_d === null ? "–" : row.float_d + " d"]);
      if (payload.compareLabel) {
        const shift = signedText(row.shift_wd, "wd");
        lines.push(["Finish vs " + payload.compareLabel, row.cmp_finish ? shift || "–" : "not in " + payload.compareLabel]);
      }
    } else {
      lines.push(["% complete", row.pct === null ? "–" : row.pct + " %"], ["Activities", row.activities]);
      const shift = signedText(row.shift_wd, "wd");
      if (shift) lines.push(["Finish vs BL (baselined tasks)", shift]);
    }
    return lines;
  };
  const showTip = (row, event) => {
    tip.replaceChildren(element("div", "title", (row.code ? row.code + "  " : "") + row.name));
    for (const [label, value] of tooltipLines(row)) tip.append(element("div", "line", label + ": " + value));
    tip.style.display = "block";
    const tipRect = tip.getBoundingClientRect();
    const left = Math.min(event.clientX + 14, window.innerWidth - tipRect.width - 8);
    const top = event.clientY + 14 + tipRect.height > window.innerHeight ? event.clientY - tipRect.height - 10 : event.clientY + 14;
    tip.style.left = Math.max(4, left) + "px";
    tip.style.top = Math.max(4, top) + "px";
  };
  const hideTip = () => { tip.style.display = "none"; };

  // --- rows ----------------------------------------------------------------------------
  // Only the rows in view (plus a margin) exist in the DOM: a 15,000-activity schedule
  // draws as fast as a small one. Events are handled once per column, not per row.
  const BUFFER = 30; // rows drawn above and below the visible ones
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
  for (const row of rows) {
    row.startMs = timestampMs(row.start);
    row.finishMs = timestampMs(row.finish);
    row.compareStartMs = timestampMs(row.cmp_start);
    row.compareFinishMs = timestampMs(row.cmp_finish);
  }
  let shown = [];
  let indexById = new Map();
  let drawn = [-1, -1];

  const gridLayer = element("div", "layer");
  const timeLayer = element("div", "layer");
  const gridLines = element("div", "layer");
  const linkSvg = document.createElementNS(SVG_NAMESPACE, "svg");
  linkSvg.setAttribute("class", "links");
  gridColumn.append(gridLayer);
  timelineColumn.append(gridLines, timeLayer, linkSvg);

  const toggle = (row) => {
    if (!children.has(row.id)) return;
    if (open.has(row.id)) open.delete(row.id); else open.add(row.id);
    render();
  };

  // the opening both columns share: its class (the row's kind, "sel" when picked), place and data-i
  const rowShell = (className, index, isSelected) => {
    const shell = element("div", className + (isSelected ? " sel" : ""));
    shell.style.top = index * payload.rowPx + "px";
    shell.dataset.i = String(index);
    return shell;
  };

  const gridRow = (row, index) => {
    const shell = rowShell("row cols " + row.kind, index, row.id === payload.selected);
    const name = element("div", "name");
    name.style.paddingLeft = 8 + row.depth * 16 + "px";
    let arrow = "";
    if (children.has(row.id)) arrow = open.has(row.id) ? "▾" : "▸";
    name.append(element("span", "toggle", arrow));
    if (row.code) name.append(element("span", "code", row.code));
    const text = element("span", "text", row.name);
    text.title = row.name;
    name.append(text);
    shell.append(name, element("div", "num", row.pct === null ? "" : row.pct), element("div", "num", row.float_d === null ? "" : row.float_d));
    return shell;
  };

  const box = (className, startMs, endMs) => {
    const node = element("div", className);
    const left = pixelX(startMs);
    node.style.left = left + "px";
    node.style.width = Math.max(2, pixelX(endMs) - left) + "px";
    return node;
  };

  const timelineRow = (row, index) => {
    const shell = rowShell("trow " + row.kind, index, row.id === payload.selected);
    if (row.kind === "wbs") {
      if (row.startMs !== null && row.finishMs !== null) shell.append(box("summary", row.startMs, row.finishMs));
      return shell;
    }
    if (row.compareStartMs !== null && row.compareFinishMs !== null && !row.milestone) {
      shell.append(box("outline", row.compareStartMs, row.compareFinishMs));
    }
    const colour = palette[row.category] || palette.Normal;
    if (row.milestone) {
      const milestoneMs = row.milestone === "start" ? row.startMs : row.finishMs;
      if (milestoneMs !== null) {
        const diamond = element("div", "diamond");
        diamond.style.left = pixelX(milestoneMs) + "px";
        diamond.style.background = colour;
        shell.append(diamond);
      }
    } else if (row.startMs !== null && row.finishMs !== null) {
      const bar = box("bar", row.startMs, row.finishMs);
      bar.style.background = colour;
      shell.append(bar);
    }
    return shell;
  };

  const drawLinks = (firstIndex, lastIndex) => {
    linkSvg.replaceChildren();
    if (!payload.links.length) return;
    const defs = document.createElementNS(SVG_NAMESPACE, "defs");
    const marker = document.createElementNS(SVG_NAMESPACE, "marker");
    for (const [name, value] of Object.entries({ id: "arrow", markerWidth: "6", markerHeight: "6", refX: "5", refY: "3", orient: "auto" })) marker.setAttribute(name, value);
    const arrowHead = document.createElementNS(SVG_NAMESPACE, "path");
    arrowHead.setAttribute("d", "M0,0 L6,3 L0,6 Z");
    marker.append(arrowHead);
    defs.append(marker);
    linkSvg.append(defs);
    for (const [predecessorId, successorId, linkType] of payload.links) {
      const predecessorIndex = indexById.get(predecessorId);
      const successorIndex = indexById.get(successorId);
      if (predecessorIndex === undefined || successorIndex === undefined) continue;
      if (Math.max(predecessorIndex, successorIndex) < firstIndex || Math.min(predecessorIndex, successorIndex) > lastIndex) continue; // crosses no drawn row
      const predecessor = byId.get(predecessorId);
      const successor = byId.get(successorId);
      const startX = pixelX(linkType === "SS" || linkType === "SF" ? predecessor.startMs : predecessor.finishMs);
      const endX = pixelX(linkType === "FF" || linkType === "SF" ? successor.finishMs : successor.startMs);
      if (!isFinite(startX) || !isFinite(endX)) continue;
      const path = document.createElementNS(SVG_NAMESPACE, "path");
      path.setAttribute("d", `M${startX},${predecessorIndex * payload.rowPx + payload.rowPx / 2} H${startX + 6} V${successorIndex * payload.rowPx + payload.rowPx / 2} H${endX}`);
      path.setAttribute("marker-end", "url(#arrow)");
      linkSvg.append(path);
    }
  };

  // rows from firstIndex to lastIndex (inclusive) that the scroll position shows, with a margin
  const windowRows = () => {
    const top = scroll.scrollTop - body.offsetTop;
    const firstIndex = Math.max(0, Math.floor(top / payload.rowPx) - BUFFER);
    const lastIndex = Math.min(shown.length - 1, Math.ceil((top + scroll.clientHeight) / payload.rowPx) + BUFFER);
    return [firstIndex, lastIndex];
  };

  const drawWindow = (force) => {
    const [firstIndex, lastIndex] = windowRows();
    if (!force && firstIndex === drawn[0] && lastIndex === drawn[1]) return;
    drawn = [firstIndex, lastIndex];
    const gridRows = [];
    const timelineRows = [];
    for (let index = firstIndex; index <= lastIndex; index++) {
      gridRows.push(gridRow(shown[index], index));
      timelineRows.push(timelineRow(shown[index], index));
    }
    gridLayer.replaceChildren(...gridRows);
    timeLayer.replaceChildren(...timelineRows);
    drawLinks(firstIndex, lastIndex);
  };

  function render() {
    width = Math.max(1, timelineColumn.clientWidth);
    shown = visibleRows();
    indexById = new Map(shown.map((row, index) => [row.id, index]));
    const height = shown.length * payload.rowPx;
    // with no row the first-paint height stays: it leaves the room the "no activity" notice needs
    if (shown.length) root.style.height = Math.min(payload.maxHeight, payload.chromePx + height) + "px";
    const marks = ticks();
    drawScale(marks);
    gridColumn.style.height = timelineColumn.style.height = height + "px";
    linkSvg.setAttribute("width", String(width));
    linkSvg.setAttribute("height", String(height));
    const lines = marks.bottom.map((tick) => {
      const line = element("div", "vline");
      line.style.left = pixelX(tick.timeMs) + "px";
      line.style.height = height + "px";
      return line;
    });
    if (payload.dataDate) {
      const line = element("div", "vline dd");
      line.style.left = pixelX(timestampMs(payload.dataDate)) + "px";
      line.style.height = height + "px";
      lines.push(line);
    }
    gridLines.replaceChildren(...lines);
    empty.style.display = shown.length ? "none" : "block";
    drawWindow(true);
  }

  const empty = element("div", "empty", "No activity matches the filters.");
  scroll.append(empty);

  // one listener per column: hover, tooltip and folding find their row through data-i
  let hovered = -1;
  const setHover = (index) => {
    if (index === hovered) return;
    for (const node of body.querySelectorAll(".hover")) node.classList.remove("hover");
    hovered = index;
    if (index >= 0) for (const node of body.querySelectorAll(`[data-i="${index}"]`)) node.classList.add("hover");
  };
  const rowIndexAt = (event) => {
    const node = event.target.closest("[data-i]");
    return node ? Number(node.dataset.i) : -1;
  };
  body.addEventListener("mousemove", (event) => {
    const index = rowIndexAt(event);
    setHover(index);
    if (index >= 0) showTip(shown[index], event); else hideTip();
  });
  body.addEventListener("mouseleave", () => { setHover(-1); hideTip(); });
  // the page scrolling under the pointer (wheel outside the chart's own scroll box): the tip would
  // stay where the row was
  window.addEventListener("scroll", hideTip, { passive: true });
  // a WBS row opens or closes; an activity row sends its row id ("a:<Activity ID>") and only
  // that: the page reads every value it shows from the loaded schedule (app/task_panel.py)
  body.addEventListener("click", (event) => {
    const index = rowIndexAt(event);
    if (index < 0) return;
    const row = shown[index];
    if (row.kind === "task") setTriggerValue("picked", row.id); else toggle(row);
  });
  // a double click on a WBS row makes it the page's focus ("w:<wbs_id>"); the two single
  // clicks before it toggled the branch twice, so it is left as it was
  body.addEventListener("dblclick", (event) => {
    const index = rowIndexAt(event);
    if (index >= 0 && shown[index].kind === "wbs") setTriggerValue("focus", shown[index].id);
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
  const selectedIndex = indexById.get(payload.selected);
  if (selectedIndex > 1) {
    scroll.scrollTop = (selectedIndex - 1) * payload.rowPx;
    drawWindow(false);
  }
  return () => {
    window.removeEventListener("resize", onResize);
    window.removeEventListener("scroll", hideTip);
  };
}
