import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Download, Eye, Play, ShoppingBag, Store, ThumbsDown, ThumbsUp, TrendingUp, Users, X } from "lucide-react";
import { API, all, downloadConfiguration, id, request } from "./api.js";
import { actions, appendEvents, format, latestMetric, liveMetrics, sessionHistoryFromReport, stages, statuses, updateSessionHistory } from "./model.js";
import { tagText } from "./copy.js";
import { Badge, Button, Empty, ErrorBox, Field, Intro, LineChart, Link, Persona, Resource, ScheduleTable, Tags, navigate, useConfirm, useResource } from "./ui.jsx";

const completedResultCache = new Map();
const completedHistoryCache = new Map();

export function Run({ runId, tab, detailId, onBundle }) {
  const resource = useResource(async signal => {
    const [run, objects, sessions, agents, config] = await Promise.all([
      request(`/runs/${id(runId)}`, { signal }), request(`/runs/${id(runId)}/objects`, { signal }),
      request(`/runs/${id(runId)}/sessions`, { signal }), all(`/runs/${id(runId)}/agents`, signal),
      request(`/runs/${id(runId)}/configuration`, { signal }),
    ]);
    return { run, objects, sessions, agents, config };
  }, [runId]);
  useEffect(() => { if (resource.data) onBundle(resource.data.config.input_snapshot.bundle); }, [resource.data, onBundle]);
  const [error, setError] = useState(null), [downloading, setDownloading] = useState(false);
  async function download() {
    setDownloading(true); setError(null);
    try { await downloadConfiguration(runId); } catch (e) { setError(e); } finally { setDownloading(false); }
  }
  return <Resource resource={resource}>{data => <>
    <Intro eyebrow="LẦN MÔ PHỎNG" title={data.config.input_snapshot.setup.name} action={<div className="toolbar">
      <Button variant="outline" disabled={downloading} onClick={download}><Download size={16} />Tải cấu hình</Button>
    </div>}>
      <code>{runId}</code> · {data.agents.length} người · {data.sessions.length} phiên · <Badge status={data.run.status} />
    </Intro>
    <div className="tabs" aria-label="Các phần của lần mô phỏng">
      {[["live", "Diễn biến"], ["results", "Kết quả"], ["config", "Cấu hình"], ["articles", "Bài viết"], ["shop", "Cửa hàng"], ["agents", "Người tham gia"]].map(([path, label]) =>
        <Link key={path} className={tab === path ? "active" : ""} to={`/runs/${runId}/${path}`}>{label}</Link>)}
    </div><ErrorBox error={error} />
    {tab === "live" ? <Live {...data} reload={resource.reload} /> :
      tab === "agents" ? <AgentHistory runId={runId} agents={data.agents} objects={data.objects} selectedId={detailId} runStatus={data.run.status} /> :
      tab === "config" ? <RunConfiguration config={data.config} sessions={data.sessions} /> :
        <Results {...data} tab={tab} detailId={detailId} />}
  </>}</Resource>;
}

function RunConfiguration({ config, sessions }) {
  const snapshot = config.input_snapshot || {};
  const setup = snapshot.setup || {};
  const campaign = snapshot.campaign || {};
  const shops = setup.shops || [];
  const posts = setup.posts || [];
  const products = setup.products || [];
  return <section className="run-configuration stack">
    <div className="section-heading"><div><h2>Cấu hình của lần mô phỏng</h2><p>Đây là thông tin đã được lưu cùng lần chạy. Bạn chỉ xem lại, không chỉnh sửa cấu hình cũ.</p></div></div>
    <section className="card run-config-business stack">
      <div className="section-heading"><div><span className="eyebrow">THÔNG TIN CHUNG</span><h3>{setup.business?.brand_name || "Chưa đặt tên thương hiệu"}</h3></div><span className="badge">{setup.industry_id === "cafe" ? "Cà phê" : setup.industry_id || "Ngành chưa xác định"}</span></div>
      <div className="run-config-grid">
        <div><small>Tên chiến dịch</small><strong>{campaign.name || "—"}</strong><p>{campaign.brief || "Chưa có thông điệp chiến dịch."}</p></div>
        <div><small>Đơn vị kinh doanh</small><strong>{setup.business?.organization_name || "—"}</strong><p>{setup.business?.organization_description || "Chưa có giới thiệu đơn vị kinh doanh."}</p></div>
      </div>
      <Tags tags={setup.business?.tags} />
    </section>
    <section className="run-config-grid run-config-grid-wide">
      {shops.map(shop => <article className="card run-config-shop stack" key={shop.shop_id}>
        <div className="section-heading"><div><span className="eyebrow">CỬA HÀNG</span><h3>{shop.name}</h3></div><span className="hint">{products.filter(product => product.shop_id === shop.shop_id).length} sản phẩm</span></div>
        <p>{shop.public_profile || "Chưa có giới thiệu cửa hàng."}</p><Tags tags={shop.tags} />
        <div className="run-config-products">{products.filter(product => product.shop_id === shop.shop_id).sort((a, b) => a.position - b.position).map(product =>
          <div className="run-config-item" key={product.product_id}><div><strong>{product.product_name}</strong><span className="price">{product.listed_price}</span></div><p>{product.product_description || "Chưa có mô tả sản phẩm."}</p><Tags tags={product.tags} /></div>)}</div>
      </article>)}
    </section>
    <section className="card run-config-articles stack">
      <div className="section-heading"><div><span className="eyebrow">BÀI VIẾT QUẢNG CÁO</span><h2>{posts.length} bài viết</h2></div><span className="hint">{setup.sessions?.length || sessions.length} phiên</span></div>
      {posts.map(post => <article className="run-config-item" key={post.post_id}><div className="section-heading"><div><h3>{post.title}</h3><small>{shops.find(shop => shop.shop_id === post.shop_id)?.name || "Chưa gắn cửa hàng"}</small></div></div><p>{post.preview || "Chưa có phần giới thiệu trước khi đọc."}</p><Tags tags={post.tags} /><details><summary>Đọc nội dung đầy đủ</summary><p className="preserve">{post.article_content || "Chưa có nội dung đầy đủ."}</p></details></article>)}
      {!posts.length && <Empty title="Chưa có bài viết">Lần mô phỏng này không có bài viết được chuẩn bị.</Empty>}
    </section>
    <section className="card run-config-schedule stack"><div><span className="eyebrow">LỊCH ĐĂNG</span><h2>Bài nào xuất hiện ở từng phiên?</h2></div><ScheduleTable sessions={sessions} posts={posts} /></section>
  </section>;
}

