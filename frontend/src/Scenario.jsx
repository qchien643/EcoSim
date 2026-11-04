import { useEffect, useId, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Plus, Save, Search, Trash2 } from "lucide-react";
import { all, id, request } from "./api.js";
import { articleExcerpt, draftPayload, format, initialSetup, moveScheduled, newId, relationOptions, saveCatalogProduct, toggleScheduled, toggleDefaultTag } from "./model.js";
import { Badge, Button, Empty, ErrorBox, Field, FormIssues, Intro, Link, Modal, Persona, Resource, ScheduleTable, TextArea, focusField, navigate, useConfirm, useModalDraft, useResource } from "./ui.jsx";
import { groupLabels, matchesTag, tagText } from "./copy.js";
import tagDefaultsText from "./config/tag-defaults.yaml?raw";
import simulationDefaultsText from "./config/simulation-defaults.yaml?raw";

// ponytail: YAML uses its JSON-compatible syntax; add a YAML parser only if block syntax is needed.
const tagDefaults = JSON.parse(tagDefaultsText);
const simulationDefaults = JSON.parse(simulationDefaultsText);

export function Scenario({ scenarioId, tab, onBundle }) {
  const resource = useResource(async signal => {
    const [scenario, industries, cohorts] = await Promise.all([
      request(`/scenarios/${id(scenarioId)}`, { signal }), request("/industries", { signal }), all("/cohorts", signal),
    ]);
    return { scenario, industries, cohorts };
  }, [scenarioId]);
  return <Resource resource={resource}>{data => <Editor key={`${scenarioId}-${data.scenario.revision}`} {...data} tab={tab} onBundle={onBundle} />}</Resource>;
}

