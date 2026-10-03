/* xalgo — 投稿スコアの計算機 */
(() => {
  "use strict";

  const { scorePost } = window.XalgoScoring;

  const SAMPLES = {
    conversation: { views: 100000, likes: 1500, replies: 1600, retweets: 300, quotes: 400 },
    assertion: { views: 100000, likes: 3000, replies: 200, retweets: 1500, quotes: 1200 },
    viral: { views: 100000, likes: 3000, replies: 60, retweets: 4000, quotes: 200 },
    empathy: { views: 100000, likes: 8000, replies: 40, retweets: 50, quotes: 5 },
  };
  const DEFAULT_SAMPLE = "conversation";
  const CALC_DELAY_MS = 180;

  const ACTION_NAMES = {
    favorite: "いいね", reply: "返信", retweet: "リポスト", quote: "引用", dwell: "滞在",
    report: "報告", negative_feedback: "興味なし", vqv: "動画視聴", follow_author: "フォロー",
    photo_expand: "画像展開", video_open: "動画を開く", click: "クリック",
    open_link: "リンクを開く", profile_click: "プロフィール表示",
    share: "共有", share_via_dm: "DM共有", share_via_copy_link: "リンクコピー",
    quoted_click: "引用クリック", quoted_vqv: "引用動画視聴",
    cont_dwell_time: "滞在時間", cont_click_dwell_time: "クリック後滞在",
    cont_active_secs_5m_residual_norm: "5分内アクティブ時間",
    post_unexplored: "新規性", not_interested: "興味なし", block_author: "ブロック",
    mute_author: "ミュート", not_dwelled: "即離脱",
  };
  const PRESET_NOTES = {
    upstream_2026_10: "2026-09-29〜の公開既定値",
    upstream_2026_09: "2026-09-18版",
    upstream_2026_08: "2026-08-24版",
    repo_demo: "2026年5月demo（履歴）",
    legacy_2023: "2023年Heavy Ranker",
    full_template: "感度分析用",
  };
  const BAR_COLORS = ["#2f5d8a", "#b03a2e", "#4f7a52", "#7a5c9e", "#a1743a"];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  let config = null;
  let lastFormula = "";
  let timer = null;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  async function fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function setSample(name) {
    const values = SAMPLES[name];
    if (!values) return;
    Object.entries(values).forEach(([key, value]) => {
      const input = $(`[name="${key}"]`);
      if (input) input.value = value;
    });
    scheduleCalculate();
  }

  function buildPresetOptions() {
    const select = $("#preset-select");
    select.innerHTML = Object.keys(config.presets)
      .map((key) => `<option value="${key}">${key}</option>`)
      .join("");
    select.value = config.default_preset;
    buildWeightFields();
  }

  function buildWeightFields() {
    const preset = $("#preset-select").value;
    $("#weight-fields").innerHTML = Object.entries(config.presets[preset])
      .map(([action, value]) => `
        <label title="${action}">${ACTION_NAMES[action] || action}
          <input type="number" step="0.01" data-weight="${action}" value="${value}">
        </label>`).join("");
    $("#preset-note").textContent = PRESET_NOTES[preset] || "";
  }

  function readForm() {
    const preset = $("#preset-select").value;
    const weights = {};
    $$("[data-weight]").forEach((input) => {
      weights[input.dataset.weight] = Number(input.value);
    });
    const post = {};
    $$("[name]", $("#manual-inputs")).forEach((input) => {
      post[input.name] = Number(input.value);
    });
    const probabilities = {};
    if (Object.hasOwn(config.presets[preset], "dwell")) {
      probabilities.dwell = Number($("#dwell-p").value);
    }
    return { preset, weights, post, probabilities };
  }

  function buildFormula(data) {
    const parts = Object.entries(data.result.breakdown).map(([action, contribution]) => {
      const probability = data.result.p_hat[action];
      return probability === undefined
        ? `${action}: ${contribution.toFixed(5)}`
        : `${probability.toFixed(5)} × ${Number(data.weights[action]).toFixed(2)}`;
    });
    const subtotal = Object.values(data.result.breakdown).reduce((sum, value) => sum + value, 0);
    const adjustment = Math.abs(subtotal - data.result.score) > 1e-12
      ? ` + offset ${(data.result.score - subtotal).toFixed(5)}`
      : "";
    return `${parts.join(" + ")}${adjustment} = ${data.result.score.toFixed(5)}`;
  }

  function renderBreakdown(result) {
    const rows = Object.entries(result.breakdown).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
    if (!rows.length) {
      $("#breakdown-list").innerHTML = '<p class="empty-breakdown">計算できる公開シグナルがありません。</p>';
      return;
    }
    const max = Math.max(...rows.map(([, value]) => Math.abs(value)), 0.000001);
    $("#breakdown-list").innerHTML = rows.map(([action, contribution], index) => {
      const probability = result.p_hat[action];
      const detail = probability === undefined ? "log1p(count)" : `p = ${probability.toFixed(5)}`;
      const width = Math.max(2, Math.abs(contribution) / max * 100);
      const color = contribution < 0 ? "#b03a2e" : BAR_COLORS[index % BAR_COLORS.length];
      return `<div class="breakdown-row">
        <label>${ACTION_NAMES[action] || action}<small>${detail}</small></label>
        <div class="breakdown-bar"><i style="--width:${width}%;--bar:${color}"></i></div>
        <strong>${contribution >= 0 ? "+" : ""}${contribution.toFixed(5)}</strong>
      </div>`;
    }).join("");
  }

  function renderResult(data) {
    const result = data.result;
    $("#score-value").textContent = result.score.toFixed(5);
    $("#mode-pill").textContent = `${result.mode.toUpperCase()} MODE`;
    lastFormula = buildFormula(data);
    $("#formula-output").textContent = lastFormula;
    renderBreakdown(result);

    const warnings = result.warnings || [];
    const note = $("#result-note");
    note.hidden = warnings.length === 0;
    note.innerHTML = warnings.length ? `<p>${warnings.map(escapeHtml).join(" / ")}</p>` : "";
  }

  async function calculate(event) {
    if (event) event.preventDefault();
    if (!config) return;
    const panel = $(".result-panel");
    const button = $(".calculate-button");
    const error = $("#form-error");
    panel.setAttribute("aria-busy", "true");
    button.disabled = true;
    $("#calculate-label").textContent = "計算中…";
    error.hidden = true;
    try {
      const input = readForm();
      const settings = config.preset_settings?.[input.preset] || {};
      const result = scorePost(
        input.post, input.preset, input.weights, input.probabilities, settings,
      );
      renderResult({ result, weights: input.weights });
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      panel.setAttribute("aria-busy", "false");
      button.disabled = false;
      $("#calculate-label").textContent = "計算する";
    }
  }

  function scheduleCalculate() {
    clearTimeout(timer);
    timer = setTimeout(() => calculate(), CALC_DELAY_MS);
  }

  function renderEmbed(data) {
    const preview = $("#embed-preview");
    if (!preview) return;
    const frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.setAttribute("title", "投稿プレビュー");
    frame.setAttribute(
      "srcdoc",
      `<!doctype html><html><head><meta charset="utf-8">` +
        `<style>body{font:13px/1.6 sans-serif;margin:0;color:#23252b}` +
        `blockquote{margin:0;padding-left:8px;border-left:2px solid #ddd}</style>` +
        `</head><body>${data.html || ""}</body></html>`,
    );
    preview.hidden = false;
    preview.replaceChildren(frame);
  }

  async function showEmbed() {
    const url = $("#post-url").value.trim();
    if (!url) return;
    const button = $("#fetch-embed");
    const error = $("#form-error");
    error.hidden = true;
    button.disabled = true;
    try {
      const endpoint = `https://publish.twitter.com/oembed?omit_script=1&dnt=1&url=${encodeURIComponent(url)}`;
      renderEmbed(await fetchJson(endpoint));
    } catch (err) {
      error.textContent = `投稿を表示できませんでした: ${err.message}`;
      error.hidden = false;
    } finally {
      button.disabled = false;
    }
  }

  function updateDiversity() {
    if (!config) return;
    const slider = $("#position-slider");
    if (!slider) return;
    const item = Number(slider.value);
    const position = item - 1;
    const preset = $("#preset-select").value || config.default_preset;
    const diversity = config.preset_settings?.[preset]?.author_diversity
      || config.author_diversity;
    const decay = Number(diversity.decay);
    const floor = Number(diversity.floor);
    const multiplier = (1 - floor) * (decay ** position) + floor;
    const output = $("#position-output");
    if (output) output.textContent = `${item}件目`;
    const formula = $("#diversity-formula");
    if (formula) {
      formula.innerHTML = `(1 − ${floor}) × ${decay}<sup>${position}</sup> + ${floor} = <b>${multiplier.toFixed(3)}</b>`;
    }
  }

  function bindEvents() {
    $$(".source-tabs button").forEach((button) => button.addEventListener("click", () => {
      $$(".source-tabs button").forEach((tab) => {
        tab.classList.toggle("active", tab === button);
        tab.setAttribute("aria-selected", String(tab === button));
      });
      $("#url-inputs").hidden = button.dataset.source !== "url";
    }));
    $("#sample-select").addEventListener("change", (event) => setSample(event.target.value));
    $("#preset-select").addEventListener("change", () => {
      buildWeightFields();
      updateDiversity();
      scheduleCalculate();
    });
    $("#score-form").addEventListener("submit", calculate);
    $("#manual-inputs").addEventListener("input", scheduleCalculate);
    $("#advanced-panel").addEventListener("input", scheduleCalculate);
    $("#dwell-p").addEventListener("input", (event) => {
      $("#dwell-output").textContent = `${Math.round(event.target.value * 100)}%`;
    });
    $("#advanced-button").addEventListener("click", (event) => {
      const panel = $("#advanced-panel");
      panel.hidden = !panel.hidden;
      event.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
      $("span", event.currentTarget).textContent = panel.hidden ? "＋" : "−";
    });
    $("#reset-button").addEventListener("click", () => {
      $("#sample-select").value = DEFAULT_SAMPLE;
      $("#preset-select").value = config.default_preset;
      $("#dwell-p").value = 0;
      $("#dwell-output").textContent = "0%";
      buildWeightFields();
      setSample(DEFAULT_SAMPLE);
    });
    $("#copy-formula").addEventListener("click", async (event) => {
      await navigator.clipboard.writeText(lastFormula);
      event.currentTarget.textContent = "コピー済み ✓";
      setTimeout(() => { event.currentTarget.textContent = "式をコピー"; }, 1500);
    });
    const fetchEmbed = $("#fetch-embed");
    if (fetchEmbed) fetchEmbed.addEventListener("click", showEmbed);
    const positionSlider = $("#position-slider");
    if (positionSlider) {
      positionSlider.addEventListener("input", updateDiversity);
      updateDiversity();
    }
  }

  async function init() {
    try {
      const response = await fetch("./weights.json", { cache: "no-cache" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      config = await response.json();
      buildPresetOptions();
      await calculate();
    } catch (error) {
      $("#form-error").textContent = `設定を読み込めませんでした: ${error.message}`;
      $("#form-error").hidden = false;
    }
    bindEvents();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
