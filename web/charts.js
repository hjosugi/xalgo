/* xalgo — 軽量チャート（外部ライブラリなし） */
(() => {
  "use strict";

  const SVG = "http://www.w3.org/2000/svg";

  function svgEl(name, attrs) {
    const node = document.createElementNS(SVG, name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    return node;
  }

  function renderBars(container, data, options) {
    const max = options.max || Math.max(...data.map((d) => Math.abs(d.value)), 0.0001);
    container.classList.add("bars");
    container.innerHTML = data
      .map(({ label, value }) => {
        const width = Math.max(1, (Math.abs(value) / max) * 100);
        const color = value < 0 ? "var(--red)" : "var(--blue)";
        return `<div class="bar-row">
          <span class="bar-label">${label}</span>
          <span class="bar-track"><i style="width:${width}%;background:${color}"></i></span>
          <span class="bar-value">${value > 0 ? "+" : ""}${value}</span>
        </div>`;
      })
      .join("");
  }

  function renderLine(container, points, options) {
    const width = options.width || 460;
    const height = options.height || 150;
    const pad = { top: 12, right: 12, bottom: 24, left: 34 };
    const xMax = options.xMax || Math.max(...points.map((p) => p.x));
    const yMax = options.yMax || Math.max(...points.map((p) => p.y));
    const yMin = options.yMin || 0;
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const sx = (x) => pad.left + (x / xMax) * plotW;
    const sy = (y) => pad.top + (1 - (y - yMin) / (yMax - yMin)) * plotH;

    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, class: "line-chart", role: "img" });
    svg.appendChild(svgEl("line", { x1: pad.left, y1: pad.top, x2: pad.left, y2: pad.top + plotH, stroke: "#bbb" }));
    svg.appendChild(svgEl("line", { x1: pad.left, y1: pad.top + plotH, x2: pad.left + plotW, y2: pad.top + plotH, stroke: "#bbb" }));
    svg.appendChild(svgEl("text", { x: 4, y: sy(yMax) + 4, class: "axis" })).textContent = String(yMax);
    svg.appendChild(svgEl("text", { x: 4, y: sy(yMin) + 4, class: "axis" })).textContent = String(yMin);
    const path = points.map((p, i) => `${i ? "L" : "M"}${sx(p.x)},${sy(p.y)}`).join(" ");
    svg.appendChild(svgEl("path", { d: path, fill: "none", stroke: "#b03a2e", "stroke-width": 2 }));
    for (const p of points) {
      svg.appendChild(svgEl("circle", { cx: sx(p.x), cy: sy(p.y), r: 2.5, fill: "#b03a2e" }));
    }
    container.replaceChildren(svg);
  }

  function mount() {
    document.querySelectorAll("[data-chart]").forEach((node) => {
      let data;
      try {
        data = JSON.parse(node.dataset.values || "[]");
      } catch {
        return;
      }
      if (node.dataset.chart === "bars") {
        renderBars(node, data, JSON.parse(node.dataset.opts || "{}"));
      } else if (node.dataset.chart === "line") {
        renderLine(node, data, JSON.parse(node.dataset.opts || "{}"));
      }
    });
  }

  document.addEventListener("DOMContentLoaded", mount);
})();
