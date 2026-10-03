/* xalgo — 共通のトップバー・サイドバー・検索 */
(() => {
  "use strict";

  const NAV = [
    { group: "入門", pages: [
      { href: "index.html", title: "はじめに" },
      { href: "background.html", title: "背景（分析対象）" },
      { href: "method.html", title: "調査方法" },
    ] },
    { group: "仕組み", pages: [
      { href: "pipeline.html", title: "パイプライン" },
      { href: "scoring.html", title: "スコア計算" },
      { href: "ranking.html", title: "順位との関係" },
      { href: "weights.html", title: "重み一覧" },
      { href: "settings.html", title: "設定・ゲート" },
    ] },
    { group: "実践", pages: [
      { href: "examples.html", title: "スコアが高い例" },
      { href: "posting.html", title: "投稿の作り方" },
      { href: "calculator.html", title: "計算機" },
    ] },
    { group: "調査", pages: [
      { href: "history.html", title: "重みの変遷" },
      { href: "observation.html", title: "観測・調査" },
      { href: "competitors.html", title: "競合・関連" },
    ] },
    { group: "参考", pages: [
      { href: "limits.html", title: "限界と注意" },
      { href: "glossary.html", title: "用語" },
      { href: "sources.html", title: "根拠コード" },
    ] },
  ];

  const current = (location.pathname.split("/").pop() || "index.html").split("#")[0];

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function topbarMarkup() {
    return (
      `<div class="topbar-inner">` +
      `<a class="brand" href="./index.html">xalgo<small>Xアルゴリズム観測</small></a>` +
      `<div class="search"><input id="search" type="search" placeholder="検索（例: offset / 0.625 / 返信）" autocomplete="off">` +
      `<div id="search-results" hidden></div></div>` +
      `</div>`
    );
  }

  function sidebarMarkup() {
    const nav = NAV.map(({ group, pages }) => {
      const links = pages
        .map(
          (page) =>
            `<a href="./${page.href}"${page.href === current ? ' class="active"' : ""}>${page.title}</a>`,
        )
        .join("");
      return `<div class="nav-group"><span>${group}</span>${links}</div>`;
    }).join("");
    return (
      `<nav>${nav}</nav>` +
      `<div class="side-foot">公開既定値<br>upstream_2026_10<br>commit 76843a5eea</div>`
    );
  }

  let index = null;

  async function loadIndex() {
    if (index) return index;
    try {
      const response = await fetch("./search-index.json");
      index = response.ok ? await response.json() : [];
    } catch {
      index = [];
    }
    return index;
  }

  function snippet(text, query) {
    const at = text.toLowerCase().indexOf(query);
    const start = at < 0 ? 0 : Math.max(0, at - 24);
    return (start > 0 ? "…" : "") + text.slice(start, start + 90);
  }

  async function runSearch(rawQuery) {
    const box = document.getElementById("search-results");
    const query = rawQuery.trim().toLowerCase();
    if (!query) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    const data = await loadIndex();
    const hits = [];
    for (const page of data) {
      for (const section of page.sections) {
        const hay = `${section.title} ${section.text}`.toLowerCase();
        if (hay.includes(query)) hits.push({ page, section, hay });
      }
    }
    box.hidden = false;
    if (!hits.length) {
      box.innerHTML = '<p class="no-hit">見つかりません</p>';
      return;
    }
    box.innerHTML = hits
      .slice(0, 12)
      .map(({ page, section, hay }) => {
        const label = section.title ? `${page.title} › ${section.title}` : page.title;
        return `<a href="./${page.url}"><b>${escapeHtml(label)}</b><span>${escapeHtml(snippet(hay, query))}…</span></a>`;
      })
      .join("");
  }

  function mount() {
    const topbar = document.createElement("div");
    topbar.className = "topbar";
    topbar.innerHTML = topbarMarkup();
    const layout = document.querySelector(".layout");
    if (layout) document.body.insertBefore(topbar, layout);

    const slot = document.getElementById("sidebar");
    if (slot) slot.innerHTML = sidebarMarkup();
    const input = document.getElementById("search");
    if (input) input.addEventListener("input", (event) => runSearch(event.target.value));
  }

  document.addEventListener("DOMContentLoaded", mount);
})();
