export const statuses = { draft: "Bản nháp", ready: "Sẵn sàng", running: "Đang chạy",
  completed: "Hoàn tất", failed: "Gặp lỗi", pending: "Chưa bắt đầu", inactive: "Không tham gia",
  resolved: "Đã xử lý", empty_result: "Không có nhãn đạt điểm sàn", unresolved: "Chưa có kết quả hợp lệ" };
export const stages = { A1: "Chú ý bài viết", A1R: "Lý do bỏ qua bài viết", A2: "Cảm nhận ban đầu",
  A3: "Đọc bài viết", A4: "Phản ứng với bài", A5: "Cân nhắc ghé cửa hàng",
  B1: "Chú ý sản phẩm", B1R: "Lý do bỏ qua sản phẩm", B2: "Cân nhắc sản phẩm", B3: "Quyết định mua" };
export const actions = { attend: "Chú ý", attend_again: "Chú ý lại", skip: "Bỏ qua",
  like: "Thích", dislike: "Không thích", no_reaction: "Không phản ứng", keep_current: "Giữ phản ứng",
  remove_reaction: "Bỏ phản ứng", no_new_reaction: "Không thêm phản ứng", visit: "Ghé cửa hàng",
  not_visit: "Không ghé", visit_again: "Ghé lại", not_visit_again: "Không ghé lại",
  buy: "Mua", buy_again: "Mua lại", not_buy: "Không mua", not_buy_again: "Không mua lại" };
