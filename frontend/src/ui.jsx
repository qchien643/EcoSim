import { cloneElement, createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AlertCircle, LoaderCircle, X } from "lucide-react";
import { chartSegments, format, statuses, relationOptions } from "./model.js";
import { errorMessage, familyLabels, issueInfo, matchesTag, normalizePath, personaFieldText, personaGroupItems, personaGroups, personaValueText, tagText } from "./copy.js";

export const FormIssues = createContext([]);
export function focusField(path) {
  const normalized = normalizePath(path);
  const nodes = [...document.querySelectorAll("[data-field-path]")];
  const node = nodes.find(n => n.dataset.fieldPath === normalized)
    || nodes.find(n => normalized.startsWith(`${n.dataset.fieldPath}.`) || normalized.startsWith(`${n.dataset.fieldPath}[`));
  if (!node) return false;
  // A failed field may be inside a collapsed customer group or advanced settings.
  for (let parent = node.parentElement; parent; parent = parent.parentElement)
    if (parent.tagName === "DETAILS") parent.open = true;
  const target = node.matches("input, select, textarea") ? node : node.querySelector("input, select, textarea, summary") || node;
  target.focus(); target.scrollIntoView({ block: "center" });
  return true;
}

export function navigate(path) {
  window.location.hash = path;
}
export function Link({ to, children, className = "", ...props }) {
  return <a href={`#${to}`} className={className} {...props} onClick={event => {
    if (!event.ctrlKey && !event.metaKey && !event.shiftKey && event.button === 0) {
      event.preventDefault(); navigate(to);
    }
  }}>{children}</a>;
}
export function Button({ children, variant = "secondary", ...props }) {
  return <button type="button" className={`button button-${variant}`} {...props}>{children}</button>;
}
export function Field({ label, hint, children, wide = false, path, ...props }) {
  const uid = useId();
  const issues = useContext(FormIssues);
  const issue = path && issues.find(i => normalizePath(i.path) === normalizePath(path));
  const describedBy = [hint && `${uid}-hint`, issue && `${uid}-error`].filter(Boolean).join(" ") || undefined;
  const accessibility = { id: uid, "aria-describedby": describedBy, "aria-invalid": issue ? true : undefined };
  return <div className={`field ${wide ? "field-wide" : ""}`} data-field-path={path && normalizePath(path)}>
    <label htmlFor={uid}>{label}</label>
    {children ? cloneElement(children, accessibility) : <input {...props} {...accessibility} />}
    {hint && <small id={`${uid}-hint`}>{hint}</small>}
    {issue && <small className="field-error" id={`${uid}-error`}>{issueInfo(issue).message}</small>}
  </div>;
}
export function TextArea({ label, value, onChange, hint, path, ...props }) {
  return <Field label={label} hint={hint} path={path}><textarea rows={4} value={value || ""} onChange={e => onChange(e.target.value)} {...props} /></Field>;
}
export function Badge({ status }) { return <span className={`badge ${status === "running" ? "accent" : ""}`}>{statuses[status] || status}</span>; }
export function ErrorBox({ error, retry, onField }) {
  const ref = useRef(null);
  useEffect(() => { if (error) ref.current?.focus(); }, [error]);
  return error ? <div className="alert" role="alert" tabIndex={-1} ref={ref}>
    <AlertCircle size={24} aria-hidden="true" /><div><strong>{error.status === 409 ? "Dữ liệu đã thay đổi hoặc thao tác đang bận." : "Chưa thể hoàn tất thao tác."}</strong>
      <p>{errorMessage(error)}</p>
      {error.fields?.length > 0 && <ul>{error.fields.map((f, i) => {
        const info = issueInfo(f);
        return <li key={i}>{onField ? <button type="button" className="error-link" onClick={() => onField(info)}>{info.label} — {info.message}</button> : <span>{info.label} — {info.message}</span>}</li>;
      })}</ul>}
      {retry && <Button onClick={retry}>Thử lại</Button>}
      <details><summary>Chi tiết kỹ thuật</summary><p>{error.message || String(error)}</p>
        {error.fields?.map((f, i) => <p key={i}><code>{f.path}</code> — {f.message}</p>)}
      </details>
    </div>
  </div> : null;
}
export function Loading() { return <div className="empty-panel" role="status"><LoaderCircle size={24} aria-hidden="true" />Đang tải dữ liệu…</div>; }
export function Empty({ title = "Chưa có dữ liệu", children }) { return <div className="empty-panel"><h3>{title}</h3><p>{children}</p></div>; }
export function Intro({ title, children, action }) {
  return <div className="section-heading"><div className="panel-intro"><h1>{title}</h1>{children && <p>{children}</p>}</div>{action}</div>;
}
export function useResource(loader, dependencies) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ data: null, error: null, loading: true });
    Promise.resolve().then(() => loader(controller.signal)).then(data => {
      if (!controller.signal.aborted) setState({ data, error: null, loading: false });
    }).catch(error => {
      if (!controller.signal.aborted) setState({ data: null, error, loading: false });
    });
    return () => controller.abort();
    // Callers explicitly provide the resource identity as dependencies.
  }, [...dependencies, tick]);
  return { ...state, reload: () => setTick(t => t + 1) };
}
export function Resource({ resource, children }) {
  if (resource.loading) return <Loading />;
  if (resource.error) return <ErrorBox error={resource.error} retry={resource.reload} />;
  return children(resource.data);
}
let openModals = 0, bodyOverflow = "";
export function Modal({ title, children, onClose, className = "", ...props }) {
  const ref = useRef(null);
  useEffect(() => {
    const trigger = document.activeElement;
    const dialog = ref.current;
    if (!openModals++) bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.showModal();
    dialog.querySelector("[data-modal-focus]")?.focus();
    return () => {
      dialog.close();
      if (!--openModals) document.body.style.overflow = bodyOverflow;
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return createPortal(<dialog className={`dialog ${className}`} ref={ref} {...props}
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }} aria-label={title}>
    <div className="drawer-head"><h2>{title}</h2><Button variant="ghost" aria-label="Đóng" onClick={onClose}><X size={24} aria-hidden="true" /></Button></div>{children}
  </dialog>, document.body);
}
const Confirmation = createContext(null);
export const useConfirm = () => useContext(Confirmation);
export function ConfirmationProvider({ children }) {
  const [question, setQuestion] = useState(null);
  const pending = useRef(null);
  const descriptionId = useId();
  const confirm = useCallback((message, options = {}) => {
    // Only the foreground question can be answered; never queue destructive actions.
    if (pending.current) return Promise.resolve(false);
    return new Promise(resolve => { pending.current = resolve; setQuestion({ message, ...options }); });
  }, []);
  function answer(value) {
    const resolve = pending.current;
    pending.current = null; setQuestion(null); resolve?.(value);
  }
  useEffect(() => () => { pending.current?.(false); pending.current = null; }, []);
  return <Confirmation.Provider value={confirm}>{children}
    {question && <Modal title={question.title || "Xác nhận thay đổi"} className="confirmation-dialog"
      role="alertdialog" aria-describedby={descriptionId} onClose={() => answer(false)}>
      <p id={descriptionId}>{question.message}</p>
      <div className="modal-actions"><div className="toolbar">
        <Button variant="outline" data-modal-focus onClick={() => answer(false)}>{question.cancelLabel || "Quay lại"}</Button>
        <Button variant="primary" onClick={() => answer(true)}>{question.confirmLabel || "Xác nhận"}</Button>
      </div></div>
    </Modal>}
  </Confirmation.Provider>;
}
export function useModalDraft(changed) {
  useEffect(() => {
    window.ecosimModalDirty = !!changed;
    const prevent = event => { if (changed) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", prevent);
    return () => { window.ecosimModalDirty = false; window.removeEventListener("beforeunload", prevent); };
  }, [changed]);
}
export function Tags({ tags = [], registry }) {
  return <div className="tags">{tags.map(t => {
    const copy = tagText(t.tag_id, t.description || registry?.tags?.find(r => r.id === t.tag_id)?.description);
    return <span className="tag" key={t.tag_id} title={copy.description}>{copy.label}{t.score != null ? ` · ${format(t.score)}` : ""}</span>;
  })}</div>;
}
export function Persona({ person }) {
  const values = person.persona?.persona || {};
  return <details className="persona"><summary>Người {person.ordinal} · Xem hồ sơ khách hàng ảo</summary>
    <p className="persona-relation">{Object.entries(person.initial_relationship).map(([key, val]) => relationOptions[key]?.[val] || val).join(" · ")}</p>
    <p className="hint">Các dòng trên là mối quan hệ ban đầu với thương hiệu. Những mục dưới đây mô tả cách người này chú ý, cân nhắc và lựa chọn.</p>
    <div className="persona-groups">{personaGroups.map(([key, title, fields]) => {
      const items = personaGroupItems(values, fields);
      return items.length ? <section className="persona-group" key={key}><h4>{title}</h4><div className="persona-facts">{items.map(item =>
        <article className="persona-fact" key={item.field}><strong>{item.label}</strong><span>{item.value}</span><small>{item.description}</small>
          {person.persona.field_provenance?.[item.field]?.status === "imputed_prior" && <em>Giá trị bổ sung theo cấu hình MVP</em>}</article>)}</div></section> : null;
    })}</div>
    <details className="persona-technical"><summary>Xem mã kỹ thuật và nguồn dữ liệu</summary>
      <p>Phần này chỉ dành cho đối chiếu dữ liệu, không phải cách hệ thống mô tả người dùng khi mô phỏng.</p>
      <small>Mã tra cứu: <code>{person.agent_id}</code></small>
      <dl>{Object.entries(values).map(([key, val]) => <div key={key}><dt>{personaFieldText(key)[0]} <code>{key}</code></dt><dd>{personaValueText(val)}</dd></div>)}</dl>
    </details>
  </details>;
}
export function ScheduleTable({ sessions, posts }) {
  return <div className="table-wrap"><table><caption>Lịch đăng đã chuẩn bị</caption><thead><tr><th>Phiên</th><th>Thứ tự</th><th>Bài viết</th></tr></thead><tbody>{sessions.map(s => s.posts.length
    ? [...s.posts].sort((a, b) => a.position - b.position).map(p => <tr key={`${s.session_no}-${p.post_id}`}><td>{s.session_no}</td><td>{p.position}</td><td>{posts.find(x => x.post_id === p.post_id)?.title || "Bài viết chưa đặt tên"}</td></tr>)
    : <tr key={s.session_no}><td>{s.session_no}</td><td>—</td><td>Không có bài đăng</td></tr>)}</tbody></table></div>;
}
export function LineChart({ points, definition, cumulative }) {
  cumulative = definition.kind === "state" ? false : cumulative;
  const valueKey = cumulative ? "cumulative_value" : "session_value";
  const { segments, max, sorted } = chartSegments(points, valueKey);
  if (!points.length) return <Empty title="Chưa có phiên hoàn tất">Biểu đồ xuất hiện khi có chỉ số chính thức.</Empty>;
  return <div className="line-chart">
    <svg viewBox="0 0 680 288" role="img" aria-label={`${definition.label_vi}, ${definition.kind === "state" ? "trạng thái cuối mỗi phiên" : cumulative ? "tích lũy đến mỗi phiên" : "riêng từng phiên"}. Bảng giá trị ở bên dưới.`}>
      <text x="8" y="40">{format(max, definition.unit === "ratio")}</text><text x="8" y="240">0</text>
      {segments.map((segment, i) => <polyline key={i} points={segment.map(p => `${p.x},${p.y}`).join(" ")} />)}
      {segments.flat().map((p, i, all) => <circle className={i === all.length - 1 ? "highlight" : ""} key={p.point.session_no} cx={p.x} cy={p.y} r="4"><title>Phiên {p.point.session_no}: {format(p.point[valueKey], definition.unit === "ratio")}</title></circle>)}
      {sorted.map(p => <text key={p.session_no} x={sorted.length === 1 ? 340 : 48 + (p.session_no - sorted[0].session_no) / (sorted.at(-1).session_no - sorted[0].session_no) * 584} y="276" textAnchor="middle">{p.session_no}</text>)}
    </svg><p className="chart-caption">Trục ngang: phiên · {definition.unit === "ratio" ? "Tỷ lệ (%)" : "Số lượt"} · “—” là chưa đủ dữ liệu, không phải 0.</p>
    <details><summary>Xem số liệu từng phiên</summary><div className="table-wrap"><table><thead><tr><th>Phiên</th><th>{definition.kind === "state" ? "Cuối phiên" : cumulative ? "Tích lũy đến phiên" : "Trong phiên"}</th>{definition.unit === "ratio" && <th>Số lượt / tổng lượt làm cơ sở</th>}</tr></thead><tbody>{sorted.map(p => <tr key={p.session_no}><td>{p.session_no}</td><td>{format(p[valueKey], definition.unit === "ratio")}</td>{definition.unit === "ratio" && <td>{format(p[cumulative ? "cumulative_numerator" : "numerator"])} / {format(p[cumulative ? "cumulative_denominator" : "denominator"])}</td>}</tr>)}</tbody></table></div></details>
  </div>;
}
export function Dictionary({ registry, onClose }) {
  const [search, setSearch] = useState("");
  const [family, setFamily] = useState("");
  const tags = registry?.tags.filter(t => (!family || t.family === family) && matchesTag(t, search)) || [];
  return <Modal title="Từ điển đặc điểm & cảm xúc" onClose={onClose}><p>Hiểu các đặc điểm bạn chọn và cảm xúc được ghi nhận trong mô phỏng. Tên tiếng Việt chỉ dùng để hiển thị, không thay đổi định nghĩa gốc.</p>
    <div className="form-grid">
      <Field label="Tìm đặc điểm hoặc cảm xúc" hint="Có thể tìm không dấu, ví dụ: nguyen lieu." value={search} onChange={e => setSearch(e.target.value)} autoFocus />
      <Field label="Nhóm thông tin"><select value={family} onChange={e => setFamily(e.target.value)}><option value="">Tất cả nhóm</option>{Object.entries(familyLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
    </div>
    {!registry ? <Empty>Chọn một ngành trong kịch bản để tải từ điển.</Empty> : <>
      <p role="status">{tags.length} mục phù hợp</p>
      {!tags.length && <Empty title="Không tìm thấy">Thử từ khóa khác hoặc chọn “Tất cả nhóm”.</Empty>}
      <div className="dictionary-list">{tags.map(t => {
        const copy = tagText(t.id, t.description);
        return <article key={t.id}><span className="eyebrow">{familyLabels[t.family]}</span><h3>{copy.label}</h3><p>{copy.description}</p>
          <details><summary>Định nghĩa gốc & mã kỹ thuật</summary><code>{t.id}</code><p>{t.description}</p><small>{t.boundary}</small>{t.example && <p>Ví dụ gốc: {t.example}</p>}</details>
        </article>;
      })}</div>
    </>}
  </Modal>;
}