function Live({ run, objects, sessions, agents, reload }) {
  const confirm = useConfirm();
  const [progress, setProgress] = useState(null), [events, setEvents] = useState([]), [error, setError] = useState(null);
  const [sessionHistory, setSessionHistory] = useState([]);
  const [connection, setConnection] = useState("Đang kết nối"), [busy, setBusy] = useState(false);
  const command = useRef(null);
  useEffect(() => {
    let active = true, source, fallbackTimer;
    let queue = [], seen = new Set(), cursor = null, pendingPoll = false;
    const terminal = ["completed", "failed"].includes(run.status);
    function receive(message) {
      if (!active) return;
      cursor = message.cursor;
      if (message.resync_required) { queue = []; seen = new Set(); setEvents([]); }
      if (message.progress) {
        setProgress(message.progress);
        setSessionHistory(history => updateSessionHistory(history, message.progress, run.run_id));
      }
      queue = appendEvents(queue, message.events || [], seen);
      if (["run_completed", "run_failed"].includes(message.type)) {
        queue = []; source?.close(); clearInterval(fallbackTimer);
        reload();
        if (message.type === "run_completed") navigate(`/runs/${run.run_id}/results`);
      } else if (message.type === "session_completed") {
        request(`/runs/${id(run.run_id)}/progress`).then(p => {
          if (active) {
            setProgress(p);
            setSessionHistory(history => updateSessionHistory(history, p, run.run_id, true));
          }
        }).catch(e => { if (active) setError(e); });
      }
    }
    async function poll() {
      if (!active || pendingPoll) return;
      pendingPoll = true;
      try {
        const page = await request(`/runs/${id(run.run_id)}/updates?limit=100${cursor ? `&after=${encodeURIComponent(cursor)}` : ""}`);
        if (active) {
          page.items.forEach(receive); setError(null);
          if (!page.items.length) {
            const current = await request(`/runs/${id(run.run_id)}`);
            if (active && ["completed", "failed"].includes(current.status)) {
              clearInterval(fallbackTimer); reload();
              if (current.status === "completed") navigate(`/runs/${run.run_id}/results`);
            }
          }
        }
      } catch (e) { if (active) setError(e); } finally { pendingPoll = false; }
    }
    Promise.all([
      request(`/runs/${id(run.run_id)}/progress`),
      request(`/runs/${id(run.run_id)}/report`),
      request(`/runs/${id(run.run_id)}/events?limit=20`),
    ]).then(([p, report, recent]) => {
      if (!active) return;
      const recentEvents = recent?.items || [];
      recentEvents.forEach(event => seen.add(event.event_id));
      setEvents(recentEvents);
      setProgress(p);
      setSessionHistory(updateSessionHistory(
        sessionHistoryFromReport(report, run.run_id), p, run.run_id, true));
      cursor = p.cursor;
      if (p.status !== run.status) {
        reload();
        if (p.status === "completed") navigate(`/runs/${run.run_id}/results`);
        return;
      }
      if (terminal || run.status === "ready") { setConnection("Dữ liệu đã lưu"); return; }
      source = new EventSource(`${API}/runs/${id(run.run_id)}/stream?after=${encodeURIComponent(cursor)}`);
      source.onopen = () => { if (active) { setConnection("Đang nhận diễn biến"); setError(null); } };
      ["run_started", "progress_batch", "session_completed", "run_completed", "run_failed", "reset"].forEach(type =>
        source.addEventListener(type, event => {
          try { receive(JSON.parse(event.data)); } catch { setError(new Error("Gói diễn biến không hợp lệ. Hãy tải lại lần chạy.")); }
        }));
      source.onerror = () => {
        source.close(); setConnection("Đang cập nhật định kỳ");
        poll(); fallbackTimer = setInterval(poll, 3000);
      };
    }).catch(e => { if (active) setError(e); });
    const timer = setInterval(() => {
      if (!queue.length || !active) return;
      const count = matchMedia("(prefers-reduced-motion: reduce)").matches ? queue.length : Math.min(5, queue.length);
      const next = queue.splice(0, count);
      setEvents(old => [...old, ...next].slice(-20));
    }, 180);
    return () => { active = false; source?.close(); clearInterval(timer); clearInterval(fallbackTimer); };
  }, [run.run_id, run.status]);
  async function start() {
    const resume = run.status === "failed";
    if (!await confirm("Thao tác này gọi JEV/OpenAI thật và có thể phát sinh phí.", {
      title: `${resume ? "Chạy tiếp" : "Bắt đầu"} mô phỏng?`, confirmLabel: resume ? "Chạy tiếp mô phỏng" : "Bắt đầu mô phỏng",
    })) return;
    setBusy(true); setError(null);
    if (!command.current) command.current = crypto.randomUUID();
    try {
      await request(`/runs/${id(run.run_id)}/${resume ? "resume" : "start"}`, { method: "POST", key: command.current });
      command.current = null; reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const count = (scope, objectId, metric) => progress?.counters.find(c => c.scope_type === scope && c.scope_id === objectId)?.values[metric];
  const runValues = progress?.counters.find(c => c.scope_type === "run" && c.scope_id === run.run_id)?.values || {};
  const latestEvent = events.at(-1);
  const latestAgent = agents.find(agent => agent.agent_id === latestEvent?.agent_id);
  const latestObject = latestEvent?.object_type === "article"
    ? objects.posts.find(post => post.post_id === latestEvent.object_id)
    : objects.products.find(product => product.product_id === latestEvent?.object_id);
  return <>
    <ErrorBox error={error} retry={reload} />
    <section className="run-banner">
      <div><span className="eyebrow"><i className={`connection-dot ${connection === "Đang nhận diễn biến" ? "is-live" : ""}`} />{connection}</span><h2>{statuses[progress?.status || run.status]}</h2><p>Phiên {progress?.session_no || "—"} / {sessions.length} · {progress?.completed_agents ?? "—"} / {progress?.active_agents ?? "—"} người hoàn tất trong phiên</p></div>
      {["ready", "failed"].includes(run.status) && <Button variant="primary" disabled={busy} onClick={start}><Play size={16} />{busy ? "Đang gửi…" : run.status === "failed" ? "Chạy tiếp mô phỏng" : "Bắt đầu mô phỏng"}</Button>}
      {run.status === "completed" && <Link className="button button-primary" to={`/runs/${run.run_id}/results`}>Xem kết quả <ArrowRight size={16} /></Link>}
    </section>
    {run.failure_code && <p role="alert">Lần chạy gặp lỗi: <code>{run.failure_code}</code>. Dữ liệu đã ghi vẫn được giữ.</p>}
    <LiveCurrentActivity event={latestEvent} agent={latestAgent} object={latestObject} runStatus={run.status} />
    <LiveFlow activeStage={latestEvent?.stage} />
    <LiveStateCharts history={sessionHistory} sessionCount={sessions.length} />
    <LiveRunStats values={runValues} progress={progress} />
    <div className="live-theater-grid">
      <section className="live-feed stack"><div className="section-heading"><div><h2>Dòng diễn biến</h2><p>Mỗi thẻ là một bước vừa được ghi nhận từ người dùng ảo.</p></div><span className="badge">{events.length} gần nhất</span></div>
        {!events.length && <div className="card live-empty"><p>Mô phỏng chưa có diễn biến mới.</p><small>Khi bắt đầu, các quyết định sẽ lần lượt xuất hiện ở đây.</small></div>}
        <ol className="activity-list">{[...events].reverse().map((event, index) => <LiveEvent key={event.event_id} event={event} index={index} agents={agents} objects={objects} />)}</ol>
      </section>
      <section className="live-inventory stack"><div className="section-heading"><div><h2>Nội dung đang được thử</h2><p>Chỉ số rút gọn của bài viết và sản phẩm trong lần chạy này.</p></div></div>
        <section className="live-object-section"><h3>Bài quảng cáo</h3>{objects.posts.map(post => <LivePost key={post.post_id} post={post} brand={objects.business.brand_name} count={count} />)}</section>
        {objects.shops.map(shop => <section className="live-object-section" key={shop.shop_id}><div className="section-heading"><h3>{shop.name}</h3><span className="hint">{format(count("shop", shop.shop_id, "shop_visits"))} lượt ghé</span></div>
          {objects.products.filter(product => product.shop_id === shop.shop_id).sort((a, b) => a.position - b.position).map(product => <LiveProduct key={product.product_id} product={product} count={count} />)}
        </section>)}
      </section>
    </div>
    <ScheduleTable sessions={sessions} posts={objects.posts} />
  </>;
}

function LiveStateCharts({ history, sessionCount }) {
  return <section className="live-state-section stack" aria-label="Trạng thái thay đổi theo phiên">
    <div className="section-heading"><div><h2>Trạng thái qua từng phiên</h2>
      <p>Đường biểu diễn cho biết số liệu đang tích lũy. Điểm đang chạy là tạm thời; điểm của phiên hoàn tất là số liệu chính thức.</p>
    </div><span className="live-chart-legend"><i className="live-dot" /> Đang chạy</span></div>
    {!history.length ? <div className="card live-chart-empty"><p>Biểu đồ sẽ bắt đầu khi mô phỏng xử lý người đầu tiên.</p><small>{sessionCount} phiên đã được chuẩn bị.</small></div> :
      <div className="live-chart-grid">{liveMetrics.map(([name, label]) =>
        <LiveMetricChart key={name} label={label} metric={name} history={history} sessionCount={sessionCount} />)}</div>}
  </section>;
}

function LiveCurrentActivity({ event, agent, object, runStatus }) {
  const finished = runStatus === "completed";
  return <section className={`live-current card ${event ? "has-event" : ""}`}>
    <div className="section-heading"><div><span className="eyebrow">{finished ? "DIỄN BIẾN CUỐI CÙNG" : "ĐANG DIỄN RA"}</span><h2>{event ? `${agent ? `Người ${String(agent.ordinal).padStart(2, "0")}` : "Một người dùng ảo"} ${finished ? "đã" : "đang"} ${stages[event.stage]?.toLowerCase() || "xử lý"}` : "Chờ bắt đầu mô phỏng"}</h2></div>
      {event && <Badge status={event.status} />}</div>
    {event ? <div className="live-current-detail"><div><strong>{object?.title || object?.product_name || "Nội dung đang được xử lý"}</strong><small>Phiên {event.session_no} · {stages[event.stage] || event.stage}</small></div>
      <div className="live-current-action"><span>Kết quả bước này</span><strong>{actions[event.action] || statuses[event.status] || "Đang xử lý"}</strong></div>
      {!!event.tags?.length && <Tags tags={event.tags} />}</div>
      : <p>Bấm “Bắt đầu mô phỏng” để xem từng người dùng ảo chú ý, đọc và đưa ra quyết định.</p>}
  </section>;
}

function LiveFlow({ activeStage }) {
  const steps = [["A1", "Chú ý"], ["A3", "Đọc"], ["A5", "Ghé cửa hàng"], ["B1", "Chú ý sản phẩm"], ["B3", "Mua"]];
  return <section className="live-flow card" aria-label="Các bước mô phỏng"><span className="eyebrow">LUỒNG MÔ PHỎNG</span><div>{steps.map(([stage, label], index) =>
    <span className={activeStage === stage || (stage === "A3" && activeStage === "A2") || (stage === "B3" && activeStage === "B2") ? "is-active" : ""} key={stage}><i>{index + 1}</i>{label}</span>)}</div></section>;
}

function LiveRunStats({ values, progress }) {
  const stats = [["posts_read", "Bài đã đọc"], ["shop_visits", "Lượt ghé shop"], ["products_attended", "Sản phẩm được chú ý"], ["buys", "Lượt mua"]];
  return <section className="live-run-stats" aria-label="Số liệu đang tích lũy">{stats.map(([name, label]) =>
    <article key={name}><span>{label}</span><strong>{format(values[name])}</strong><small>{progress?.provisional ? "Số liệu tạm thời" : "Số liệu đã chốt"}</small></article>)}</section>;
}

function LiveEvent({ event, index, agents, objects }) {
  const agent = agents.find(item => item.agent_id === event.agent_id);
  const object = event.object_type === "article"
    ? objects.posts.find(item => item.post_id === event.object_id)
    : objects.products.find(item => item.product_id === event.object_id);
  return <li className={`live-event ${index === 0 ? "is-latest" : ""}`}><span className="live-event-index">{index + 1}</span><div><strong>Người {String(agent?.ordinal || "?").padStart(2, "0")}</strong><span>{stages[event.stage] || event.stage} · {event.session_no ? `Phiên ${event.session_no}` : ""}</span><p>{object?.title || object?.product_name || "Nội dung không xác định"}{event.action ? ` · ${actions[event.action] || event.action}` : ""}</p>{event.tags?.length ? <Tags tags={event.tags} /> : null}</div></li>;
}

function LivePost({ post, brand, count }) {
  return <article className="live-object-card"><span className="eyebrow">{brand}</span><h3>{post.title}</h3><p>{post.preview}</p><div className="counters"><span><Eye size={16} aria-hidden="true" />{format(count("article", post.post_id, "posts_read"))} đọc</span><span><ThumbsUp size={16} aria-hidden="true" />{format(count("article", post.post_id, "current_likes"))} thích</span><span><ThumbsDown size={16} aria-hidden="true" />{format(count("article", post.post_id, "current_dislikes"))} không thích</span></div></article>;
}

function LiveProduct({ product, count }) {
  return <article className="live-object-card product"><div className="section-heading"><h3>{product.product_name}</h3><strong className="price">{product.listed_price}</strong></div><div className="counters"><span>{format(count("product", product.product_id, "products_attended"))} chú ý</span><span>{format(count("product", product.product_id, "buys"))} mua</span></div></article>;
}

function LiveMetricChart({ label, metric, history, sessionCount }) {
  const width = 420, height = 150, left = 12, right = 12, top = 18, bottom = 28;
  const maxSession = Math.max(sessionCount, history.at(-1)?.session_no || 1);
  const maxValue = Math.max(1, ...history.map(point => point.values[metric] || 0));
  const x = session => maxSession === 1 ? width / 2 : left + (session - 1) / (maxSession - 1) * (width - left - right);
  const y = value => height - bottom - (value / maxValue) * (height - top - bottom);
  const points = history.map(point => `${x(point.session_no)},${y(point.values[metric] || 0)}`).join(" ");
  const last = history.at(-1);
  return <article className="live-chart-card">
    <div className="section-heading"><h3>{label}</h3><strong>{format(last.values[metric])}</strong></div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label} theo từng phiên`}>
      <text x={left} y={top - 4}>{format(maxValue)}</text>
      <polyline className="live-chart-line" points={points} />
      {history.map(point => <circle className={point.provisional ? "is-provisional" : ""} key={point.session_no}
        cx={x(point.session_no)} cy={y(point.values[metric] || 0)} r="4">
        <title>Phiên {point.session_no}: {format(point.values[metric])}{point.provisional ? " · tạm thời" : ""}</title>
      </circle>)}
      {Array.from({ length: maxSession }, (_, index) => <text key={index} x={x(index + 1)} y={height - 6} textAnchor="middle">{index + 1}</text>)}
    </svg>
    <small>Phiên hiện tại: {last.session_no}{last.provisional ? " · đang cập nhật" : " · đã hoàn tất"}</small>
  </article>;
}

function Results({ run, objects, sessions, agents, tab, detailId }) {
  const resource = useResource(async signal => {
    const cacheKey = run.run_id;
    if (run.status === "completed" && completedResultCache.has(cacheKey)) {
      return completedResultCache.get(cacheKey);
    }
    const [report, definitions] = await Promise.all([
      request(`/runs/${id(run.run_id)}/report`, { signal }),
      request(`/runs/${id(run.run_id)}/metric-definitions`, { signal }),
    ]);
    const data = { report, definitions };
    if (run.status === "completed") completedResultCache.set(cacheKey, data);
    return data;
  }, [run.run_id, run.status]);
  const [chosen, setChosen] = useState(null), [metric, setMetric] = useState(""), [cumulative, setCumulative] = useState(true);
  return <Resource resource={resource}>{({ report, definitions }) => {
    const options = tab === "articles" ? objects.posts.map(p => ({ id: p.post_id, name: p.title, type: "article" }))
      : tab === "shop" ? [...objects.shops.map(s => ({ id: s.shop_id, name: s.name, type: "shop" })), ...objects.products.map(p => ({ id: p.product_id, name: p.product_name, type: "product" }))] : [];
    const selected = options.find(o => detailId ? o.id === detailId : o.id === chosen?.id && o.type === chosen?.type) || options[0];
    const selectedScope = tab === "results" ? "run" : selected?.type;
    const selectedId = selectedScope === "run" ? run.run_id : selected?.id;
    const post = objects.posts.find(p => selectedScope === "article" && p.post_id === selected?.id);
    const product = objects.products.find(p => selectedScope === "product" && p.product_id === selected?.id);
    const shop = objects.shops.find(s => selectedScope === "shop" && s.shop_id === selected?.id);
    const available = definitions.filter(d => d.scopes.includes(selectedScope));
    const choices = (resultMetricChoices[selectedScope] || []).filter(name => available.some(d => d.name === name));
    const defaultMetric = choices[0];
    const definition = available.find(d => d.name === metric) || available.find(d => d.name === defaultMetric);
    const points = report.metrics.filter(p => p.scope_type === selectedScope && p.scope_id === selectedId && p.metric_name === definition?.name);
    const summary = resultSummary.map(item => ({ ...item, value: latestMetric(report, run.run_id, item.metric, "cumulative_value") }));
    return <>
      <ResultHero run={run} report={report} sessions={sessions} agents={agents} />
      {report.partial && <p className="notice">Lần mô phỏng chưa hoàn tất. Những biểu đồ dưới đây chỉ tính các phiên đã chốt.</p>}
      {tab === "results" && <section className="result-summary-grid">{summary.map(item => <ResultSummaryCard key={item.metric} {...item} />)}</section>}
      <p className="hint">Số lượt có thể gồm nhiều lần của cùng một người. Phản ứng thích / không thích là số đang được giữ ở cuối phiên, không phải tổng số lần bấm.</p>
      {tab !== "results" && <ResultObjectPicker tab={tab} options={options} selected={selected} onChoose={next => { setChosen(next); setMetric(""); if (detailId) navigate(`/runs/${run.run_id}/${tab}`); }} objects={objects} />}
      {(post || product || shop) && <ResultObjectIntro post={post} product={product} shop={shop} />}
      {definition ? <div className="results-layout result-analysis"><ResultMetricPicker selectedScope={selectedScope} choices={choices} selected={definition.name} definitions={available} onChoose={setMetric} />
        <section className="chart-card result-chart-panel stack"><div className="section-heading"><div><p>{selected?.name || "Toàn bộ lần mô phỏng"}</p><h2>{friendlyMetricLabel(definition.name, definition.label_vi)}</h2></div>{definition.kind !== "state" && <Field label="Cách xem"><select value={cumulative ? "total" : "session"} onChange={e => setCumulative(e.target.value === "total")}><option value="session">Riêng từng phiên</option><option value="total">Tích lũy đến mỗi phiên</option></select></Field>}</div>
          <p>{friendlyMetricDescription(definition.name, definition.description_vi)}</p>{definition.kind === "state" && <p className="hint">Đây là số đang còn ở trạng thái hiện tại, không cộng dồn qua các phiên.</p>}
          <LineChart points={points} definition={{ ...definition, label_vi: friendlyMetricLabel(definition.name, definition.label_vi) }} cumulative={definition.kind !== "state" && cumulative} />
        </section></div> : <Empty>Chưa có dữ liệu biểu đồ cho phần này.</Empty>}
      {tab === "results" && <ResultObjects objects={objects} report={report} runId={run.run_id} />}
      {tab === "shop" && shop && <ResultShopCard shop={shop} products={objects.products} report={report} runId={run.run_id} />}
      <Link className="button button-outline" to={`/runs/${run.run_id}/agents`}>Xem hành trình từng người <ArrowRight size={16} aria-hidden="true" /></Link>
      <section className="result-support-grid"><details className="card"><summary>Lịch đăng và thứ tự bài viết</summary><p className="hint">Lịch đã chuẩn bị cho toàn bộ lần chạy, kể cả phiên chưa hoàn tất.</p><ScheduleTable sessions={sessions} posts={objects.posts} /></details><details className="card result-cost"><summary>Token đã sử dụng: {format(report.usage.total_tokens)}</summary><p>Token là đơn vị nội dung mô hình xử lý, không phải số tiền. Đây là tổng được nhà cung cấp trả về; có {report.usage.usage_missing_attempts} / {report.usage.attempts} lượt gọi thiếu số liệu.</p><div className="table-wrap"><table><thead><tr><th>Phiên</th><th>Đầu vào</th><th>Đầu ra</th><th>Tổng</th><th>Lượt thiếu số liệu</th></tr></thead><tbody>{report.usage.by_session.map(s => <tr key={s.session_no}><td>{s.session_no}</td><td>{format(s.input_tokens)}</td><td>{format(s.output_tokens)}</td><td>{format(s.total_tokens)}</td><td>{s.usage_missing_attempts}</td></tr>)}</tbody></table></div></details></section>
    </>;
  }}</Resource>;
}

const resultMetricChoices = {
  run: ["posts_read", "posts_attended", "current_likes", "current_dislikes", "shop_visits", "products_attended", "buys", "post_attention_rate", "purchase_rate"],
  article: ["posts_exposed", "posts_attended", "posts_read", "current_likes", "current_dislikes", "likes_added", "dislikes_added", "read_rate"],
  shop: ["shop_visits", "shop_not_visits", "products_attended", "buys", "purchase_rate"],
  product: ["products_exposed", "products_attended", "products_skipped", "buys", "not_buys", "purchase_rate"],
};
const resultSummary = [
  { metric: "posts_read", label: "Lượt đọc bài viết", note: "Số lần người dùng ảo đọc bài quảng cáo." },
  { metric: "shop_visits", label: "Lượt ghé cửa hàng", note: "Số lần người dùng ảo quyết định ghé cửa hàng." },
  { metric: "products_attended", label: "Lượt chú ý sản phẩm", note: "Số lần sản phẩm được chú ý trong cửa hàng." },
  { metric: "buys", label: "Lượt mua", note: "Số quyết định mua được ghi nhận." },
];
const friendlyLabels = {
  posts_exposed: "Lượt gặp bài viết", posts_attended: "Lượt chú ý bài viết", posts_read: "Lượt đọc bài viết",
  current_likes: "Phản ứng thích còn giữ", current_dislikes: "Phản ứng không thích còn giữ",
  likes_added: "Lượt chọn thích", dislikes_added: "Lượt chọn không thích",
  shop_visits: "Lượt ghé cửa hàng", shop_not_visits: "Lượt không ghé cửa hàng",
  products_exposed: "Lượt gặp sản phẩm", products_attended: "Lượt chú ý sản phẩm", products_skipped: "Lượt bỏ qua sản phẩm",
  buys: "Lượt mua", not_buys: "Lượt không mua", post_attention_rate: "Tỷ lệ chú ý bài viết",
  read_rate: "Tỷ lệ đọc sau khi chú ý", purchase_rate: "Tỷ lệ mua",
};
function friendlyMetricLabel(name, fallback = name) {
  if (name.startsWith("tag.")) {
    const stage = name.split(".")[1];
    const tag = name.slice(`tag.${stage}.`.length, -".selected".length);
    return `${tagText(tag).label} · ${stages[stage] || stage}`;
  }
  return friendlyLabels[name] || fallback;
}
function friendlyMetricDescription(name, fallback) {
  const descriptions = {
    posts_exposed: "Số lần bài viết được đưa tới trước người dùng ảo.",
    posts_attended: "Số lần người dùng ảo dừng lại để chú ý bài viết.",
    posts_read: "Số lần người dùng ảo đọc nội dung đầy đủ.",
    current_likes: "Số phản ứng thích còn được giữ ở cuối mỗi phiên. Một người có thể thích nhiều bài.",
    current_dislikes: "Số phản ứng không thích còn được giữ ở cuối mỗi phiên. Một người có thể phản ứng với nhiều bài.",
    shop_visits: "Số quyết định ghé cửa hàng được ghi nhận.",
    products_attended: "Số lần người dùng ảo dừng lại để chú ý một sản phẩm.",
    buys: "Số quyết định mua được ghi nhận.",
    products_exposed: "Số lần sản phẩm được đưa tới bước cân nhắc chú ý, chưa đồng nghĩa với đã chú ý.",
    purchase_rate: "Số lượt quyết định mua chia cho số lượt có quyết định mua hoặc không mua hợp lệ. Không phải tỷ lệ trên tổng người tham gia.",
    post_attention_rate: "Số lượt chú ý bài viết chia cho số lượt có quyết định chú ý hoặc bỏ qua hợp lệ.",
    product_attention_rate: "Số lượt chú ý sản phẩm chia cho số lượt có quyết định chú ý hoặc bỏ qua hợp lệ.",
    shop_visit_rate: "Số lượt ghé cửa hàng chia cho số lượt có quyết định ghé hoặc không ghé hợp lệ.",
    read_rate: "Số lượt hoàn tất bước đọc chia cho số lượt chú ý bài viết.",
  };
  return descriptions[name] || fallback;
}
function ResultHero({ run, report, sessions, agents }) {
  return <section className="result-hero card"><div><h2>Kết quả mô phỏng</h2><p>Khách hàng ảo đã đọc bài, ghé cửa hàng và chọn mua như thế nào?</p></div>
    <div className="result-hero-meta"><Badge status={run.status} /><span><Users size={16} aria-hidden="true" />{agents?.length ?? "—"} người</span><span><BookOpen size={16} aria-hidden="true" />{sessions.length} phiên</span><span><TrendingUp size={16} aria-hidden="true" />{report.sessions.length} phiên đã chốt</span></div></section>;
}
function ResultSummaryCard({ label, note, value }) {
  return <article className="result-summary-card"><span>{label}</span><strong>{format(value)}</strong><small>{note}</small></article>;
}
function ResultMetricPicker({ selectedScope, choices, selected, definitions, onChoose }) {
  return <aside className="metric-list result-metric-picker stack"><div><h3>Bạn muốn xem điều gì?</h3><p>Chọn chỉ số để xem thay đổi qua từng phiên.</p></div>
    <div className="result-metric-options">{choices.map(name => <button type="button" className={`result-metric-option ${selected === name ? "is-active" : ""}`} aria-pressed={selected === name} key={name} onClick={() => onChoose(name)}><span>{friendlyMetricLabel(name)}</span></button>)}</div>
    <details><summary>Các chỉ số khác</summary><Field label="Chọn chỉ số bổ sung"><select value={choices.includes(selected) ? "" : selected} onChange={e => { if (e.target.value) onChoose(e.target.value); }}><option value="">Chọn một chỉ số…</option>{definitions.filter(d => !choices.includes(d.name)).map(d => <option key={d.name} value={d.name}>{friendlyMetricLabel(d.name, d.label_vi)}</option>)}</select></Field></details>
  </aside>;
}
function ResultObjectPicker({ tab, options, selected, onChoose, objects }) {
  return <section className="result-object-picker stack"><h2>{tab === "articles" ? "Chọn bài viết muốn xem" : "Chọn cửa hàng hoặc sản phẩm"}</h2>
    <div className="result-object-options">{options.map(option => <button type="button" key={`${option.type}:${option.id}`} aria-pressed={selected?.id === option.id && selected?.type === option.type} className={`result-object-option ${selected?.id === option.id && selected?.type === option.type ? "is-active" : ""}`} onClick={() => onChoose(option)}><span className="result-object-icon">{option.type === "article" ? <BookOpen size={18} aria-hidden="true" /> : option.type === "shop" ? <Store size={18} aria-hidden="true" /> : <ShoppingBag size={18} aria-hidden="true" />}</span><span><strong>{option.name}</strong><small>{option.type === "article" ? "Bài viết" : option.type === "shop" ? "Cửa hàng" : `${objects.products.find(p => p.product_id === option.id)?.listed_price || ""}`}</small></span></button>)}</div></section>;
}
function ResultObjectIntro({ post, product, shop }) {
  const object = post || product || shop;
  return <article className="card result-object-intro stack"><div className="section-heading"><h2>{post?.title || product?.product_name || shop?.name}</h2>{product && <strong className="price">{product.listed_price}</strong>}</div>
    <details key={post?.post_id || product?.product_id || shop?.shop_id}><summary>{post ? "Đọc nội dung bài viết và đặc điểm" : "Xem mô tả và đặc điểm"}</summary><div className="stack"><p className="preserve">{post?.article_content || product?.product_description || shop?.public_profile}</p><Tags tags={object.tags} /></div></details></article>;
}
function ResultObjects({ objects, report, runId }) {
  return <section className="result-detail-sections stack"><div className="section-heading"><div><h2>Bài viết hoạt động thế nào?</h2><p>Tổng lượt đọc và phản ứng còn giữ ở phiên đã chốt gần nhất.</p></div></div>
    <div className="result-object-grid">{objects.posts.map(post => <ResultPostCard key={post.post_id} post={post} report={report} runId={runId} />)}</div>
    <div className="section-heading result-shop-heading"><div><h2>Cửa hàng và sản phẩm</h2><p>Tổng lượt ghé, chú ý sản phẩm và mua qua các phiên đã chốt.</p></div></div>
    <div className="result-shop-grid">{objects.shops.map(shop => <ResultShopCard key={shop.shop_id} shop={shop} products={objects.products} report={report} runId={runId} />)}</div>
  </section>;
}
function ResultPostCard({ post, report, runId }) {
  return <article className="card result-object-card stack"><h3>{post.title}</h3><p>{post.preview}</p><div className="result-object-numbers"><span><small>Đọc</small><strong>{format(latestMetric(report, post.post_id, "posts_read", "cumulative_value", "article"))}</strong></span><span><small>Thích còn giữ</small><strong>{format(latestMetric(report, post.post_id, "current_likes", "cumulative_value", "article"))}</strong></span><span><small>Không thích còn giữ</small><strong>{format(latestMetric(report, post.post_id, "current_dislikes", "cumulative_value", "article"))}</strong></span></div><Link className="button button-outline" to={`/runs/${runId}/articles/${id(post.post_id)}`} aria-label={`Xem biểu đồ bài viết ${post.title}`}>Xem biểu đồ bài viết <ArrowRight size={16} aria-hidden="true" /></Link></article>;
}
function ResultShopCard({ shop, products, report, runId }) {
  return <article className="card result-shop-card"><div className="section-heading"><h3>{shop.name}</h3><div><strong className="result-big-number">{format(latestMetric(report, shop.shop_id, "shop_visits", "cumulative_value", "shop"))}</strong><small> lượt ghé</small></div></div><div className="result-product-list">{products.filter(product => product.shop_id === shop.shop_id).sort((a, b) => a.position - b.position).map(product => <div className="result-product-row" key={product.product_id}><span><Link to={`/runs/${runId}/shop/${id(product.product_id)}`} aria-label={`Xem biểu đồ sản phẩm ${product.product_name}`}><strong>{product.product_name}</strong></Link><small>{product.listed_price}</small></span><span><b>{format(latestMetric(report, product.product_id, "products_attended", "cumulative_value", "product"))}</b><small>chú ý</small></span><span><b>{format(latestMetric(report, product.product_id, "buys", "cumulative_value", "product"))}</b><small>mua</small></span></div>)}</div><Link className="button button-outline" to={`/runs/${runId}/shop/${id(shop.shop_id)}`}>Xem biểu đồ cửa hàng <ArrowRight size={16} aria-hidden="true" /></Link></article>;
}

function AgentHistory({ runId, agents, objects, selectedId, runStatus }) {
  const [choice, setChoice] = useState(selectedId || agents[0]?.agent_id || "");
  const agent = agents.find(a => a.agent_id === choice) || agents[0];
  const [session, setSession] = useState(""), [stage, setStage] = useState("");
  const [extra, setExtra] = useState([]), [cursor, setCursor] = useState(null), [error, setError] = useState(null), [busy, setBusy] = useState(false);
  const query = new URLSearchParams({ limit: "50", ...(session ? { session_no: session } : {}), ...(stage ? { stage } : {}) });
  const path = `/runs/${id(runId)}/agents/${id(agent?.agent_id || "")}/history?${query}`;
  const cacheKey = `${runId}:${path}`;
  const history = useResource(async signal => {
    if (runStatus === "completed" && completedHistoryCache.has(cacheKey)) {
      return completedHistoryCache.get(cacheKey);
    }
    if (!agent) return { items: [], next_cursor: null };
    const page = await request(path, { signal });
    if (runStatus === "completed") completedHistoryCache.set(cacheKey, page);
    return page;
  }, [cacheKey, runStatus]);
  useEffect(() => { setExtra([]); setCursor(null); setError(null); }, [path]);
  async function more() {
    setBusy(true); setError(null);
    try {
      const page = await request(`${path}&after=${encodeURIComponent(cursor || history.data.next_cursor)}`);
      setExtra(prev => [...prev, ...page.items]); setCursor(page.next_cursor || "end");
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <section className="stack"><h2>Mỗi người, một hành trình</h2><p>Đặc điểm ban đầu và diễn biến đã ghi theo từng phiên. Cảm xúc được thể hiện bằng nhãn, không phải đoạn tự sự sinh thêm.</p>
    <div className="form-grid">
      <Field label="Người tham gia"><select value={agent?.agent_id || ""} onChange={e => { setChoice(e.target.value); setSession(""); setStage(""); }}>{agents.map(a => <option key={a.agent_id} value={a.agent_id}>Người {a.ordinal}</option>)}</select></Field>
      <Field label="Lọc phiên" type="number" min="1" value={session} placeholder="Tất cả phiên" onChange={e => setSession(e.target.value)} />
      <Field label="Lọc bước"><select value={stage} onChange={e => setStage(e.target.value)}><option value="">Tất cả bước</option>{Object.entries(stages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
    </div>
    {agent && <Persona person={agent} />}
    <ErrorBox error={error} /><Resource resource={history}>{page => {
      const events = [...page.items, ...extra];
      return <>{!events.length && <Empty>Chưa có hoạt động phù hợp với bộ lọc.</Empty>}
        {!!events.length && <AgentJourney sessions={groupEventsBySession(events)} objects={objects} />}
        {cursor !== "end" && (cursor || page.next_cursor) && <Button disabled={busy} onClick={more}>Xem thêm các phiên</Button>}</>;
    }}</Resource>
  </section>;
}

const journeyLanes = [
  ["A1", "Chú ý bài viết"], ["A3", "Đọc bài viết"], ["A4", "Phản ứng với bài viết"],
  ["A5", "Ghé cửa hàng"], ["B1", "Chú ý sản phẩm"], ["B3", "Quyết định mua"],
];
const journeyLaneIndex = Object.fromEntries(journeyLanes.map(([stage], index) => [stage, index]));
const journeyActionStages = new Set(journeyLanes.map(([stage]) => stage));

function groupEventsBySession(events) {
  return Object.values(events.reduce((groups, event) => {
    (groups[event.session_no] ||= []).push(event);
    return groups;
  }, {})).sort((a, b) => a[0].session_no - b[0].session_no);
}

function AgentJourney({ sessions, objects }) {
  const [selected, setSelected] = useState(null);
  return <section className="agent-journey stack" aria-label="Hành trình theo từng phiên">
    <div className="journey-intro"><div><h2>Hành trình qua từng phiên</h2><p>Mỗi khung là một phiên. Đi từ trái sang phải để thấy người dùng ảo đã lần lượt chú ý, đọc, phản ứng, ghé cửa hàng và mua hàng. Các bước suy nghĩ được gộp vào phần chi tiết của hành động liên quan.</p></div></div>
    {sessions.map(session => <JourneySession key={session[0].session_no} events={session} objects={objects} selected={selected} onSelect={setSelected} />)}
  </section>;
}

function JourneySession({ events, objects, selected, onSelect }) {
  const ordered = [...events].sort((a, b) => (a.sequence_no ?? 0) - (b.sequence_no ?? 0));
  const visible = ordered.filter(event => journeyActionStages.has(event.stage));
  const width = Math.max(900, 172 + visible.length * 212);
  const height = journeyLanes.length * 78 + 36;
  const selectedEvent = selected && visible.some(event => event.event_id === selected.event_id) ? selected : null;
  const markerId = `journey-arrow-${events[0].session_no}`;
  return <article className="journey-session card">
    <div className="section-heading"><div><h3>Phiên {events[0].session_no}</h3><p>{visible.length} hành động chính · đọc từ trái sang phải theo thứ tự xảy ra</p></div><Badge status={events[0].session_status} /></div>
    <div className="journey-scroll" tabIndex={0} aria-label={`Đồ thị hành trình phiên ${events[0].session_no}`}>
      <div className="journey-canvas" style={{ width: `${width}px`, height: `${height}px` }}>
        <div className="journey-lane-labels">{journeyLanes.map(([stage, label]) => <span key={stage}>{label}</span>)}</div>
        <div className="journey-lane-lines" aria-hidden="true">{journeyLanes.map(([stage]) => <span key={stage} />)}</div>
        <svg className="journey-lines" width={width} height={height} aria-hidden="true">
          <defs><marker id={markerId} markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" /></marker></defs>
          {visible.slice(1).map((event, index) => {
            const previous = visible[index];
            const from = journeyNodePosition(index, previous.stage);
            const to = journeyNodePosition(index + 1, event.stage);
            return <line key={`${previous.event_id}-${event.event_id}`} x1={from.x + 178} y1={from.y + 36} x2={to.x} y2={to.y + 36} markerEnd={`url(#${markerId})`} />;
          })}
        </svg>
        {visible.map((event, index) => <JourneyNode key={event.event_id} event={event} index={index} objects={objects}
          selected={selectedEvent?.event_id === event.event_id} onSelect={onSelect} />)}
        {selectedEvent && <JourneyPopover event={selectedEvent} allEvents={ordered} visibleEvents={visible} objects={objects}
          canvasWidth={width} canvasHeight={height} onClose={() => onSelect(null)} />}
      </div>
    </div>
  </article>;
}

