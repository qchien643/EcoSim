import assert from "node:assert/strict";
import { articleExcerpt, chartSegments, moveScheduled, appendEvents, draftPayload, initialSetup, latestMetric, liveMetrics, sameScenario, saveCatalogProduct, sessionHistoryFromReport, tagSourceStages, toggleDefaultTag, toggleScheduled, toggleTag, updateSessionHistory } from "./src/model.js";
import { request, all } from "./src/api.js";
import { matchesTag } from "./src/copy.js";
import { readFileSync } from "node:fs";

// Use the shipped template and registry, not invented input tags.
const template = JSON.parse(readFileSync(new URL("../data/scenario_templates/cafe/cafe-demo-v1.json", import.meta.url)));
// Result totals read the last committed point, never sum state or average rates.
const resultPoints = { metrics: [
  { scope_type: "run", scope_id: "r", metric_name: "buys", session_no: 2, session_value: 0, cumulative_value: 4 },
  { scope_type: "run", scope_id: "r", metric_name: "buys", session_no: 1, session_value: 4, cumulative_value: 4 },
  { scope_type: "product", scope_id: "r", metric_name: "buys", session_no: 3, cumulative_value: 99 },
  { scope_type: "run", scope_id: "other", metric_name: "buys", session_no: 4, cumulative_value: 99 },
  { scope_type: "run", scope_id: "r", metric_name: "current_likes", session_no: 1, cumulative_value: 8 },
  { scope_type: "run", scope_id: "r", metric_name: "current_likes", session_no: 2, cumulative_value: 5 },
  { scope_type: "run", scope_id: "r", metric_name: "purchase_rate", session_no: 1, cumulative_value: 0.5 },
  { scope_type: "run", scope_id: "r", metric_name: "purchase_rate", session_no: 2, cumulative_value: null },
] };
const pointsBefore = structuredClone(resultPoints);
assert.equal(latestMetric(resultPoints, "r", "buys"), 4);
assert.equal(latestMetric(resultPoints, "r", "buys", "session_value"), 0);
assert.equal(latestMetric(resultPoints, "r", "buys", "cumulative_value", "product"), 99);
assert.equal(latestMetric(resultPoints, "r", "current_likes"), 5);
assert.equal(latestMetric(resultPoints, "r", "purchase_rate"), null);
assert.equal(latestMetric(resultPoints, "r", "missing"), null);
assert.equal(latestMetric({ metrics: [] }, "r", "buys"), null);
assert.deepEqual(resultPoints, pointsBefore);
const progress = (status, session_no, latest_completed_session_no, values) => ({
  status, session_no, latest_completed_session_no,
  completed_agents: session_no === latest_completed_session_no ? 2 : 1,
  counters: [{ scope_type: "run", scope_id: "run_fixture", values }],
});
const history1 = updateSessionHistory([], progress("running", 1, 0, { posts_read: 2, buys: 0 }), "run_fixture");
assert.equal(history1.length, 1);
assert.equal(history1[0].provisional, true);
const history2 = updateSessionHistory(history1, progress("running", 2, 1, { posts_read: 7, buys: 1 }), "run_fixture");
assert.deepEqual(history2.map(point => point.session_no), [1, 2]);
assert.equal(history2[0].values.posts_read, 2);
assert.equal(history2[1].values.buys, 1);
const history3 = updateSessionHistory(history2, progress("running", 3, 2, { posts_read: 8, buys: 2 }), "run_fixture", true);
assert.equal(history3.find(point => point.session_no === 2).values.posts_read, 8);
assert.equal(history3.at(-1).provisional, true);
const history4 = updateSessionHistory(history3, progress("completed", 2, 2, { posts_read: 8, buys: 2 }), "run_fixture", true);
assert.equal(history4.find(point => point.session_no === 2).provisional, false);
assert.equal(updateSessionHistory(history2, progress("ready", 1, 0, { posts_read: 0 }), "run_fixture").length, 2);
const reportHistory = sessionHistoryFromReport({
  sessions: [{ session_no: 1 }, { session_no: 2 }],
  metrics: [
    { scope_type: "run", scope_id: "run_fixture", session_no: 1, metric_name: "posts_read", cumulative_value: 3 },
    { scope_type: "run", scope_id: "run_fixture", session_no: 2, metric_name: "posts_read", cumulative_value: 8 },
    { scope_type: "run", scope_id: "run_fixture", session_no: 2, metric_name: "buys", cumulative_value: 2 },
  ],
}, "run_fixture");
assert.deepEqual(reportHistory.map(point => point.session_no), [1, 2]);
assert.equal(reportHistory[0].values.posts_read, 3);
assert.equal(reportHistory[1].values.buys, 2);
assert.equal(liveMetrics.length, 6);
const defaults = JSON.parse(readFileSync(new URL("./src/config/tag-defaults.yaml", import.meta.url)));
const simulationDefaults = JSON.parse(readFileSync(new URL("./src/config/simulation-defaults.yaml", import.meta.url)));
assert.deepEqual(simulationDefaults, {
  execution: { mode: "parallel", batch_size: 4 },
  show_advanced_controls: false,
});
const tagRegistry = JSON.parse(readFileSync(new URL("../data/tags/agent_flow_tags.v2.json", import.meta.url)));
const configured = structuredClone(template.setup);
const cases = [
  ["business", configured.business, `brand:${configured.business.brand_id}:brand_description`],
  ["shop", configured.shops[0], `shop:${configured.shops[0].shop_id}:public_profile`],
  ["article", configured.posts[0], `post:${configured.posts[0].post_id}:preview`],
  ["product", configured.products[0], `product:${configured.products[0].product_id}:product_description`],
];
for (const [kind, object, source] of cases) {
  const before = structuredClone(object.tags);
  const family = ["business", "shop"].includes(kind) ? "enterprise" : kind;
  const tag = tagRegistry.tags.find(t => t.family === family && !before.some(v => v.tag_id === t.id));
  const next = toggleDefaultTag(object.tags, tag.id, defaults[kind], [source], tagRegistry);
  assert.deepEqual(next.slice(0, -1), before);
  assert.deepEqual(object.tags, before);
  assert.deepEqual(next.at(-1), {
    tag_id: tag.id, source_ref: source, visible_stages: defaults[kind].visible_stages,
  });
  assert.notEqual(next.at(-1).visible_stages, defaults[kind].visible_stages);
  assert.deepEqual(toggleDefaultTag(next, tag.id, undefined, [], tagRegistry), before);
  for (const preset of [undefined, { ...defaults[kind], source_field: "missing" },
    { ...defaults[kind], visible_stages: [] },
    { ...defaults[kind], visible_stages: ["invalid"] },
    { ...defaults[kind], visible_stages: [defaults[kind].visible_stages[0], defaults[kind].visible_stages[0]] }]) {
    assert.throws(() => toggleDefaultTag(before, tag.id, preset, [source], tagRegistry), /Cấu hình mặc định/);
  }
  assert.throws(() => toggleDefaultTag(before, "unknown", defaults[kind], [source], tagRegistry), /Cấu hình mặc định/);
  assert.throws(() => toggleDefaultTag(before, tag.id, defaults[kind], [], tagRegistry), /Cấu hình mặc định/);
  object.tags = next;
}
assert.deepEqual(draftPayload(configured), configured);
assert.deepEqual(draftPayload(template.setup), template.setup);
for (const [family, field, forbidden] of [["article", "article_content", "A1"], ["product", "product_description", "B1"]]) {
  const tag = tagRegistry.tags.find(t => t.family === family);
  assert.throws(() => toggleDefaultTag([], tag.id, { source_field: field, visible_stages: [forbidden] },
    [`${family}:fixture:${field}`], tagRegistry), /Cấu hình mặc định/);
}
const originalTag = template.setup.products[0].tags[0];
const productsBefore = structuredClone(template.setup.products);
const productEdit = { ...productsBefore[0], product_name: "Tên vừa sửa" };
const updatedProducts = saveCatalogProduct(productsBefore, productEdit);
assert.equal(updatedProducts[0].product_name, productEdit.product_name);
assert.equal(updatedProducts[0].position, productsBefore[0].position);
assert.deepEqual(updatedProducts[0].tags, productsBefore[0].tags);
const targetShop = { ...productsBefore[1], product_id: "target_fixture", shop_id: "shop_fixture", position: 8 };
const transferred = saveCatalogProduct([...productsBefore, targetShop], { ...productEdit, shop_id: targetShop.shop_id });
assert.equal(transferred[0].position, 9);
assert.deepEqual(transferred.at(-1), targetShop);
const added = saveCatalogProduct(productsBefore, { ...productEdit, product_id: "new_fixture" });
assert.equal(added.at(-1).position, Math.max(...productsBefore.map(p => p.position)) + 1);
assert.deepEqual(productsBefore, template.setup.products);
const reordered = moveScheduled(productsBefore, 0, 1);
assert.equal(reordered[0].product_id, productsBefore[1].product_id);
assert.equal(new Set(reordered.map(p => p.position)).size, productsBefore.length);
// Every confirmation is asynchronous UI, never the browser's blocking dialog.
for (const file of ["App.jsx", "Scenario.jsx", "Run.jsx", "ui.jsx"]) {
  const source = readFileSync(new URL(`./src/${file}`, import.meta.url), "utf8");
  assert.ok(!/(?:window\.)?(?:confirm|alert)\(/.test(source.replace(/await confirm\(/g, "await customConfirmation(")), file);
}
const selected = toggleTag([], originalTag.tag_id, originalTag.source_ref, originalTag.visible_stages);
assert.deepEqual(selected, [originalTag]);
assert.notEqual(selected[0].visible_stages, originalTag.visible_stages);
assert.deepEqual(toggleTag(selected, originalTag.tag_id, "", []), []);
assert.deepEqual(selected, [originalTag]); // Removing a choice does not mutate the input.
assert.ok(matchesTag({ id: "enterprise.craft_focus" }, "nguyen lieu"));
const registry = { families: { article: { stages: ["A1", "A2", "A3"] }, product: { stages: ["B1", "B2", "B3"] } } };
assert.deepEqual(tagSourceStages(registry, "article", "post:p:article_content"), ["A3"]);
assert.deepEqual(tagSourceStages(registry, "article", "post:p:preview"), ["A1", "A2", "A3"]);
assert.deepEqual(tagSourceStages(registry, "product", "product:p:product_description"), ["B2", "B3"]);
assert.deepEqual(tagSourceStages(registry, "product", ""), []);
const posts = [{ post_id: "a", position: 2 }, { post_id: "b", position: 5 }];
assert.ok(sameScenario("#/scenarios/a/content", "/scenarios/a/shop"));
assert.ok(!sameScenario("#/scenarios/a/content", "/scenarios/b/shop"));
assert.deepEqual(moveScheduled(posts, 1, -1), [{ post_id: "b", position: 1 }, { post_id: "a", position: 2 }]);
assert.equal(posts[0].position, 2);
assert.equal(articleExcerpt(" \n Cà phê  ngon\t"), "Cà phê ngon");
assert.equal(articleExcerpt(""), "");
assert.equal(articleExcerpt(Array(100).fill("cà").join(" ")).split(" ").length, 100);
assert.equal(articleExcerpt(Array(101).fill("cà").join(" ")), Array(100).fill("cà").join(" ") + "…");
const scheduled = toggleScheduled(posts, "c");
assert.deepEqual(scheduled, [...posts, { post_id: "c", position: 6 }]);
assert.deepEqual(toggleScheduled(scheduled, "c"), posts);
assert.deepEqual(toggleScheduled([{ post_id: "a", position: 1 }], "a"), []);
assert.deepEqual(posts, [{ post_id: "a", position: 2 }, { post_id: "b", position: 5 }]);
const localDraft = structuredClone(template.setup);
localDraft.posts[0].title = "Unconfirmed edit";
localDraft.sessions[0].posts = [];
assert.notEqual(localDraft.posts[0].title, template.setup.posts[0].title);
assert.ok(template.setup.sessions[0].posts.length > 0);
const chart = chartSegments([
  { session_no: 3, session_value: 2 }, { session_no: 1, session_value: 0 },
  { session_no: 2, session_value: null },
], "session_value");
assert.equal(chart.segments.length, 2);
assert.equal(chart.segments[0][0].point.session_value, 0);
assert.equal(chart.segments[0][0].y, 240);
assert.equal(chartSegments([{ session_no: 1, session_value: 0 }], "session_value").segments[0][0].x, 340);
const seen = new Set();
const first = appendEvents([], [{ event_id: "a" }, { event_id: "b" }], seen);
assert.deepEqual(appendEvents(first, [{ event_id: "b" }, { event_id: "c" }], seen).map(e => e.event_id), ["a", "b", "c"]);
const draft = initialSetup({ name: "Draft" });
assert.equal(draftPayload(draft).business, undefined);
assert.ok(draft.business);
let calls = [];
globalThis.fetch = async (url, options) => {
  calls.push({ url, options });
  return new Response(JSON.stringify(url.includes("after=") ? { items: [2], next_cursor: null } : { items: [1], next_cursor: "abc" }));
};
assert.deepEqual(await all("/campaigns"), [1, 2]);
await request("/runs/r/start", { method: "POST", key: "same-retry-key" });
assert.equal(calls.at(-1).options.headers["Idempotency-Key"], "same-retry-key");
globalThis.fetch = async () => new Response(JSON.stringify({ error: { message: "Revision conflict", fields: [{ path: "revision" }] } }), { status: 409 });
await assert.rejects(request("/scenarios/s"), e => e.status === 409 && e.fields[0].path === "revision");
console.log("PASS: YAML tag defaults, preserved assignments, invalid-default rejection, 100-word excerpts, isolated drafts, schedule selection/order, tag toggle/source boundaries, Vietnamese search, chart zero/null/single point, FIFO dedup, pagination, command key, API errors");
