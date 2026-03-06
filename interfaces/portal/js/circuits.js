// ── Circuits page ────────────────────────────────────────
let circuitsCache = [];
let currentCircuitId = null;

function _circuitStatusLabel(status) {
  const s = String(status || "active").toLowerCase();
  if (lang === "zh") {
    if (s === "active") return "active";
    if (s === "paused") return "paused";
    if (s === "cancelled") return "cancelled";
  }
  return s;
}

function showCircuits(selectedId = null) {
  currentCircuitId = selectedId || currentCircuitId;
  document.getElementById("view-compose").style.display = "none";
  document.getElementById("view-detail").style.display = "none";
  document.getElementById("view-circuits").style.display = "flex";
  renderCircuitsPage();
}

async function renderCircuitsPage() {
  const tbody = document.getElementById("circuits-table-body");
  if (!tbody) return;
  try {
    circuitsCache = await api("/circuits");
  } catch (e) {
    circuitsCache = [];
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--red)">Error: ${esc(e.message || e)}</td></tr>`;
    return;
  }
  const rows = Array.isArray(circuitsCache) ? circuitsCache : [];
  document.getElementById("cir-count").textContent = `${rows.length}`;
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:var(--muted)">${t("none")}</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((c) => {
    const id = String(c.circuit_id || "");
    const status = String(c.status || "active");
    const enabled = c.enabled !== false && status !== "cancelled";
    const runTitle = c.run_title || c.name || id;
    const nextEnabled = enabled ? "false" : "true";
    const nextLabel = enabled ? t("pause") : t("resume");
    const activeClass = currentCircuitId && currentCircuitId === id ? " class='active'" : "";
    return `<tr${activeClass}>
      <td>${esc(runTitle)}</td>
      <td style="font-family:var(--mono);color:var(--muted)">${esc(String(c.cron || ""))}</td>
      <td><span class="sbadge ${status === "active" ? "s-running" : status === "paused" ? "s-pending_review" : "s-cancelled"}">${esc(_circuitStatusLabel(status))}</span></td>
      <td style="color:var(--muted)">${c.last_triggered_utc ? esc(relTime(c.last_triggered_utc)) : "—"}</td>
      <td style="color:var(--muted)">${Number(c.run_count || 0)}</td>
      <td class="cir-actions">
        <button class="btn btn-ghost btn-sm" onclick="toggleCircuit('${id}', ${nextEnabled})">${esc(nextLabel)}</button>
        <button class="btn btn-ghost btn-sm" onclick="triggerCircuit('${id}')">${lang === "zh" ? "立即触发" : "Trigger"}</button>
        <button class="btn btn-danger btn-sm" onclick="deleteCircuit('${id}')">${lang === "zh" ? "删除" : "Delete"}</button>
      </td>
    </tr>`;
  }).join("");
}

async function toggleCircuit(circuitId, enable) {
  try {
    await api(`/circuits/${encodeURIComponent(circuitId)}`, {
      method: "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({enabled: !!enable}),
    });
    await Promise.all([renderCircuitsPage(), renderNav()]);
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function triggerCircuit(circuitId) {
  try {
    await api(`/circuits/${encodeURIComponent(circuitId)}/trigger`, {method: "POST"});
    await Promise.all([renderCircuitsPage(), renderNav()]);
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}

async function deleteCircuit(circuitId) {
  if (!confirm(lang === "zh" ? "确认删除这个 Circuit？" : "Delete this circuit?")) return;
  try {
    await api(`/circuits/${encodeURIComponent(circuitId)}`, {method: "DELETE"});
    if (currentCircuitId === circuitId) currentCircuitId = null;
    await Promise.all([renderCircuitsPage(), renderNav()]);
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
}