function journeyNodePosition(index, stage) {
  return { x: 150 + index * 212, y: 8 + (journeyLaneIndex[stage] ?? 0) * 78 };
}

const journeyNodeLabels = {
  A1: { attend: "Chú ý bài viết", attend_again: "Chú ý lại bài viết", skip: "Bỏ qua bài viết" },
  A1R: { default: "Lý do bỏ qua bài viết" },
  A2: { default: "Cảm nhận ban đầu" },
  A3: { default: "Đọc bài viết" },
  A4: { like: "Thích bài viết", dislike: "Không thích bài viết", keep_current: "Giữ phản ứng", remove_reaction: "Bỏ phản ứng", no_new_reaction: "Không thêm phản ứng", no_reaction: "Không phản ứng" },
  A5: { visit: "Ghé cửa hàng", visit_again: "Ghé lại cửa hàng", not_visit: "Không ghé cửa hàng", not_visit_again: "Không ghé lại cửa hàng" },
  B1: { attend: "Chú ý sản phẩm", attend_again: "Chú ý lại sản phẩm", skip: "Bỏ qua sản phẩm" },
  B1R: { default: "Lý do bỏ qua sản phẩm" },
  B2: { default: "Cân nhắc sản phẩm" },
  B3: { buy: "Mua sản phẩm", buy_again: "Mua lại sản phẩm", not_buy: "Không mua sản phẩm", not_buy_again: "Không mua lại sản phẩm" },
};

