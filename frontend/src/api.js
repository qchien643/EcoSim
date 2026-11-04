export const API = "/api/v1";
export const id = encodeURIComponent;

export async function request(path, { method = "GET", body, key, signal } = {}) {
  let response;
  try {
    response = await fetch(API + path, {
      method, signal,
      headers: { ...(body ? { "Content-Type": "application/json" } : {}),
        ...(key ? { "Idempotency-Key": key } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error("Không kết nối được máy chủ. Kiểm tra backend và thử lại.");
  }
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : null; } catch {
    throw new Error("Máy chủ không trả JSON hợp lệ. Kiểm tra địa chỉ API.");
  }
  if (!response.ok) {
    const error = new Error(data?.error?.message || `Yêu cầu thất bại (${response.status}).`);
    error.status = response.status;
    error.fields = data?.error?.fields || [];
    throw error;
  }
  return data;
}

export async function all(path, signal) {
  const items = [];
  let after = null;
  do {
    const query = new URLSearchParams({ limit: "200", ...(after ? { after } : {}) });
    const page = await request(`${path}${path.includes("?") ? "&" : "?"}${query}`, { signal });
    items.push(...page.items);
    after = page.next_cursor;
  } while (after);
  return items;
}

export async function downloadConfiguration(runId) {
  const data = await request(`/runs/${id(runId)}/configuration`);
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2) + "\n"], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${runId}.configuration.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
