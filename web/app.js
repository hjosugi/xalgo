const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const samples = {
  balanced: { views: 100000, likes: 3200, replies: 180, retweets: 940, quotes: 120 },
  conversation: { views: 52000, likes: 880, replies: 760, retweets: 150, quotes: 210 },
  viral: { views: 1500000, likes: 28000, replies: 620, retweets: 14600, quotes: 3200 },
  small: { views: 1800, likes: 72, replies: 8, retweets: 13, quotes: 2 },
};
const actionNames = {
  favorite: "いいね", reply: "返信", retweet: "リポスト", quote: "引用", dwell: "滞在",
  report: "報告", negative_feedback: "興味なし", vqv: "動画視聴", follow_author: "フォロー",
};
const barColors = ["#ff6747", "#9680ff", "#59cfdb", "#c7ff5e", "#f3bb54"];
const presetNotes = {
  repo_demo: "公開リポジトリに実在する唯一の2026年版デモ重みです。",
  legacy_2023: "2023年版で公開されていたHeavy Ranker重みとの比較用です。",
  full_template: "全アクションを含む感度分析用テンプレートです。",
};

let config = null;
let source = "manual";
let lastFormula = "";
let calculateTimer = null;

const { scorePost, extractStatusId } = window.XalgoScoring;

function setSample(name) {
  const values = samples[name];
  Object.entries(values).forEach(([key, value]) => {
    const input = $(`[name="${key}"]`);
    if (input) input.value = value;
  });
  scheduleCalculate();
}

function buildPresetOptions() {
  const select = $("#preset-select");
  const labels = {
    repo_demo: "repo_demo — 2026公開デモ",
    legacy_2023: "legacy_2023 — 2023比較",
    full_template: "full_template — 全22アクション",
  };
  select.innerHTML = Object.keys(config.presets)
    .map((key) => `<option value="${key}">${labels[key] || key}</option>`).join("");
  select.value = config.default_preset;
  buildWeightFields();
}

function buildWeightFields() {
  const preset = $("#preset-select").value;
  const fields = $("#weight-fields");
  fields.innerHTML = Object.entries(config.presets[preset]).map(([action, value]) => `
    <label title="${action}"><span>${actionNames[action] || action}</span>
      <input type="number" step="0.01" data-weight="${action}" value="${value}">
    </label>`).join("");
  $("#preset-note").textContent = presetNotes[preset] || "選択した重みセットで計算します。";
}