export const liveMetrics = [
  ["posts_read", "Lượt đọc bài viết"],
  ["current_likes", "Lượt thích"],
  ["current_dislikes", "Lượt không thích"],
  ["shop_visits", "Lượt ghé cửa hàng"],
  ["products_attended", "Lượt chú ý sản phẩm"],
  ["buys", "Lượt mua"],
];
export function updateSessionHistory(history, progress, scopeId, commit = false) {
  if (!progress || progress.status === "ready") return history;
  const completed = progress.latest_completed_session_no || 0;
  const counter = progress.counters?.find(item =>
    item.scope_type === "run" && item.scope_id === scopeId);
  const values = Object.fromEntries(liveMetrics.map(([name]) => [name, counter?.values?.[name] ?? 0]));
  const next = [...history];
  if (commit && Number.isInteger(completed) && completed > 0) {
    const official = { session_no: completed, values, provisional: false };
    const index = next.findIndex(item => item.session_no === completed);
    if (index < 0) next.push(official);
    else next[index] = official;
  }
  const current = progress.session_no;
  if (progress.status === "running" && Number.isInteger(current) &&
      current > completed && progress.completed_agents > 0) {
    const provisional = { session_no: current, values, provisional: true };
    const index = next.findIndex(item => item.session_no === current);
    if (index < 0) next.push(provisional);
    else next[index] = provisional;
  }
  return next.sort((a, b) => a.session_no - b.session_no);
}
export function sessionHistoryFromReport(report, scopeId) {
  const points = (report?.metrics || []).filter(point =>
    point.scope_type === "run" && point.scope_id === scopeId);
  const bySession = new Map();
  for (const point of points) {
    const values = bySession.get(point.session_no) ||
      Object.fromEntries(liveMetrics.map(([name]) => [name, 0]));
    if (liveMetrics.some(([name]) => name === point.metric_name)) {
      values[point.metric_name] = point.cumulative_value ?? 0;
    }
    bySession.set(point.session_no, values);
  }
  const completed = new Set((report?.sessions || []).map(session => session.session_no));
  return [...bySession.entries()]
    .filter(([sessionNo]) => completed.has(sessionNo))
    .map(([session_no, values]) => ({ session_no, values, provisional: false }))
    .sort((a, b) => a.session_no - b.session_no);
}
export const relationOptions = {
  awareness: { unknown: "Chưa biết", aware: "Đã biết" },
  familiarity: { none: "Chưa quen", low: "Ít quen", established: "Quen thuộc" },
  attitude: { not_formed: "Chưa hình thành thái độ", positive: "Có thiện cảm", neutral: "Trung lập", negative: "Không có thiện cảm" },
  purchase_history: { none: "Chưa từng mua", has_purchased: "Đã từng mua" },
};
export const newId = (prefix) => `${prefix}_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
export const format = (value, ratio = false) => value == null ? "—" :
  new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 2, ...(ratio ? { style: "percent" } : {}) }).format(value);

export function latestMetric(report, scopeId, metric, valueKey = "cumulative_value", scopeType = "run") {
  const points = report.metrics.filter(point =>
    point.scope_type === scopeType && point.scope_id === scopeId && point.metric_name === metric);
  const latest = points.reduce((last, point) => !last || point.session_no > last.session_no ? point : last, null);
  return latest?.[valueKey] ?? null;
}

export function sameScenario(from, to) {
  const a = from.replace(/^#/, "").split("/").filter(Boolean);
  const b = to.replace(/^#/, "").split("/").filter(Boolean);
  return a[0] === "scenarios" && b[0] === "scenarios" && a[1] === b[1];
}

export function initialSetup(setup) {
  return { business: { organization_id: newId("org"), brand_id: newId("brand"),
    organization_name: "", organization_description: "", brand_name: "", brand_description: "", tags: [] },
    shops: [], posts: [], products: [], sessions: [{ session_no: 1, posts: [] }],
    agent_count: 12, selection_seed: 1, assignment_seed: 1,
    relationship_groups: [{ group_id: "group_1", percentage: 100, state: {
      awareness: "unknown", familiarity: "none", attitude: "not_formed", purchase_history: "none" } }],
    ...setup };
}
export function draftPayload(setup) {
  const value = structuredClone(setup);
  const { business } = value;
  if (!business.organization_name && !business.organization_description && !business.brand_name && !business.brand_description && !business.tags.length) delete value.business;
  for (const key of ["industry_id", "profile_version", "cohort_id", "policy_version"]) if (!value[key]) delete value[key];
  return value;
}
export function moveScheduled(posts, index, direction) {
  const sorted = [...posts].sort((a, b) => a.position - b.position);
  const target = index + direction;
  if (target < 0 || target >= sorted.length) return sorted;
  [sorted[index], sorted[target]] = [sorted[target], sorted[index]];
  return sorted.map((post, i) => ({ ...post, position: i + 1 }));
}
export function saveCatalogProduct(products, draft) {
  const previous = products.find(p => p.product_id === draft.product_id);
  const saved = { ...draft };
  if (!previous || previous.shop_id !== draft.shop_id) {
    saved.position = Math.max(0, ...products.filter(p => p.shop_id === draft.shop_id).map(p => p.position)) + 1;
  }
  return previous ? products.map(p => p === previous ? saved : p) : [...products, saved];
}
export function articleExcerpt(content) {
  const words = (content || "").trim().split(/\s+/).filter(Boolean);
  return words.slice(0, 100).join(" ") + (words.length > 100 ? "…" : "");
}
export function toggleScheduled(posts, postId) {
  return posts.some(p => p.post_id === postId)
    ? posts.filter(p => p.post_id !== postId)
    : [...posts, { post_id: postId, position: Math.max(0, ...posts.map(p => p.position)) + 1 }];
}
export function toggleTag(tags, tagId, sourceRef, visibleStages) {
  return tags.some(tag => tag.tag_id === tagId)
    ? tags.filter(tag => tag.tag_id !== tagId)
    : [...tags, { tag_id: tagId, source_ref: sourceRef, visible_stages: [...visibleStages] }];
}
export function tagSourceStages(registry, family, ref) {
  return ref ? (registry.families[family]?.stages || []).filter(stage =>
    !(ref.endsWith(":article_content") && ["A1", "A2"].includes(stage)) &&
    !(ref.endsWith(":product_description") && stage === "B1")) : [];
}
export function toggleDefaultTag(tags, tagId, preset, sources, registry) {
  // Existing assignments are not migrated, even if their defaults have changed.
  if (tags.some(tag => tag.tag_id === tagId)) return tags.filter(tag => tag.tag_id !== tagId);
  const definition = registry.tags.find(tag => tag.id === tagId);
  const source = sources.find(ref => ref.endsWith(`:${preset?.source_field}`));
  const stages = preset?.visible_stages;
  const allowed = definition && source ? tagSourceStages(registry, definition.family, source) : [];
  if (!source || !Array.isArray(stages) || !stages.length || new Set(stages).size !== stages.length ||
      stages.some(stage => !allowed.includes(stage))) {
    throw new Error("Cấu hình mặc định của đặc điểm chưa phù hợp với ngành này. Vui lòng báo người quản lý cấu hình; dữ liệu đang nhập vẫn được giữ nguyên.");
  }
  return toggleTag(tags, tagId, source, stages);
}
export function chartSegments(points, valueKey) {
  const sorted = [...points].sort((a, b) => a.session_no - b.session_no);
  const max = Math.max(1, ...sorted.map(p => p[valueKey] ?? 0));
  const low = sorted[0]?.session_no || 1, high = sorted.at(-1)?.session_no || low;
  const segments = [];
  let current = [];
  for (const p of sorted) {
    if (p[valueKey] == null) {
      if (current.length) segments.push(current);
      current = [];
    } else current.push({ x: high === low ? 340 : 48 + (p.session_no - low) / (high - low) * 584,
      y: 240 - p[valueKey] / max * 200, point: p });
  }
  if (current.length) segments.push(current);
  return { segments, max, sorted };
}
// ponytail: bounded animation queue; complete history stays in the paged API.
export function appendEvents(queue, events, seen) {
  const fresh = events.filter(event => {
    if (seen.has(event.event_id)) return false;
    seen.add(event.event_id);
    return true;
  });
  return [...queue, ...fresh].slice(-200);
}
