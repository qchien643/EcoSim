import { useEffect, useRef, useState } from "react";
import { Activity, ArrowRight, BookOpen, CalendarDays, CheckCheck, CircleAlert, LayoutDashboard, Plus, Store, Users } from "lucide-react";
import { all, id, request } from "./api.js";
import { Badge, Button, Dictionary, Empty, ErrorBox, Field, FormIssues, Intro, Link, Modal, Resource, ScheduleTable, TextArea, focusField, useConfirm, useResource, navigate } from "./ui.jsx";
import { Scenario } from "./Scenario.jsx";
import { Run } from "./Run.jsx";
import { sameScenario } from "./model.js";

const steps = [["content", "Doanh nghiệp", BookOpen], ["shop", "Cửa hàng", Store],
  ["schedule", "Bài viết & lịch", CalendarDays], ["participants", "Người tham gia", Users],
  ["review", "Kiểm tra & chạy", CheckCheck]];
const readRoute = () => (location.hash.slice(1) || "/").split("/").filter(Boolean).map(decodeURIComponent);

export function App() {
  const confirm = useConfirm();
  const [route, setRoute] = useState(readRoute);
  const [dictionary, setDictionary] = useState(false);
  const [bundle, setBundle] = useState(null);
  const lastHash = useRef(location.hash);
  const routing = useRef(false);
  useEffect(() => {
    const change = async () => {
      if (location.hash === "#main") { document.getElementById("main")?.focus(); history.replaceState(null, "", lastHash.current || "#/"); return; }
      const target = location.hash;
      const leaving = !sameScenario(lastHash.current, target);
      if (routing.current) { history.replaceState(null, "", lastHash.current || "#/"); return; }
      if (window.ecosimModalDirty || (leaving && window.ecosimDirty)) {
        history.replaceState(null, "", lastHash.current || "#/");
        routing.current = true;
        const accepted = await confirm("Những thay đổi chưa lưu ở màn hình này sẽ bị bỏ. Bạn có muốn rời trang không?", {
          title: "Rời trang khi chưa lưu?", confirmLabel: "Bỏ thay đổi và rời trang", cancelLabel: "Tiếp tục chỉnh sửa",
        });
        routing.current = false;
        if (!accepted) return;
        history.replaceState(null, "", target || "#/");
      }
      if (leaving) window.ecosimDirty = false;
      window.ecosimModalDirty = false;
      lastHash.current = location.hash;
      setRoute(readRoute()); window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, [confirm]);
  const [section, resourceId, tab] = route;
  const isScenario = section === "scenarios";
  return <div className="app-shell">
    <a className="skip-link" href="#main">Đến nội dung chính</a>
    <aside className="sidebar">
      <Link to="/" className="brand"><span className="brand-title">ecoSim<span>.</span></span></Link>
      <nav aria-label="Điều hướng chính">
        <Link to="/" className={`nav-item ${!section ? "is-active" : ""}`}><LayoutDashboard size={16} aria-hidden="true" />Chiến dịch</Link>
        <span className="nav-heading">Các bước chuẩn bị</span>
        {steps.map(([path, label, Icon], index) => isScenario
          ? <Link key={path} to={`/scenarios/${resourceId}/${path}`} className={`nav-item ${tab === path ? "is-active" : ""}`}><Icon size={16} aria-hidden="true" /><span>{label}</span><small>0{index + 1}</small></Link>
          : <span className="nav-item unavailable" key={path}><Icon size={16} aria-hidden="true" /><span>{label}</span></span>)}
        <span className="nav-heading">Theo dõi kết quả</span>
        {section === "runs" ? <>
          <Link to={`/runs/${resourceId}/live`} className={`nav-item ${tab === "live" ? "is-active" : ""}`}><Activity size={16} />Mô phỏng</Link>
          <Link to={`/runs/${resourceId}/results`} className={`nav-item ${tab !== "live" ? "is-active" : ""}`}><CheckCheck size={16} />Kết quả</Link>
        </> : <span className="nav-item unavailable"><Activity size={16} />Mở từ một lần chạy</span>}
      </nav>
      <div className="sidebar-bottom"><p>Thử ý tưởng quảng cáo.<br />Hiểu thêm khách hàng.</p><small>Dùng trong môi trường nội bộ.</small></div>
    </aside>
    <main id="main" className="main" tabIndex={-1}>
      <header className="topbar"><Breadcrumb section={section} resourceId={resourceId} tab={tab} isScenario={isScenario} />
        <Button variant="ghost" onClick={() => setDictionary(true)} aria-label="Mở từ điển đặc điểm và cảm xúc"><CircleAlert size={16} aria-hidden="true" />Giải thích đặc điểm</Button>
      </header>
      <div className="page-stack">
        {!section && <Home />}
        {section === "campaigns" && <Campaign key={resourceId} campaignId={resourceId} />}
        {isScenario && <Scenario key={resourceId} scenarioId={resourceId} tab={tab || "content"} onBundle={setBundle} />}
        {section === "runs" && <Run key={resourceId} runId={resourceId} tab={tab || "live"} detailId={route[3]} onBundle={setBundle} />}
        {section && !["campaigns", "scenarios", "runs"].includes(section) && <Intro title="Không tìm thấy màn hình"><Link to="/">Về trang đầu</Link></Intro>}
      </div>
      <footer>Kết quả mô phỏng hỗ trợ quyết định, không bảo đảm hành vi trong thực tế.</footer>
    </main>
    {dictionary && <Dictionary registry={bundle?.tag_registry} onClose={() => setDictionary(false)} />}
  </div>;
}

function Breadcrumb({ section, resourceId, tab, isScenario }) {
  if (section === "runs" && resourceId) return <RunBreadcrumb runId={resourceId} tab={tab || "live"} />;
  return <div className="breadcrumb"><Link to="/">Không gian làm việc</Link><span>/</span><span>{isScenario ? "Kịch bản" : section === "campaigns" ? "Chiến dịch" : "Không gian làm việc"}</span></div>;
}

function RunBreadcrumb({ runId, tab }) {
  const resource = useResource(async signal => {
    const config = await request(`/runs/${id(runId)}/configuration`, { signal });
    const snapshot = config.input_snapshot || {};
    return { campaign: snapshot.campaign, campaignId: snapshot.campaign_id, setup: snapshot.setup };
  }, [runId]);
  const tabLabels = { live: "Diễn biến", results: "Kết quả", config: "Cấu hình", articles: "Bài viết", shop: "Cửa hàng", agents: "Người tham gia" };
  if (resource.loading || resource.error) {
    return <div className="breadcrumb"><Link to="/">Chiến dịch</Link><span>/</span><span>Lần mô phỏng · {runId}</span><span>/</span><span>{tabLabels[tab] || "Đang xem"}</span></div>;
  }
  const campaignName = resource.data.campaign?.name || "Chiến dịch";
  const campaignId = resource.data.campaignId;
  const scenarioName = resource.data.setup?.name || "Kịch bản";
  return <div className="breadcrumb">
    <Link to="/">Chiến dịch</Link><span>/</span>{campaignId
      ? <Link to={`/campaigns/${id(campaignId)}`} title={campaignName}>{campaignName}</Link>
      : <span title={campaignName}>{campaignName}</span>}
    <span>/</span><span title={scenarioName}>{scenarioName}</span>
    <span>/</span><span>Lần mô phỏng · <code>{runId}</code></span>
    <span>/</span><span>{tabLabels[tab] || "Đang xem"}</span>
  </div>;
}

function Home() {
  const campaigns = useResource(signal => all("/campaigns", signal), []);
  const [creating, setCreating] = useState(false);
  const [usingTemplate, setUsingTemplate] = useState(false);
  return <>
    <section className="hero">
      <h1>Thử quảng cáo.<br /><span>Hiểu thêm khách hàng.</span></h1>
      <div className="hero-bottom"><p>Bạn chuẩn bị mở quán hoặc ra mắt sản phẩm? Thử bài quảng cáo và gian hàng với khách hàng ảo trước. Chọn mẫu có sẵn nếu bạn chưa biết bắt đầu từ đâu.</p>
        <div className="toolbar"><Button variant="primary" onClick={() => setCreating(true)}><Plus size={16} />Tạo chiến dịch</Button>
          <Button variant="outline" onClick={() => setUsingTemplate(true)}>Tạo từ mẫu</Button></div></div>
      <div className="flow-strip" aria-label="Luồng mô phỏng">{["Chú ý", "Đọc & cảm nhận", "Ghé cửa hàng", "Quyết định mua"].map((text, i) => <span key={text}><small>0{i + 1}</small>{text}{i < 3 && <ArrowRight size={16} aria-hidden="true" />}</span>)}</div>
    </section>
    <section><div className="section-heading"><h2>Chiến dịch của bạn</h2></div>
      <Resource resource={campaigns}>{items => items.length ? <div className="campaign-grid">{items.map(c =>
        <Link className="campaign-card" to={`/campaigns/${c.campaign_id}`} key={c.campaign_id}>
          <h3>{c.campaign.name}</h3><p>{c.campaign.brief}</p><span className="card-link">Mở chiến dịch <ArrowRight size={16} aria-hidden="true" /></span>
        </Link>)}</div> : <div className="empty-panel"><h3>Chiến dịch đầu tiên bắt đầu từ đây.</h3><p>Chuẩn bị thông điệp, cửa hàng và những bài quảng cáo bạn muốn thử.</p></div>}</Resource>
    </section>
    {creating && <Modal title="Tạo chiến dịch" onClose={() => setCreating(false)}><CampaignForm onSaved={c => navigate(`/campaigns/${c.campaign_id}`)} /></Modal>}
    {usingTemplate && <TemplatePicker onClose={() => setUsingTemplate(false)} />}
  </>;
}

function TemplatePicker({ onClose }) {
  const templates = useResource(signal => request("/scenario-templates", { signal }), []);
  const [selected, setSelected] = useState("");
  const detail = useResource(signal => selected ? request(`/scenario-templates/${id(selected)}`, { signal }) : Promise.resolve(null), [selected]);
  const [busy, setBusy] = useState(false);
  return <Modal title="Tạo chiến dịch từ mẫu" onClose={() => { if (!busy) onClose(); }}>
    <div className="stack">
      <p>Mẫu có sẵn thông tin cửa hàng, sản phẩm và bài quảng cáo hư cấu. Bạn có thể sửa lại theo ý mình. Tạo bản nháp chưa bắt đầu mô phỏng và chưa phát sinh chi phí mô hình.</p>
      <Resource resource={templates}>{items => items.length ? <Field label="Chọn mẫu chiến dịch"><select disabled={busy} value={selected} onChange={e => setSelected(e.target.value)}>
        <option value="">Chọn bộ dữ liệu mẫu</option>{items.map(t => <option key={t.template_id} value={t.template_id}>{t.name} · {t.agent_count} người · {t.session_count} phiên</option>)}
      </select></Field> : <Empty title="Chưa có mẫu">Máy chủ chưa cung cấp bộ dữ liệu mẫu.</Empty>}</Resource>
      {selected && <Resource resource={detail}>{template => template && <TemplateForm key={template.template_id} template={template} onBusy={setBusy} />}</Resource>}
    </div>
  </Modal>;
}

function TemplateForm({ template, onBusy }) {
  const [campaign, setCampaign] = useState(() => ({ ...template.campaign }));
  const [scenarioName, setScenarioName] = useState(template.setup.name);
  const [busy, setBusy] = useState(false), [error, setError] = useState(null);
  const command = useRef(null), inFlight = useRef(false);
  async function create(event) {
    event.preventDefault();
    if (inFlight.current) return;
    const payload = { campaign, scenario_name: scenarioName };
    const signature = JSON.stringify(payload);
    if (!command.current || command.current.signature !== signature)
      command.current = { signature, key: crypto.randomUUID() };
    inFlight.current = true; setBusy(true); onBusy(true); setError(null);
    try {
      const result = await request(`/scenario-templates/${id(template.template_id)}/instantiate`, {
        method: "POST", body: payload, key: command.current.key,
      });
      navigate(`/scenarios/${result.scenario_id}/content`);
    } catch (e) { setError(e); }
    finally { inFlight.current = false; setBusy(false); onBusy(false); }
  }
  return <FormIssues.Provider value={error?.fields || []}><form className="stack" onSubmit={create} aria-busy={busy}>
    <p>{template.description}</p>
    <div className="counters"><span>{template.setup.agent_count} người</span><span>{template.setup.sessions.length} phiên</span>
      <span>{template.setup.shops.length} cửa hàng</span><span>{template.setup.posts.length} bài viết</span><span>{template.setup.products.length} sản phẩm</span></div>
    <details><summary>Xem sản phẩm, bài viết và lịch đăng có sẵn</summary>
      <ul>{template.setup.products.map(p => <li key={p.product_id}>{p.product_name} — {p.listed_price}</li>)}</ul>
      <ScheduleTable sessions={template.setup.sessions} posts={template.setup.posts} />
    </details>
    <ErrorBox error={error} onField={info => focusField(info.path)} />
    <fieldset className="editor stack" disabled={busy}>
      <Field path="campaign.name" label="Tên chiến dịch" required value={campaign.name} onChange={e => setCampaign({ ...campaign, name: e.target.value })} />
      <Field path="scenario_name" label="Tên kịch bản" required value={scenarioName} onChange={e => setScenarioName(e.target.value)} />
      <TextArea path="campaign.brief" label="Thông điệp chiến dịch" hint="Thông tin lập kế hoạch, không đưa trực tiếp vào ngữ cảnh người dùng ảo." required value={campaign.brief} onChange={brief => setCampaign({ ...campaign, brief })} />
    </fieldset>
    <p className="hint">Bạn có thể đổi số người tham gia và nội dung ở các bước tiếp theo.</p>
    <Button variant="primary" type="submit" disabled={busy}>{busy ? "Đang tạo bản nháp…" : "Dùng mẫu này"}</Button>
  </form></FormIssues.Provider>;
}

function CampaignForm({ current, onSaved }) {
  const [form, setForm] = useState(current?.campaign || { name: "", brief: "", internal_notes: "" });
  const [busy, setBusy] = useState(false), [error, setError] = useState(null);
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const c = await request(current ? `/campaigns/${id(current.campaign_id)}` : "/campaigns",
        { method: current ? "PUT" : "POST", body: current ? { campaign: form, expected_revision: current.revision } : form });
      onSaved(c);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <FormIssues.Provider value={error?.fields || []}><form onSubmit={save} className="stack"><ErrorBox error={error} onField={info => focusField(info.path.replace(/^campaign\./, ""))} />
    <p>Ghi lại ý tưởng bạn muốn thử. Khách hàng ảo sẽ đọc các bài quảng cáo bạn chuẩn bị ở bước sau, không đọc phần ghi chú này. Hệ thống chưa tự viết bài.</p>
    <Field path="name" label="Bạn muốn đặt tên chiến dịch là gì?" hint="Ví dụ: Giới thiệu quán Mộc sắp khai trương." required maxLength={20000} value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
    <TextArea path="brief" label="Bạn muốn khách hàng biết điều gì?" hint="Ví dụ: Quán có cà phê pha tại chỗ, ít đường và phù hợp để mua mỗi sáng." required value={form.brief} onChange={brief => setForm({ ...form, brief })} />
    <TextArea path="internal_notes" label="Ghi chú nội bộ (không bắt buộc)" value={form.internal_notes} onChange={internal_notes => setForm({ ...form, internal_notes })} />
    <Button variant="primary" type="submit" disabled={busy}>{busy ? "Đang lưu…" : "Lưu chiến dịch"}</Button>
  </form></FormIssues.Provider>;
}

function Campaign({ campaignId }) {
  const resource = useResource(async signal => {
    const [campaign, scenarios] = await Promise.all([request(`/campaigns/${id(campaignId)}`, { signal }), all(`/campaigns/${id(campaignId)}/scenarios`, signal)]);
    return { campaign, scenarios };
  }, [campaignId]);
  const [editing, setEditing] = useState(false), [creating, setCreating] = useState(false);
  const [name, setName] = useState(""), [error, setError] = useState(null), [busy, setBusy] = useState(false);
  async function create(event) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const s = await request(`/campaigns/${id(campaignId)}/scenarios`, { method: "POST", body: { name } });
      navigate(`/scenarios/${s.scenario_id}/content`);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return <Resource resource={resource}>{({ campaign, scenarios }) => <>
    <Intro eyebrow="CHIẾN DỊCH" title={campaign.campaign.name} action={<Button variant="outline" onClick={() => setEditing(true)}>Sửa thông điệp</Button>}>{campaign.campaign.brief}</Intro>
    <div className="section-heading"><div><h2>Các kịch bản</h2><p>Cùng một thông điệp. Nhiều cấu hình để thử nghiệm.</p></div><Button variant="primary" onClick={() => setCreating(true)}><Plus size={16} />Tạo kịch bản</Button></div>
    {!scenarios.length && <div className="empty-panel"><h3>Chưa có kịch bản</h3><p>Thêm sản phẩm, bài viết, lịch đăng và người tham gia trong kịch bản mới.</p></div>}
    {scenarios.map(s => <ScenarioCard key={s.scenario_id} scenario={s} />)}
    {editing && <Modal title="Sửa thông điệp chiến dịch" onClose={() => setEditing(false)}><p>Thay đổi không làm đổi các kịch bản đã chốt.</p><CampaignForm current={campaign} onSaved={() => { setEditing(false); resource.reload(); }} /></Modal>}
    {creating && <Modal title="Tạo kịch bản" onClose={() => setCreating(false)}><form className="stack" onSubmit={create}><ErrorBox error={error} /><Field label="Tên kịch bản" required value={name} onChange={e => setName(e.target.value)} /><Button variant="primary" disabled={busy} type="submit">Tạo bản nháp</Button></form></Modal>}
  </>}</Resource>;
}
function ScenarioCard({ scenario }) {
  const runs = useResource(signal => all(`/scenarios/${id(scenario.scenario_id)}/runs`, signal), [scenario.scenario_id]);
  return <article className="card"><div className="section-heading"><div><Badge status={scenario.status} /><h3>{scenario.setup.name}</h3></div><Link className="button button-outline" to={`/scenarios/${scenario.scenario_id}/content`}>Mở kịch bản <ArrowRight size={16} /></Link></div>
    <Resource resource={runs}>{items => items.length ? <div className="run-list">{items.map(r => <Link to={`/runs/${r.run_id}/${r.status === "completed" ? "results" : "live"}`} key={r.run_id}><code>{r.run_id}</code><Badge status={r.status} /><ArrowRight size={16} /></Link>)}</div> : <p>Chưa có lần chạy nào.</p>}</Resource>
  </article>;
}