function readForm() {
  const preset = $("#preset-select").value;
  const weights = {};
  $$('[data-weight]').forEach((input) => { weights[input.dataset.weight] = Number(input.value); });
  const post = {};
  $$('[name]', $("#manual-inputs")).forEach((input) => { post[input.name] = Number(input.value); });
  const probabilities = {};
  if (Object.hasOwn(config.presets[preset], "dwell")) {
    probabilities.dwell = Number($("#dwell-p").value);
  }
  return { preset, weights, post, probabilities };
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function fetchPublicPost(url) {
  const statusId = extractStatusId(url);
  const errors = [];
  try {
    const data = await fetchJson(`https://api.fxtwitter.com/status/${statusId}`);
    const post = data.tweet;
    return {
      views: post.views, likes: post.likes, replies: post.replies, retweets: post.retweets,
      quotes: post.quotes, warnings: [], source_backend: "fxtwitter",
    };
  } catch (error) { errors.push(`FxTwitter: ${error.message}`); }
  try {
    const post = await fetchJson(`https://api.vxtwitter.com/Twitter/status/${statusId}`);
    return {
      views: post.views, likes: post.likes, replies: post.replies, retweets: post.retweets,
      quotes: post.quotes, warnings: [], source_backend: "vxtwitter",
    };
  } catch (error) { errors.push(`VxTwitter: ${error.message}`); }
  throw new Error(`公開データを取得できませんでした。${errors.join(" / ")}`);
}

function buildFormula(data) {
  const parts = Object.entries(data.result.breakdown).map(([action, contribution]) => {
    const p = data.result.p_hat[action];
    if (p !== undefined) return `${p.toFixed(5)} × ${Number(data.weights[action]).toFixed(2)}`;
    return `${action}: ${contribution.toFixed(5)}`;
  });
  return `${parts.join(" + ")} = ${data.result.score.toFixed(5)}`;
}

function renderResult(data) {
  const result = data.result;
  $("#score-value").textContent = result.score.toFixed(5);
  $("#mode-pill").textContent = `${result.mode.toUpperCase()} MODE`;
  lastFormula = buildFormula(data);
  $("#formula-output").textContent = lastFormula;

  const rows = Object.entries(result.breakdown).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  const max = Math.max(...rows.map(([, value]) => Math.abs(value)), 0.000001);
  $("#breakdown-list").innerHTML = rows.length ? rows.map(([action, contribution], index) => {
    const probability = result.p_hat[action];
    const detail = probability === undefined ? "log1p(count)" : `p = ${probability.toFixed(5)}`;
    return `<div class="breakdown-row">
      <label>${actionNames[action] || action}<small>${detail}</small></label>
      <div class="breakdown-bar"><i style="--width:${Math.max(2, Math.abs(contribution) / max * 100)}%;--bar:${contribution < 0 ? "#f04e67" : barColors[index % barColors.length]}"></i></div>
      <strong>${contribution >= 0 ? "+" : ""}${contribution.toFixed(5)}</strong>
    </div>`;
  }).join("") : '<p class="empty-breakdown">計算できる公開シグナルがありません。</p>';

  const warnings = result.warnings || [];
  $("#result-note").innerHTML = warnings.length
    ? `<span>!</span><p><b>計算上の注意</b> ${warnings.map(escapeHtml).join(" / ")}</p>`
    : '<span>!</span><p><b>これは実際の「おすすめ順位」ではありません。</b> 閲覧者ごとの予測を、公開カウントの割合で代用した学習用スコアです。</p>';
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

async function calculate(event) {
  if (event) event.preventDefault();
  if (!config || (source === "url" && !$("#post-url").value.trim())) return;
  const panel = $(".result-panel");
  const button = $(".calculate-button");
  const error = $("#form-error");
  panel.setAttribute("aria-busy", "true");
  button.disabled = true;
  $("#calculate-label").textContent = source === "url" ? "公開データを取得中…" : "計算中…";
  error.hidden = true;
  try {
    const input = readForm();
    const post = source === "url" ? await fetchPublicPost($("#post-url").value) : input.post;
    const result = scorePost(post, input.preset, input.weights, input.probabilities);
    renderResult({ result, weights: input.weights });
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    panel.setAttribute("aria-busy", "false");
    button.disabled = false;
    $("#calculate-label").textContent = "この数字で計算する";
  }
}

function scheduleCalculate() {
  if (source !== "manual") return;
  clearTimeout(calculateTimer);
  calculateTimer = setTimeout(() => calculate(), 180);
}

function updateDiversity() {
  if (!config) return;
  const item = Number($("#position-slider").value);
  const position = item - 1;
  const decay = Number(config.author_diversity.decay || 0.9);
  const floor = Number(config.author_diversity.floor || 0.2);
  const multiplier = (1 - floor) * (decay ** position) + floor;
  $("#position-output").textContent = `${item}件目`;
  $("#diversity-formula").innerHTML = `(1 − ${floor}) × ${decay}<sup>${position}</sup> + ${floor} = <b>${multiplier.toFixed(3)}</b>`;
  $("#feed-multiplier").textContent = `${item}件目 · score × ${multiplier.toFixed(3)}`;
  $("#feed-rank").textContent = item <= 2 ? "2" : "↓";
  const card = $$(".feed-card")[1];
  card.style.opacity = String(Math.max(.55, multiplier));
  card.style.transform = `rotate(1.5deg) translateX(${(1 - multiplier) * 35}px)`;
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

  $$(".source-tabs button").forEach((button) => button.addEventListener("click", () => {
    source = button.dataset.source;
    $$(".source-tabs button").forEach((tab) => { tab.classList.toggle("active", tab === button); tab.setAttribute("aria-selected", String(tab === button)); });
    $("#manual-inputs").hidden = source !== "manual";
    $("#url-inputs").hidden = source !== "url";
    $("#calculate-label").textContent = source === "url" ? "投稿を取得して計算する" : "この数字で計算する";
  }));
  $("#sample-select").addEventListener("change", (event) => setSample(event.target.value));
  $("#preset-select").addEventListener("change", () => { buildWeightFields(); scheduleCalculate(); });
  $("#score-form").addEventListener("submit", calculate);
  $("#manual-inputs").addEventListener("input", scheduleCalculate);
  $("#advanced-panel").addEventListener("input", scheduleCalculate);
  $("#dwell-p").addEventListener("input", (event) => { $("#dwell-output").textContent = `${Math.round(event.target.value * 100)}%`; });
  $("#advanced-button").addEventListener("click", (event) => {
    const panel = $("#advanced-panel");
    panel.hidden = !panel.hidden;
    event.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
    $("span", event.currentTarget).textContent = panel.hidden ? "＋" : "−";
  });
  $("#reset-button").addEventListener("click", () => {
    $("#sample-select").value = "balanced";
    $("#preset-select").value = config.default_preset;
    $("#dwell-p").value = 0;
    $("#dwell-output").textContent = "0%";
    buildWeightFields();
    setSample("balanced");
  });
  $("#copy-formula").addEventListener("click", async (event) => { await navigator.clipboard.writeText(lastFormula); event.currentTarget.textContent = "コピー済み ✓"; setTimeout(() => { event.currentTarget.textContent = "式をコピー"; }, 1500); });
  $("#position-slider").addEventListener("input", updateDiversity);
  updateDiversity();
}

document.addEventListener("DOMContentLoaded", init);