function journeyNodeLabel(event) {
  return journeyNodeLabels[event.stage]?.[event.action] ||
    journeyNodeLabels[event.stage]?.default ||
    actions[event.action] || stages[event.stage] || statuses[event.status] || "Chưa có hành động";
}

function JourneyNode({ event, index, objects, selected, onSelect }) {
  const object = event.object_type === "article"
    ? objects.posts.find(item => item.post_id === event.object_id)
    : objects.products.find(item => item.product_id === event.object_id);
  const title = object?.title || object?.product_name || "Không rõ nội dung";
  const position = journeyNodePosition(index, event.stage);
  const actionLabel = journeyNodeLabel(event);
  const label = `Bước ${index + 1}: ${actionLabel}. Nội dung: ${title}.`;
  return <div className="journey-node-wrap" style={{ left: position.x, top: position.y }}>
    <button type="button" className={`journey-node ${selected ? "is-selected" : ""}`} aria-label={label} aria-pressed={selected}
      onFocus={() => onSelect(event)} onClick={() => onSelect(selected ? null : event)}>
      <span className="journey-node-index">Bước {index + 1}</span>
      <strong>{actionLabel}</strong>
      <small>{title}</small>
    </button>
  </div>;
}

function JourneyPopover({ event, allEvents, visibleEvents, objects, canvasWidth, canvasHeight, onClose }) {
  const object = event.object_type === "article"
    ? objects.posts.find(item => item.post_id === event.object_id)
    : objects.products.find(item => item.product_id === event.object_id);
  const index = visibleEvents.findIndex(item => item.event_id === event.event_id);
  const previousVisible = visibleEvents[index - 1];
  const nextVisible = visibleEvents[index + 1];
  const related = allEvents.filter(candidate =>
    !journeyActionStages.has(candidate.stage) &&
    (!previousVisible || candidate.sequence_no > previousVisible.sequence_no) &&
    (!nextVisible || candidate.sequence_no < nextVisible.sequence_no) &&
    candidate.object_id === event.object_id);
  const selectedTags = [...(event.tags || []), ...related.flatMap(item => item.tags || [])]
    .filter(tag => tag.selected)
    .filter((tag, index, tags) => tags.findIndex(item => item.tag_id === tag.tag_id) === index);
  const stepNumber = index + 1;
  const position = journeyNodePosition(index, event.stage);
  const left = Math.min(Math.max(12, position.x - 60), canvasWidth - 432);
  const top = Math.min(Math.max(8, position.y - 24), canvasHeight - 220);
  const actionLabel = journeyNodeLabel(event);
  const reasonTags = selectedTags.filter(tag => tag.tag_id.startsWith("attention_reason."));
  const thoughtTags = selectedTags.filter(tag => !tag.tag_id.startsWith("attention_reason."));
  const isSkip = ["skip", "not_visit", "not_visit_again", "not_buy", "not_buy_again"].includes(event.action);
  const tagTitle = isSkip ? "Lý do không tiếp tục" : "Cảm nhận của người dùng";
  const objectLabel = event.object_type === "product" ? "Sản phẩm" : "Bài viết";
  return <div className="journey-overlay">
    <button type="button" className="journey-overlay-backdrop" aria-label="Đóng thông tin bước này" onClick={onClose} />
    <div className="journey-popover" style={{ left, top }} role="dialog" aria-label={`Thông tin bước ${stepNumber}: ${actionLabel}`}>
      <div className="journey-popover-title"><div><span className="eyebrow">BƯỚC {stepNumber}</span><h4>{actionLabel}</h4><p>{objectLabel}: {object?.title || object?.product_name || "Nội dung không xác định"}</p></div><Button variant="ghost" aria-label="Đóng thông tin bước này" onClick={onClose}><X size={18} aria-hidden="true" /></Button></div>
      {reasonTags.length ? <div className="stack"><small className="hint">{tagTitle}</small><div className="tags">{reasonTags.map(tag => <span className="tag" key={tag.tag_id} title={tag.description}>{tagText(tag.tag_id, tag.description).label}</span>)}</div></div> : null}
      {thoughtTags.length ? <div className="stack"><small className="hint">{isSkip ? "Cảm nhận liên quan" : tagTitle}</small><div className="tags">{thoughtTags.map(tag => <span className="tag" key={tag.tag_id} title={tag.description}>{tagText(tag.tag_id, tag.description).label}</span>)}</div></div> : null}
      {!selectedTags.length && <small className="hint">{isSkip ? "Chưa lưu được lý do cụ thể cho quyết định này." : "Bước này chưa lưu tag cảm xúc."}</small>}
    </div>
  </div>;
}