function Editor({ scenario, industries, cohorts, tab, onBundle }) {
  const confirm = useConfirm();
  const [saved, setSaved] = useState(scenario);
  const [setup, setSetup] = useState(() => initialSetup(scenario.setup));
  const [dirty, setDirty] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState(null);
  const [notice, setNotice] = useState(""), [validation, setValidation] = useState(null), [people, setPeople] = useState(null);
  const [execution] = useState(simulationDefaults.execution);
  const commandKey = useRef(null);
  const pendingField = useRef(null);
  const [articleIssue, setArticleIssue] = useState(null);
  const [catalogIssue, setCatalogIssue] = useState(null);
  useEffect(() => {
    if (pendingField.current && focusField(pendingField.current)) pendingField.current = null;
  }, [tab]);
  function goToIssue(info) {
    if (info.tab === "schedule") setArticleIssue({ path: info.path });
    if (info.tab === "shop") setCatalogIssue({ path: info.path });
    if (info.tab === tab) focusField(info.path);
    else { pendingField.current = info.path; navigate(`/scenarios/${saved.scenario_id}/${info.tab}`); }
  }
  const bundle = useResource(signal => setup.industry_id && setup.profile_version
    ? request(`/industries/${id(setup.industry_id)}/profiles/${id(setup.profile_version)}`, { signal }) : Promise.resolve(null),
  [setup.industry_id, setup.profile_version]);
  const locked = saved.status !== "draft";
  useEffect(() => { onBundle(bundle.data); }, [bundle.data, onBundle]);
  useEffect(() => {
    window.ecosimDirty = dirty;
    const prevent = event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", prevent);
    return () => { window.ecosimDirty = false; window.removeEventListener("beforeunload", prevent); };
  }, [dirty]);

  function edit(patch) {
    setSetup(current => ({ ...current, ...patch })); setDirty(true); setValidation(null); setPeople(null); setNotice("");
  }
  async function save() {
    const result = await request(`/scenarios/${id(saved.scenario_id)}`, { method: "PUT",
      body: { expected_revision: saved.revision, setup: draftPayload(setup) } });
    setSaved(result); setDirty(false); window.ecosimDirty = false; setNotice("Đã lưu bản nháp.");
    return result;
  }
  async function act(fn) {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function validate() {
    const current = dirty ? await save() : saved;
    const report = await request(`/scenarios/${id(current.scenario_id)}/validate`, {
      method: "POST", body: { expected_revision: current.revision } });
    setValidation(report);
    if (report.valid) setPeople(await all(`/scenarios/${id(current.scenario_id)}/participants`));
  }
  async function freeze() {
    if (!await confirm("Sau khi chốt không thể sửa; muốn đổi cần tạo kịch bản mới.", { title: "Chốt kịch bản này?", confirmLabel: "Chốt kịch bản" })) return;
    setSaved(await request(`/scenarios/${id(saved.scenario_id)}/freeze`, {
      method: "POST", body: { expected_revision: saved.revision } }));
    setNotice("Đã chốt. Bạn có thể tạo nhiều lần chạy từ cùng cấu hình.");
  }
  async function createRun() {
    // Keep the same key on transport failure; a retry must not create a second run.
    const signature = JSON.stringify(execution);
    if (!commandKey.current || commandKey.current.signature !== signature)
      commandKey.current = { signature, key: crypto.randomUUID() };
    const run = await request(`/scenarios/${id(saved.scenario_id)}/runs`, { method: "POST",
      key: commandKey.current.key, body: { expected_revision: saved.revision, execution } });
    commandKey.current = null;
    navigate(`/runs/${run.run_id}/live`);
  }
  const matchedCohorts = cohorts.filter(c => c.status === "ready" && c.industry_id === setup.industry_id && c.profile_version === setup.profile_version);
  const currentCohort = matchedCohorts.find(c => c.cohort_id === setup.cohort_id);
  return <FormIssues.Provider value={error?.fields || validation?.issues || []}>
    <Intro title={{ content: "Giới thiệu thương hiệu của bạn", shop: "Chuẩn bị cửa hàng và sản phẩm", schedule: "Chuẩn bị bài viết và lịch đăng", participants: "Chọn khách hàng tham gia", review: "Xem cấu hình lần chạy" }[tab] || setup.name} action={<Badge status={saved.status} />}>
      <Link to={`/campaigns/${saved.campaign_id}`}>Về chiến dịch</Link> · {setup.name}
    </Intro>
    <ErrorBox error={error} onField={goToIssue} /><ErrorBox error={bundle.error} retry={bundle.reload} />
    {notice && <p role="status" className="notice">{notice}</p>}
    <fieldset className="editor" disabled={locked || busy}>
      {tab === "content" && <div className="stack">
        <div className="card form-grid">
          <Field path="name" label="Bạn muốn gọi phương án này là gì?" hint="Ví dụ: Thử giới thiệu món mới. Tên này chỉ để bạn dễ tìm lại." value={setup.name} onChange={e => edit({ name: e.target.value })} />
          <Field path="industry_id" label="Ngành kinh doanh"><select value={`${setup.industry_id || ""}|${setup.profile_version || ""}`} onChange={async e => {
            const [industry_id, profile_version] = e.target.value.split("|");
            if (setup.industry_id && !await confirm("Đổi ngành sẽ xóa các đặc điểm đã chọn và lựa chọn bộ người tham gia.", { title: "Đổi ngành kinh doanh?", confirmLabel: "Đổi ngành" })) return;
            const cleared = { business: { ...setup.business, tags: [] }, shops: setup.shops.map(x => ({ ...x, tags: [] })),
              posts: setup.posts.map(x => ({ ...x, tags: [] })), products: setup.products.map(x => ({ ...x, tags: [] })) };
            edit({ ...cleared, industry_id, profile_version, cohort_id: "", policy_version: "" });
            await act(async () => {
              const next = await request(`/industries/${id(industry_id)}/profiles/${id(profile_version)}`);
              setSetup(s => ({ ...s, policy_version: next.policy.id }));
            });
          }}><option value="|">Chọn ngành đã sẵn sàng</option>{industries.filter(i => i.status === "ready").map(i => <option value={`${i.industry_id}|${i.profile_version}`} key={`${i.industry_id}-${i.profile_version}`}>{i.industry_id === "cafe" ? "Cà phê" : i.name}</option>)}</select></Field>
        </div>
        <section className="card stack" data-field-path="business"><div><h2>Bạn sẽ giới thiệu mình với khách thế nào?</h2><p>Có thể dùng thông tin dự kiến nếu bạn chưa mở cửa hàng. Chỉ viết những điều bạn muốn công khai với khách hàng.</p></div>
          <div className="business-sections">
            <div className="stack">
              <Field path="business.brand_name" label="Tên thương hiệu khách sẽ nhìn thấy" hint="Ví dụ: Cà phê Mộc." value={setup.business.brand_name} onChange={e => edit({ business: { ...setup.business, brand_name: e.target.value } })} />
              <TextArea path="business.brand_description" label="Giới thiệu thương hiệu với khách" hint="Bạn phục vụ ai? Điều gì làm cửa hàng khác biệt?" placeholder="Ví dụ: Mộc phục vụ cà phê pha tại chỗ, có lựa chọn ít đường cho người thích vị nhẹ." value={setup.business.brand_description} onChange={brand_description => edit({ business: { ...setup.business, brand_description } })} />
            </div>
            <div className="stack">
              <Field path="business.organization_name" label="Tên đơn vị kinh doanh đứng sau thương hiệu" hint="Nếu cùng tên với thương hiệu, bạn có thể nhập lại tên đó." value={setup.business.organization_name} onChange={e => edit({ business: { ...setup.business, organization_name: e.target.value } })} />
              <TextArea path="business.organization_description" label="Giới thiệu đơn vị kinh doanh" hint="Đơn vị kinh doanh gì, ở đâu? Không cần thông tin pháp lý hay giấy phép." value={setup.business.organization_description} onChange={organization_description => edit({ business: { ...setup.business, organization_description } })} />
            </div>
          </div>
          <TagEditor path="business.tags" registry={bundle.data?.tag_registry} family="enterprise" preset="business" tags={setup.business.tags}
            sources={[`organization:${setup.business.organization_id}:organization_description`,
              `brand:${setup.business.brand_id}:brand_description`]}
            onChange={tags => edit({ business: { ...setup.business, tags } })} />
        </section>
      </div>}
      {tab === "participants" && <div className="stack"><section className="card stack"><h2>Chọn người tham gia</h2>
        <p>Chọn từ bộ người dùng ảo đã chuẩn bị sẵn. Các nhóm quan hệ với thương hiệu được gán ngẫu nhiên theo cơ cấu bạn nhập, không thay đổi tính cách gốc của từng người.</p>
        <div className="form-grid">
          <Field path="cohort_id" label="Bộ người tham gia có sẵn" hint="Chỉ sử dụng dữ liệu đã chuẩn bị; không cần tải tệp lên."><select value={setup.cohort_id || ""} onChange={e => edit({ cohort_id: e.target.value })}><option value="">Chọn bộ người tham gia</option>{matchedCohorts.map((c, i) => <option key={c.cohort_id} value={c.cohort_id}>{c.industry_id === "cafe" ? "Người dùng ngành cà phê" : "Người dùng ngành đã chọn"} · {c.size} người{matchedCohorts.length > 1 ? ` · Bộ ${i + 1}` : ""}</option>)}</select></Field>
          <Field path="agent_count" label="Số người tham gia" hint={currentCohort ? `Có thể chọn tối đa ${currentCohort.size} người.` : "Chọn bộ dữ liệu trước để biết số người có sẵn."} type="number" min="1" max={currentCohort?.size || 100} value={setup.agent_count} onChange={e => edit({ agent_count: e.target.value === "" ? "" : Number(e.target.value) })} />
        </div>
        <details><summary>Nâng cao: chọn lại cùng người và cách chia nhóm</summary><p>Giữ nguyên hai mã này và cấu hình đầu vào để lặp lại cách chọn người, chia nhóm. Kết quả hành vi mô phỏng vẫn có thể khác.</p><div className="form-grid">
          <Field path="selection_seed" label="Mã chọn người ngẫu nhiên" type="number" min="0" value={setup.selection_seed} onChange={e => edit({ selection_seed: Number(e.target.value) })} />
          <Field path="assignment_seed" label="Mã chia nhóm ngẫu nhiên" type="number" min="0" value={setup.assignment_seed} onChange={e => edit({ assignment_seed: Number(e.target.value) })} />
        </div></details>
      </section><RelationshipGroups setup={setup} edit={edit} validation={validation} /></div>}
    </fieldset>
    {tab === "shop" && <Catalog setup={setup} edit={edit} registry={bundle.data?.tag_registry} locked={locked} busy={busy} issue={catalogIssue} clearIssue={() => setCatalogIssue(null)} />}
    {tab === "schedule" && <Articles setup={setup} edit={edit} registry={bundle.data?.tag_registry} locked={locked} busy={busy} issue={articleIssue} clearIssue={() => setArticleIssue(null)} />}
    {tab === "review" && <section className="card stack"><h2>Kiểm tra trước khi chạy</h2>
      <div className="stat-grid"><Stat label="Người tham gia" value={setup.agent_count} /><Stat label="Phiên" value={setup.sessions.length} /><Stat label="Bài / sản phẩm" value={`${setup.posts.length} / ${setup.products.length}`} /></div>
      <ScheduleTable sessions={setup.sessions} posts={setup.posts} />
      <p>Chốt cấu hình chưa gọi mô hình. Lần chạy chỉ phát sinh chi phí khi bạn bấm “Bắt đầu mô phỏng”.</p>
    </section>}
    {["participants", "review"].includes(tab) && <section className="stack">
      <div className="toolbar"><Button disabled={busy} onClick={() => act(validate)}>Kiểm tra & xem người tham gia</Button>
        {!locked && <Button variant="primary" disabled={busy || dirty || !validation?.valid} onClick={() => act(freeze)}>Chốt kịch bản</Button>}</div>
      {validation && <div className="card"><h3>{validation.valid ? "Cấu hình hợp lệ" : "Cần bổ sung cấu hình"}</h3>
        {validation.issues.length > 0 && <ErrorBox error={{ fields: validation.issues, message: "Cấu hình chưa đầy đủ." }} onField={goToIssue} />}
        {validation.group_counts.length > 0 && <div className="table-wrap"><table><thead><tr><th>Nhóm</th><th>Số người thực tế</th><th>Tỷ lệ thực tế</th></tr></thead><tbody>{validation.group_counts.map(g => <tr key={g.group_id}><td>Nhóm {setup.relationship_groups.findIndex(x => x.group_id === g.group_id) + 1}</td><td>{g.assigned_count}</td><td>{format(g.assigned_percentage)}%</td></tr>)}</tbody></table></div>}
      </div>}
      {people && <section className="stack"><h2>{people.length} người đã chọn</h2>{people.map(p => <Persona person={p} key={p.agent_id} />)}</section>}
    </section>}
    {locked && tab === "review" && <section className="card stack"><h2>Chạy lại với cấu hình này</h2>
      <p className="hint">Lần chạy cũ vẫn được giữ nguyên. Nút này tạo một lần mô phỏng mới từ đúng cấu hình đã chốt; hệ thống sẽ tự chạy song song theo nhóm 4 người.</p>
      <Button variant="primary" disabled={busy} onClick={() => act(createRun)}>Tạo lần mô phỏng mới</Button>
    </section>}
    <div className="save-bar"><span role="status">{locked ? "Đã chốt — chỉ xem, không thể sửa." : dirty ? "Có thay đổi chưa lưu" : "Đã lưu bản nháp"}</span>
      <div className="toolbar">{!locked && <Button variant="outline" disabled={busy || !dirty} onClick={() => act(save)}><Save size={16} />{busy ? "Đang xử lý…" : "Lưu bản nháp"}</Button>}
        {tab !== "review" && <Button variant="primary" disabled={busy} onClick={() => act(async () => {
          if (dirty) await save();
          navigate(`/scenarios/${saved.scenario_id}/${{ content: "shop", shop: "schedule", schedule: "participants", participants: "review" }[tab] || "review"}`);
        })}>{busy ? "Đang xử lý…" : `Tiếp: ${{ content: "Cửa hàng", shop: "Bài viết", schedule: "Khách hàng", participants: "Kiểm tra" }[tab] || "Kiểm tra"}`}</Button>}
      </div>
    </div>
  </FormIssues.Provider>;
}

function TagEditor({ registry, family, preset = family, tags, sources, onChange, path }) {
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const searchId = useId();
  const [defaultError, setDefaultError] = useState("");
  if (!registry) return <p className="hint">Chọn ngành kinh doanh trước để xem các lựa chọn phù hợp.</p>;
  const filtered = registry.tags.filter(t => t.family === family && (matchesTag(t, search) || tags.some(chosen => chosen.tag_id === t.id)));
  return <div className="tag-editor stack" data-field-path={path}>
    <div className="tag-heading"><div><h3>{family === "enterprise" ? "Bạn muốn khách nhớ đến điều gì?" : family === "product" ? "Sản phẩm này có đặc điểm gì?" : "Bài viết này nói gì, kể thế nào?"}</h3>
      <p>Đánh dấu những ý đúng với thông tin bạn vừa viết. Có thể chọn nhiều ý; không cần chọn hết.</p></div>
      <Button variant="ghost" aria-label={searchOpen ? "Ẩn tìm kiếm đặc điểm" : "Tìm đặc điểm"} aria-expanded={searchOpen} aria-controls={searchId}
        onClick={() => { setSearchOpen(!searchOpen); setSearch(""); }}><Search size={20} aria-hidden="true" /></Button>
    </div>
    <div id={searchId} hidden={!searchOpen}>{searchOpen && <Field label="Tìm đặc điểm" placeholder="Nhập từ khóa…" autoFocus value={search} onChange={e => setSearch(e.target.value)} />}</div>
    <small role="status">Đã chọn {tags.length} đặc điểm{search ? " · Các mục đã chọn vẫn hiển thị để bạn kiểm tra." : ""}.</small>
    {defaultError && <p role="alert" className="notice">{defaultError}</p>}
    {[...new Set(filtered.map(t => t.group))].map(group => <fieldset className="tag-group" key={group}>
      <legend>{groupLabels[group] || "Đặc điểm khác"}</legend>
      <div className="tag-choice-grid">{filtered.filter(t => t.group === group).map(tag => {
        const index = tags.findIndex(t => t.tag_id === tag.id);
        const chosen = tags[index];
        const copy = tagText(tag.id, tag.description);
        return <div className={`tag-choice ${chosen ? "is-selected" : ""}`} key={tag.id} data-field-path={chosen && path ? `${path}[${index}]` : undefined}>
          <label className="tag-choice-label"><input type="checkbox" aria-label={copy.label} checked={!!chosen}
            onChange={() => {
              try {
                const next = toggleDefaultTag(tags, tag.id, tagDefaults[preset], sources, registry);
                setDefaultError(""); onChange(next);
              } catch (error) { setDefaultError(error.message); }
            }} />
            <span><strong>{copy.label}</strong><small>{copy.description}</small></span></label>
        </div>;
      })}</div>
    </fieldset>)}
    {!filtered.length && <p>Không tìm thấy. Hãy thử từ khóa khác hoặc xóa từ khóa.</p>}
    {tags.filter(t => !registry.tags.some(r => r.id === t.tag_id && r.family === family)).map(t =>
      <div className="notice" key={t.tag_id}>Đặc điểm không còn thuộc ngành đang chọn: <code>{t.tag_id}</code>
        <Button variant="ghost" onClick={() => onChange(tags.filter(x => x !== t))}>Bỏ đặc điểm không hợp lệ</Button></div>)}
  </div>;
}
function Catalog({ setup, edit, registry, locked, busy, issue, clearIssue }) {
  const confirm = useConfirm();
  const [editor, setEditor] = useState(null);
  const [message, setMessage] = useState("");
  const pendingFocus = useRef(null);
  const changed = editor && JSON.stringify(editor.draft) !== editor.original;
  useModalDraft(changed);
  function open(kind, value, index, isNew = false) {
    setMessage("");
    setEditor({ kind, index, isNew, draft: structuredClone(value), original: JSON.stringify(value) });
  }
  useEffect(() => {
    if (!issue) return;
    const match = issue.path.match(/^(shops|products)\[(\d+)\]/);
    if (match && setup[match[1]][Number(match[2])]) {
      open(match[1], setup[match[1]][Number(match[2])], Number(match[2]));
      pendingFocus.current = issue.path;
    }
    clearIssue();
  }, [issue]);
  useEffect(() => {
    if (editor && pendingFocus.current && focusField(pendingFocus.current)) pendingFocus.current = null;
  }, [editor]);
  async function close() {
    if (!changed || await confirm("Thông tin ngoài danh sách vẫn giữ nguyên. Các thay đổi trong cửa sổ này sẽ không được áp dụng.", {
      title: "Bỏ thay đổi chưa xác nhận?", confirmLabel: "Bỏ thay đổi", cancelLabel: "Tiếp tục chỉnh sửa",
    })) setEditor(null);
  }
  const isShop = editor?.kind === "shops";
  const item = editor?.draft;
  const path = editor ? `${editor.kind}[${editor.index}]` : "";
  const linkedProducts = isShop ? setup.products.filter(p => p.shop_id === item.shop_id).length : 0;
  const linkedPosts = isShop ? setup.posts.filter(p => p.shop_id === item.shop_id).length : 0;
  function patch(value) { setEditor(current => ({ ...current, draft: { ...current.draft, ...value } })); }
  async function apply(event) {
    event.preventDefault();
    if (locked || busy) return;
    const fields = isShop ? ["name", "public_profile"] : ["product_name", "listed_price", "product_description"];
    if (fields.some(key => !item[key].trim()) || (!isShop && !setup.shops.some(s => s.shop_id === item.shop_id))) {
      setMessage("Vui lòng điền đủ thông tin và chọn cửa hàng trước khi xác nhận."); return;
    }
    if (!await confirm("Thay đổi sẽ được áp dụng vào bản nháp. Sau đó bấm “Lưu bản nháp” để lưu lên hệ thống.", {
      title: isShop ? "Áp dụng thông tin cửa hàng?" : "Áp dụng thông tin sản phẩm?", confirmLabel: "Áp dụng thay đổi",
    })) return;
    if (isShop) edit({ shops: editor.isNew ? [...setup.shops, item] : setup.shops.map(s => s.shop_id === item.shop_id ? item : s) });
    else edit({ products: saveCatalogProduct(setup.products, item) });
    setEditor(null); setMessage("Đã áp dụng thay đổi. Bấm “Lưu bản nháp” hoặc “Tiếp” để lưu lên hệ thống.");
  }
  async function remove() {
    if (locked || busy || linkedProducts || linkedPosts) return;
    if (!await confirm("Thao tác này gỡ mục khỏi bản nháp; cần lưu bản nháp để cập nhật lên hệ thống.", {
      title: isShop ? "Xóa cửa hàng này?" : "Xóa sản phẩm này?", confirmLabel: isShop ? "Xóa cửa hàng" : "Xóa sản phẩm",
    })) return;
    const key = isShop ? "shop_id" : "product_id";
    edit({ [editor.kind]: setup[editor.kind].filter(v => v[key] !== item[key]) });
    setEditor(null); setMessage("Đã gỡ khỏi bản nháp. Bấm “Lưu bản nháp” để lưu lên hệ thống.");
  }
  function reorder(products, index, direction) {
    const ordered = moveScheduled(products, index, direction);
    edit({ products: setup.products.map(p => ordered.find(v => v.product_id === p.product_id) || p) });
  }
  return <div className="stack">
    <div className="section-heading"><div><h2>Cửa hàng của bạn</h2><p>Mỗi cửa hàng có một danh sách sản phẩm riêng. Bấm chỉnh sửa để cập nhật thông tin.</p></div>
      {!locked && <Button variant="outline" disabled={busy || setup.shops.length >= 20} onClick={() => open("shops",
        { shop_id: newId("shop"), name: "", public_profile: "", tags: [] }, setup.shops.length, true)}><Plus size={16} aria-hidden="true" />Thêm cửa hàng</Button>}
    </div>
    {message && !editor && <p role="status" className="notice">{message}</p>}
    {!setup.shops.length && <Empty title="Chưa có cửa hàng">Thêm cửa hàng đầu tiên, sau đó thêm những sản phẩm bạn muốn khách lựa chọn.</Empty>}
    {setup.shops.map((shop, i) => {
      const products = setup.products.filter(p => p.shop_id === shop.shop_id).sort((a, b) => a.position - b.position);
      return <section className="card stack catalog-shop" key={shop.shop_id} aria-label={shop.name || `Cửa hàng ${i + 1}`}>
        <div className="section-heading"><div><h3>{shop.name || `Cửa hàng ${i + 1}`}</h3><p className="catalog-preview">{articleExcerpt(shop.public_profile) || "Chưa có giới thiệu cửa hàng."}</p>
          <small>{products.length} sản phẩm · {shop.tags.length} đặc điểm cửa hàng</small></div>
          <Button variant="outline" disabled={busy} onClick={() => open("shops", shop, i)}>{locked ? "Xem cửa hàng" : "Sửa cửa hàng"}</Button>
        </div>
        <div className="section-heading"><div><h4>Sản phẩm trong cửa hàng</h4><p className="hint">Sản phẩm phía trên được giới thiệu trước. Dùng mũi tên để đổi thứ tự.</p></div>
          {!locked && <Button disabled={busy || setup.products.length >= 50} onClick={() => open("products",
            { product_id: newId("product"), shop_id: shop.shop_id, position: 1, product_name: "", listed_price: "", product_description: "", tags: [] },
            setup.products.length, true)}><Plus size={16} aria-hidden="true" />Thêm sản phẩm</Button>}
        </div>
        {!products.length && <p className="empty-panel">Cửa hàng chưa có sản phẩm. Thêm tên, giá và mô tả để khách có thể tìm hiểu.</p>}
        <div className="catalog-products">{products.map((p, n) => <article className="catalog-product" key={p.product_id}>
          <div><h4>{p.product_name || "Sản phẩm chưa đặt tên"}</h4><p className="price">{p.listed_price || "Chưa nhập giá"}</p>
            <p className="catalog-preview">{articleExcerpt(p.product_description) || "Chưa có mô tả sản phẩm."}</p><small>{p.tags.length} đặc điểm</small></div>
          <div className="toolbar">
            {!locked && <div className="catalog-order">
              <Button variant="ghost" aria-label={`Đưa ${p.product_name || "sản phẩm"} lên`} disabled={busy || n === 0} onClick={() => reorder(products, n, -1)}><ArrowUp size={16} aria-hidden="true" /></Button>
              <Button variant="ghost" aria-label={`Đưa ${p.product_name || "sản phẩm"} xuống`} disabled={busy || n === products.length - 1} onClick={() => reorder(products, n, 1)}><ArrowDown size={16} aria-hidden="true" /></Button>
            </div>}
            <Button variant="outline" disabled={busy} aria-label={`${locked ? "Xem" : "Sửa"} sản phẩm ${p.product_name || n + 1}`}
              onClick={() => open("products", p, setup.products.indexOf(p))}>{locked ? "Xem sản phẩm" : "Chỉnh sửa"}</Button>
          </div>
        </article>)}</div>
      </section>;
    })}
    {setup.products.some(p => !setup.shops.some(s => s.shop_id === p.shop_id)) && <section className="card stack"><h3>Sản phẩm cần chọn lại cửa hàng</h3>
      {setup.products.filter(p => !setup.shops.some(s => s.shop_id === p.shop_id)).map(p =>
        <Button key={p.product_id} onClick={() => open("products", p, setup.products.indexOf(p))}>{p.product_name || "Sản phẩm chưa đặt tên"}</Button>)}
    </section>}
    {editor && <Modal title={`${locked ? "Xem" : editor.isNew ? "Thêm" : "Chỉnh sửa"} ${isShop ? "cửa hàng" : "sản phẩm"}`} onClose={close}>
      <form className="stack" onSubmit={apply}>
        <fieldset className="editor stack" disabled={locked || busy}>
          {isShop ? <>
            <Field path={`${path}.name`} label="Tên cửa hàng" required autoFocus placeholder="Ví dụ: Gian hàng Mộc" value={item.name} onChange={e => patch({ name: e.target.value })} />
            <TextArea path={`${path}.public_profile`} label="Giới thiệu cửa hàng với khách" required hint="Bạn bán gì, phục vụ ai, có điều gì đặc biệt?" value={item.public_profile} onChange={public_profile => patch({ public_profile })} />
          </> : <>
            <div className="form-grid">
              <Field path={`${path}.product_name`} label="Tên sản phẩm" required autoFocus placeholder="Ví dụ: Cà phê sữa đá" value={item.product_name} onChange={e => patch({ product_name: e.target.value })} />
              <Field path={`${path}.listed_price`} label="Giá bán" required hint="Nhập cả đơn vị, ví dụ: 35.000 đồng / ly." value={item.listed_price} onChange={e => patch({ listed_price: e.target.value })} />
            </div>
            <Field path={`${path}.shop_id`} label="Bán tại cửa hàng"><select required value={item.shop_id} onChange={e => patch({ shop_id: e.target.value })}>
              {!setup.shops.some(s => s.shop_id === item.shop_id) && <option value="">Chọn cửa hàng</option>}
              {setup.shops.map((s, i) => <option key={s.shop_id} value={s.shop_id}>{s.name || `Cửa hàng ${i + 1}`}</option>)}
            </select></Field>
            <TextArea path={`${path}.product_description`} label="Giới thiệu sản phẩm với khách" required hint="Mô tả nguyên liệu, hương vị, kích cỡ hoặc lựa chọn thêm. Khách đọc phần này khi tìm hiểu kỹ." value={item.product_description} onChange={product_description => patch({ product_description })} />
            <p className="hint">Sản phẩm mới hoặc chuyển cửa hàng được đặt cuối danh sách. Bạn có thể đổi thứ tự bằng mũi tên ngoài danh sách.</p>
          </>}
          <TagEditor path={`${path}.tags`} registry={registry} family={isShop ? "enterprise" : "product"} preset={isShop ? "shop" : "product"}
            tags={item.tags} sources={isShop ? [`shop:${item.shop_id}:public_profile`] :
              ["product_name", "listed_price", "product_description"].map(field => `product:${item.product_id}:${field}`)}
            onChange={tags => patch({ tags })} />
        </fieldset>
        {!editor.isNew && !locked && <div className="stack">
          <Button variant="ghost" disabled={busy || !!(linkedProducts || linkedPosts)} onClick={remove}><Trash2 size={16} aria-hidden="true" />Xóa {isShop ? "cửa hàng" : "sản phẩm"}</Button>
          {!!(linkedProducts || linkedPosts) && <p className="hint">Cửa hàng đang có {linkedProducts} sản phẩm và {linkedPosts} bài viết liên kết. Chuyển hoặc gỡ những mục này trước khi xóa cửa hàng.</p>}
        </div>}
        {message && <p role="status" className="notice">{message}</p>}
        <div className="modal-actions"><p className="hint">{locked ? "Cấu hình đã chốt, chỉ có thể xem." : "Xác nhận để áp dụng vào bản nháp. Sau đó lưu bản nháp trên màn hình chính."}</p>
          <div className="toolbar"><Button variant="outline" onClick={close}>{locked ? "Đóng" : "Hủy"}</Button>
            {!locked && <Button variant="primary" type="submit" disabled={busy || (!changed && !editor.isNew)}>Xác nhận {isShop ? "cửa hàng" : "sản phẩm"}</Button>}
          </div>
        </div>
      </form>
    </Modal>}
  </div>;
}

function Articles({ setup, edit, registry, locked, busy, issue, clearIssue }) {
  const confirm = useConfirm();
  const [editor, setEditor] = useState(null);
  const [sessionIndex, setSessionIndex] = useState(0);
  const [message, setMessage] = useState("");
  const pendingFocus = useRef(null);
  const changed = editor && JSON.stringify(editor.draft) !== editor.original;
  function open(kind, value, index = 0, isNew = false) {
    setMessage("");
    setSessionIndex(index);
    setEditor({ kind, index, isNew, draft: structuredClone(value), original: JSON.stringify(value) });
  }
  useEffect(() => {
    if (!issue) return;
    const match = issue.path.match(/^(posts|sessions)\[(\d+)\]/);
    if (match) {
      const index = Number(match[2]);
      if (match[1] === "posts" && setup.posts[index]) open("post", setup.posts[index], index);
      else if (setup.sessions[index]) open("schedule", setup.sessions, index);
      pendingFocus.current = issue.path;
    }
    clearIssue();
  }, [issue]);
  useEffect(() => {
    if (editor && pendingFocus.current && focusField(pendingFocus.current)) pendingFocus.current = null;
  }, [editor]);
  useModalDraft(changed);
  async function close() {
    if (!changed || await confirm("Bài viết và lịch đăng bên ngoài sẽ giữ nguyên. Các thay đổi trong cửa sổ này sẽ không được áp dụng.", {
      title: "Bỏ thay đổi chưa xác nhận?", confirmLabel: "Bỏ thay đổi", cancelLabel: "Tiếp tục chỉnh sửa",
    })) setEditor(null);
  }
  function patchPost(patch) { setEditor(current => ({ ...current, draft: { ...current.draft, ...patch } })); }
  function patchSession(posts) {
    setEditor(current => ({ ...current, draft: current.draft.map((s, i) => i === sessionIndex ? { ...s, posts } : s) }));
  }
  async function apply(event) {
    event.preventDefault();
    if (locked || busy) return;
    if (editor.kind === "post" && ["title", "preview", "article_content"].some(key => !editor.draft[key].trim())) {
      setMessage("Vui lòng nhập tên, nội dung và thông tin làm căn cứ chọn đặc điểm.");
      return;
    }
    if (!await confirm("Thay đổi sẽ được áp dụng vào bản nháp. Sau đó bấm “Lưu bản nháp” để lưu lên hệ thống.", {
      title: editor.kind === "post" ? "Áp dụng bài viết này?" : "Áp dụng lịch đăng này?", confirmLabel: "Áp dụng thay đổi",
    })) return;
    if (editor.kind === "post") edit({ posts: editor.isNew ? [...setup.posts, editor.draft]
      : setup.posts.map(p => p.post_id === editor.draft.post_id ? editor.draft : p) });
    else edit({ sessions: editor.draft });
    setMessage("Đã áp dụng thay đổi. Bấm “Lưu bản nháp” hoặc “Tiếp” để lưu lên hệ thống.");
    setEditor(null);
  }
  const p = editor?.kind === "post" ? editor.draft : null;
  const s = editor?.kind === "schedule" ? editor.draft[sessionIndex] : null;
  const path = editor?.kind === "post" ? `posts[${editor.index}]` : `sessions[${sessionIndex}]`;
  return <div className="stack">
    <section className="stack" aria-label="Danh sách bài viết">
      <div className="section-heading"><div><h2>Bài viết của bạn</h2><p>Tên và tối đa 100 từ đầu của mỗi bài. Mở một bài để xem hoặc chỉnh sửa.</p></div>
        {!locked && <Button variant="primary" disabled={busy || !setup.shops.length || setup.posts.length >= 50} onClick={() => open("post",
          { post_id: newId("post"), shop_id: setup.shops[0].shop_id, title: "", preview: "", article_content: "", tags: [] }, setup.posts.length, true)}><Plus size={16} aria-hidden="true" />Thêm bài viết</Button>}
      </div>
      {!setup.shops.length && <p>Chuẩn bị ít nhất một cửa hàng trước khi thêm bài viết.</p>}
      {!setup.posts.length && <Empty title="Chưa có bài viết">Bấm “Thêm bài viết” để chuẩn bị bài đầu tiên.</Empty>}
      {setup.posts.map((post, i) => <article className="card article-summary" key={post.post_id}>
        <div><h3>{post.title || `Bài viết ${i + 1}`}</h3><p>{articleExcerpt(post.article_content) || "Chưa có nội dung."}</p></div>
        <Button variant="outline" disabled={busy} aria-label={`${locked ? "Xem" : "Chỉnh sửa"} bài ${post.title || i + 1}`} onClick={() => open("post", post, i)}>{locked ? "Xem bài" : "Chỉnh sửa"}</Button>
      </article>)}
    </section>
    {message && !editor && <p role="status" className="notice">{message}</p>}
    <section className="card stack" aria-label="Lịch đăng theo phiên">
      <div className="section-heading"><div><h2>Lịch đăng theo phiên</h2><p>Mỗi ô là một phiên, không phải ngày hay giờ. Nhấn vào ô để xem bài và thứ tự đăng.</p></div>
        <Button variant="outline" disabled={busy} onClick={() => open("schedule", setup.sessions)}>{locked ? "Xem lịch" : "Chỉnh sửa lịch"}</Button></div>
      <div className="session-grid">{setup.sessions.map((session, i) =>
        <button type="button" key={session.session_no} disabled={busy} className={`session-cell ${session.posts.length ? "has-posts" : ""}`}
          aria-label={`Phiên ${session.session_no}: ${session.posts.length} bài, ${locked ? "xem" : "chỉnh sửa"} lịch`}
          title={`Phiên ${session.session_no} · ${session.posts.length} bài`}
          onClick={() => open("schedule", setup.sessions, i)}>
          <span>Phiên {session.session_no}</span><strong>{session.posts.length}</strong><small>bài đăng</small>
        </button>)}</div>
      <p className="hint">Ô có viền sáng: đã xếp bài · Ô tối: chưa có bài. Một bài có thể đăng ở nhiều phiên.</p>
    </section>
    {editor && <Modal title={p ? (locked ? "Xem bài viết" : editor.isNew ? "Thêm bài viết" : "Chỉnh sửa bài viết") : locked ? "Xem lịch đăng" : "Chỉnh sửa lịch đăng"} onClose={close}>
      <form className="stack" onSubmit={apply}>
        <fieldset className="editor stack" disabled={locked || busy}>
          {p && <>
            <Field path={`${path}.title`} label="Tên bài viết" required autoFocus value={p.title} onChange={e => patchPost({ title: e.target.value })} />
            <Field path={`${path}.shop_id`} label="Bài viết dẫn khách đến cửa hàng nào?"><select required value={p.shop_id} onChange={e => patchPost({ shop_id: e.target.value })}>
              {setup.shops.map((shop, i) => <option value={shop.shop_id} key={shop.shop_id}>{shop.name || `Cửa hàng ${i + 1}`}</option>)}</select></Field>
            <TextArea path={`${path}.article_content`} label="Nội dung đầy đủ của bài viết" required rows={6} hint="Khách hàng ảo nhận nội dung này ở bước đọc bài." value={p.article_content} onChange={article_content => patchPost({ article_content })} />
            <TextArea path={`${path}.preview`} label="Thông tin làm căn cứ chọn đặc điểm trước khi đọc" required hint="Ghi ý thể hiện khi lướt qua quảng cáo. Hệ thống dùng các đặc điểm bạn chọn bên dưới, không gửi nguyên văn đoạn này cho khách hàng ảo." value={p.preview} onChange={preview => patchPost({ preview })} />
            <TagEditor path={`${path}.tags`} registry={registry} family="article" tags={p.tags} sources={[
              `post:${p.post_id}:preview`,
              `post:${p.post_id}:article_content`]} onChange={tags => patchPost({ tags })} />
          </>}
        </fieldset>
        {s && <>
          <Field label="Chọn phiên để xếp bài"><select value={sessionIndex} onChange={e => setSessionIndex(Number(e.target.value))}>
            {editor.draft.map((session, i) => <option value={i} key={session.session_no}>Phiên {session.session_no} · {session.posts.length} bài</option>)}</select></Field>
          <fieldset className="editor stack" disabled={locked || busy}>
            <div className="toolbar">
              <Button disabled={editor.draft.length >= 20} onClick={() => {
                setEditor({ ...editor, draft: [...editor.draft, { session_no: editor.draft.length + 1, posts: [] }] });
                setSessionIndex(editor.draft.length);
              }}><Plus size={16} aria-hidden="true" />Thêm phiên</Button>
              <Button variant="ghost" disabled={editor.draft.length <= 1} onClick={async () => {
                if (!await confirm("Các phiên phía sau sẽ được đánh số lại khi bạn xác nhận lịch.", { title: `Xóa phiên ${s.session_no}?`, confirmLabel: "Xóa phiên" })) return;
                setEditor({ ...editor, draft: editor.draft.filter((_, i) => i !== sessionIndex).map((session, i) => ({ ...session, session_no: i + 1 })) });
                setSessionIndex(Math.max(0, sessionIndex - 1));
              }}>Xóa phiên này</Button>
            </div>
            <fieldset className="tag-group schedule-choices"><legend>Bài đăng trong phiên {s.session_no}</legend>
              {!setup.posts.length && <p>Chưa có bài viết. Bạn có thể để phiên trống và thêm bài sau.</p>}
              {setup.posts.map(post => <label key={post.post_id}><input type="checkbox" checked={s.posts.some(item => item.post_id === post.post_id)}
                onChange={() => patchSession(toggleScheduled(s.posts, post.post_id))} /><span>{post.title || "Bài chưa đặt tên"}</span></label>)}
            </fieldset>
            <div className="stack"><h3>Thứ tự đăng</h3><p className="hint">Bài ở trên đăng trước. Dùng mũi tên để đổi thứ tự.</p>
              {!s.posts.length && <p>Phiên này không đăng bài nào.</p>}
              {[...s.posts].sort((a, b) => a.position - b.position).map((post, n) => <div className="schedule-order" key={post.post_id} data-field-path={`${path}.posts[${s.posts.indexOf(post)}]`}>
                <span>{n + 1}. {setup.posts.find(item => item.post_id === post.post_id)?.title || "Bài không còn trong danh sách"}</span>
                <div className="toolbar">
                  <Button variant="ghost" aria-label={`Đưa bài thứ ${n + 1} lên`} disabled={n === 0} onClick={() => patchSession(moveScheduled(s.posts, n, -1))}><ArrowUp size={16} aria-hidden="true" /></Button>
                  <Button variant="ghost" aria-label={`Đưa bài thứ ${n + 1} xuống`} disabled={n === s.posts.length - 1} onClick={() => patchSession(moveScheduled(s.posts, n, 1))}><ArrowDown size={16} aria-hidden="true" /></Button>
                </div>
              </div>)}
            </div>
          </fieldset>
        </>}
        {p && !editor.isNew && !locked && <Button variant="ghost" disabled={busy} onClick={async () => {
          if (!await confirm("Bài viết sẽ được gỡ khỏi tất cả phiên trong bản nháp.", { title: "Xóa bài viết này?", confirmLabel: "Xóa bài viết" })) return;
          edit({ posts: setup.posts.filter(post => post.post_id !== p.post_id),
            sessions: setup.sessions.map(session => ({ ...session, posts: session.posts.filter(post => post.post_id !== p.post_id) })) });
          setEditor(null); setMessage("Đã gỡ bài khỏi bản nháp và lịch đăng. Bấm “Lưu bản nháp” để lưu lên hệ thống.");
        }}><Trash2 size={16} aria-hidden="true" />Xóa bài viết</Button>}
        {message && <p role="status">{message}</p>}
        <div className="modal-actions"><p className="hint">{locked ? "Cấu hình đã chốt, chỉ có thể xem." : "Xác nhận để áp dụng vào bản nháp. Bạn vẫn cần lưu bản nháp trên màn hình chính."}</p>
          <div className="toolbar"><Button variant="outline" onClick={close}>{locked ? "Đóng" : "Hủy"}</Button>
            {!locked && <Button type="submit" variant="primary" disabled={busy || (!changed && !editor.isNew)}>Xác nhận {p ? "bài viết" : "lịch đăng"}</Button>}</div>
        </div>
      </form>
    </Modal>}
  </div>;
}
function RelationshipGroups({ setup, edit }) {
  const groups = setup.relationship_groups;
  const mode = groups[0]?.percentage != null ? "percentage" : "count";
  const patch = (i, value) => edit({ relationship_groups: groups.map((g, n) => n === i ? { ...g, ...value } : g) });
  const total = groups.reduce((sum, g) => sum + Number(g[mode] || 0), 0);
  const expected = mode === "percentage" ? 100 : setup.agent_count;
  return <section className="card stack" data-field-path="relationship_groups"><h2>Khách hàng bắt đầu như thế nào?</h2><p>Chia người tham gia thành các nhóm không trùng nhau. Mỗi nhóm có mức nhận biết, độ quen thuộc, thiện cảm và lịch sử mua riêng trước khi mô phỏng bắt đầu.</p>
    <Field label="Nhập cơ cấu bằng"><select value={mode} onChange={e => {
      const next = e.target.value;
      edit({ relationship_groups: groups.map(g => ({ group_id: g.group_id, state: g.state,
        [next]: next === "percentage" ? (setup.agent_count ? g.count / setup.agent_count * 100 : 0) : Math.round(g.percentage / 100 * setup.agent_count) })) });
    }}><option value="percentage">Phần trăm (%)</option><option value="count">Số người</option></select></Field>
    <p className="notice" role="status">Đã phân bổ {format(total)} / {format(expected)}{mode === "percentage" ? "%" : " người"}.
      {Math.abs(total - expected) < 0.000001 ? " Đã đủ tổng cơ cấu." : total < expected ? ` Còn thiếu ${format(expected - total)}${mode === "percentage" ? "%" : " người"}.` : ` Đang vượt ${format(total - expected)}${mode === "percentage" ? "%" : " người"}.`}</p>
    {groups.map((g, i) => <div className="group-card stack" key={g.group_id} data-field-path={`relationship_groups[${i}]`}><div className="section-heading"><strong>Nhóm {i + 1}</strong><Button variant="ghost" disabled={groups.length === 1} onClick={() => edit({ relationship_groups: groups.filter(x => x !== g) })}>Xóa nhóm</Button></div>
      <p className="group-summary">{Object.entries(relationOptions).map(([key, options]) => options[g.state[key]]).join(" · ")}</p>
      <div className="inline-form"><Field path={`relationship_groups[${i}].${mode}`} label={mode === "percentage" ? "Tỷ lệ nhóm (%)" : "Số người trong nhóm"} type="number" min="0" max={mode === "percentage" ? 100 : setup.agent_count} step={mode === "percentage" ? "any" : "1"} value={g[mode]} onChange={e => patch(i, { [mode]: e.target.value === "" ? "" : Number(e.target.value) })} />
      <p>{mode === "count" ? `${g.count || 0} người · ${format(setup.agent_count ? g.count / setup.agent_count : null, true)}` : `${format(g.percentage || 0)}% · tương đương ${format(g.percentage / 100 * setup.agent_count)} người trước làm tròn`}</p></div>
      <details><summary>Chỉnh đặc điểm của nhóm {i + 1}</summary>
      <div className="form-grid">{Object.entries(relationOptions).map(([key, options]) => <Field path={`relationship_groups[${i}].state.${key}`} key={key} label={{ awareness: "Đã biết thương hiệu chưa?", familiarity: "Quen thuộc đến mức nào?", attitude: "Có thiện cảm thế nào?", purchase_history: "Đã từng mua chưa?" }[key]}>
        <select value={g.state[key]} onChange={e => {
          const state = { ...g.state, [key]: e.target.value };
          if (key === "awareness" && e.target.value === "unknown") Object.assign(state, { familiarity: "none", attitude: "not_formed", purchase_history: "none" });
          patch(i, { state });
        }} disabled={key !== "awareness" && g.state.awareness === "unknown"}>{Object.entries(options).map(([v, label]) => <option value={v} key={v}>{label}</option>)}</select></Field>)}
      </div>{g.state.awareness === "unknown" && <p className="hint">Người chưa biết thương hiệu bắt đầu ở trạng thái chưa quen, chưa hình thành thái độ và chưa từng mua.</p>}</details>
    </div>)}
    <p>Tỷ lệ và số người đang hiển thị là phần nhập của bạn. Bấm “Kiểm tra & xem người tham gia” để xem số người chính xác sau phân bổ và làm tròn.</p>
    <Button onClick={() => edit({ relationship_groups: [...groups, { group_id: newId("group"), [mode]: 0, state: { awareness: "aware", familiarity: "low", attitude: "neutral", purchase_history: "none" } }] })}>Thêm nhóm</Button>
  </section>;
}
function Stat({ label, value }) { return <div className="stat-card"><span>{label}</span><strong>{value}</strong></div>; }
