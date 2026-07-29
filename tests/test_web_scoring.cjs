const assert = require("node:assert/strict");
const test = require("node:test");

const { extractStatusId, scorePost } = require("../web/scoring.js");

test("browser rate mode matches the Python scoring example", () => {
  const result = scorePost(
    { views: 1000, likes: 100, replies: 20, retweets: 10 },
    "test",
    { favorite: 1, reply: 0.5, retweet: 0.3, dwell: 0.2 },
    { dwell: 0.3 },
  );
  assert.equal(result.mode, "rate");
  assert.ok(Math.abs(result.score - 0.173) < 1e-12);
});

test("browser raw mode uses log1p", () => {
  const result = scorePost(
    { views: null, likes: 9, replies: 3 },
    "test",
    { favorite: 2, reply: 1 },
  );
  assert.equal(result.mode, "raw");
  assert.ok(Math.abs(result.score - (2 * Math.log1p(9) + Math.log1p(3))) < 1e-12);
});

test("browser probabilities are validated", () => {
  assert.throws(
    () => scorePost({ views: 10, likes: 1 }, "test", { favorite: 1, dwell: 0.2 }, { dwell: 1.1 }),
    /0〜1/,
  );
});

test("browser accepts X URLs and bare status IDs", () => {
  const id = "2079205509727478218";
  assert.equal(extractStatusId(id), id);
  assert.equal(extractStatusId(`https://x.com/example/status/${id}?s=20`), id);
});
