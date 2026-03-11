const JSON_HEADERS = {
  "Content-Type": "application/json",
};

function friendlyError(raw) {
  const text = String(raw || "");
  if (!text) return "暂时无法完成这次请求。";
  if (text.includes("404")) return "对象不存在，或者路由还没接上。";
  if (text.includes("message_required")) return "你还没有写下要补充的内容。";
  if (text.includes("slip_not_found") || text.includes("folio_not_found") || text.includes("deed_not_found")) {
    return "对象不存在，或者路由还没接上。";
  }
  if (text.includes("slip_has_no_design")) return "这张签札还没有可供再行的结构。";
  if (text.includes("invalid_stance_target")) return "这个对象动作目前还不支持。";
  if (text.includes("cadence_schedule_required")) return "要启用时钟，先给出一个有效时间。";
  if (text.includes("temporal_unavailable")) return "行事引擎暂时不可用，请稍后再试。";
  if (/(traceback|exception|stack|sqlite|json|errno|workflow|temporal)/i.test(text)) {
    return "后端报错了，但错误信息还不适合直接暴露在页面上。";
  }
  return text.replace(/^Error:\s*/i, "").replace(/^"|"$/g, "").trim() || "暂时无法完成这次请求。";
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(friendlyError(text || response.statusText));
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

export function getSidebar() {
  return request("/portal-api/sidebar");
}

export function getSlip(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}`);
}

export function getSlipMessages(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/messages`);
}

export function getSlipResultFiles(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/result/files`);
}

export function sendSlipMessage(slug, text) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/message`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ text }),
  });
}

export function rerunSlip(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/rerun`, {
    method: "POST",
  });
}

export function copySlip(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/copy`, {
    method: "POST",
  });
}

export function takeOutSlip(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/take-out`, {
    method: "POST",
  });
}

export function updateSlipStance(slug, target) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/stance`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ target }),
  });
}

export function setSlipCadence(slug, schedule, enabled = true) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/cadence`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ schedule, enabled }),
  });
}

export function deleteSlipCadence(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/cadence`, {
    method: "DELETE",
  });
}

export function getFolio(slug) {
  return request(`/portal-api/folios/${encodeURIComponent(slug)}`);
}

export function reorderFolio(slug, slipIds) {
  return request(`/portal-api/folios/${encodeURIComponent(slug)}/reorder`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ slip_ids: slipIds }),
  });
}
