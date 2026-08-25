(function exposeScoring(root, factory) {
  const scoring = factory();
  root.XalgoScoring = scoring;
  if (typeof module === "object" && module.exports) module.exports = scoring;
})(typeof globalThis !== "undefined" ? globalThis : this, function createScoring() {
  "use strict";

  const countForWeight = {
    favorite: "likes",
    reply: "replies",
    retweet: "retweets",
    quote: "quotes",
  };
  const positiveNormalizationActions = [
    "favorite", "reply", "retweet", "photo_expand", "video_open", "click",
    "open_link", "profile_click", "vqv", "share", "share_via_dm",
    "share_via_copy_link", "dwell", "quote", "quoted_click", "quoted_vqv",
    "follow_author", "post_unexplored",
  ];
  const negativeNormalizationActions = [
    "not_interested", "block_author", "mute_author", "report", "not_dwelled",
  ];

  function scorePost(post, preset, weights, extraProbabilities = {}, settings = {}) {
    const warnings = [...(post.warnings || [])];
    const breakdown = {};
    const pHat = {};
    let mode;

    Object.entries(weights).forEach(([action, weight]) => {
      if (!Number.isFinite(weight)) {
        throw new Error(`${action} の重みを数値で入力してください。`);
      }
    });
    Object.entries(extraProbabilities).forEach(([action, probability]) => {
      if (!Number.isFinite(probability) || probability < 0 || probability > 1) {
        throw new Error(`${action} の確率は0〜1で入力してください。`);
      }
    });

    if (post.views && post.views > 0) {
      mode = "rate";
      Object.entries(weights).forEach(([action, weight]) => {
        let probability;
        if (Object.hasOwn(extraProbabilities, action)) {
          probability = extraProbabilities[action];
        } else {
          const countKey = countForWeight[action];
          const count = countKey ? post[countKey] : null;
          if (count !== null && count !== undefined) {
            probability = Math.min(count / post.views, 1);
          }
        }
        if (probability !== undefined) {
          pHat[action] = probability;
          breakdown[action] = weight * probability;
        }
      });
      const missing = Object.keys(weights).filter(
        (action) => !(action in pHat) && weights[action] !== 0,
      );
      if (missing.length) {
        warnings.push(`公開シグナルがないため0扱い: ${missing.join(", ")}`);
      }
    } else {
      mode = "raw";
      warnings.push("表示回数がないため、行動数をlog1pで縮めたrawモードです");
      Object.entries(weights).forEach(([action, weight]) => {
        const countKey = countForWeight[action];
        const count = countKey ? post[countKey] : null;
        if (count !== null && count !== undefined) {
          breakdown[action] = weight * Math.log1p(count);
        }
      });
    }

    let score = Object.values(breakdown).reduce((sum, value) => sum + value, 0);
    if (mode === "rate") {
      const offset = Number(settings.negative_scores_offset || 0);
      const positiveSum = positiveNormalizationActions.reduce(
        (sum, action) => sum + Number(weights[action] || 0), 0,
      );
      const negativeSum = -negativeNormalizationActions.reduce(
        (sum, action) => sum + Number(weights[action] || 0), 0,
      );
      const totalSum = positiveSum + negativeSum;
      if (totalSum === 0) {
        score = Math.max(score, 0);
      } else if (score < 0) {
        score = ((score + negativeSum) / totalSum) * offset;
      } else {
        score += offset;
      }
    }
    if (preset === "upstream_2026_08") {
      warnings.push(
        "公開されたHome Mixer既定値です。実リクエストでは実験設定により上書きされ得ます。",
      );
    }

    return {
      preset,
      mode,
      breakdown,
      p_hat: pHat,
      warnings,
      score,
    };
  }

  function extractStatusId(url) {
    const input = url.trim();
    if (/^\d+$/.test(input)) return input;
    const match = input.match(
      /(?:twitter\.com|x\.com|fxtwitter\.com|vxtwitter\.com|fixupx\.com)\/[^/]+\/status(?:es)?\/(\d+)/,
    );
    if (!match) throw new Error("Xの投稿URLまたは投稿IDを入力してください。");
    return match[1];
  }

  return { scorePost, extractStatusId };
});
