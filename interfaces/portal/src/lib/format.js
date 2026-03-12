export function cx(...values) {
  return values.filter(Boolean).join(" ");
}

export function formatDateTime(value) {
  if (!value) return "未记时";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未记时";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatChatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function deedStatusLabel(status) {
  const key = String(status || "").toLowerCase();
  if (key === "running") return "执行中";
  if (key === "settling") return "待收束";
  if (key === "closed") return "已关闭";
  if (key === "failed") return "失败";
  if (key === "paused") return "已暂停";
  return key || "未开始";
}

export function deedStatusTone(status) {
  const key = String(status || "").toLowerCase();
  if (key === "running") return "bg-[#f3e9d7] text-[#7d4b24]";
  if (key === "settling") return "bg-[#efe4d7] text-[#8a4a26]";
  if (key === "closed") return "bg-[#e7e5dc] text-[#56544e]";
  if (key === "failed") return "bg-[#f3ded8] text-[#8b3c2f]";
  return "bg-[#ece9df] text-[#6b6a68]";
}

export function deedSubStatusLabel(status) {
  const key = String(status || "").toLowerCase();
  if (key === "queued") return "排队中";
  if (key === "executing") return "执行中";
  if (key === "paused") return "已暂停";
  if (key === "retrying") return "重试中";
  if (key === "reviewing") return "待收束";
  if (key === "succeeded") return "已完成";
  if (key === "failed") return "失败";
  if (key === "cancelled") return "已取消";
  if (key === "timed_out") return "已超时";
  return "";
}

export function slipStanceLabel(status) {
  const key = String(status || "").toLowerCase();
  if (key === "archived") return "归档";
  if (key === "active") return "在场";
  return key || "未定";
}

export function triggerTypeLabel(triggerType) {
  const key = String(triggerType || "").toLowerCase();
  if (key === "manual") return "手动";
  if (key === "timer") return "定时";
  if (key === "writ_chain") return "前序";
  return key || "未定";
}

export function slipStateDot(status) {
  const key = String(status || "").toLowerCase();
  if (key === "running") return "bg-[#ae5630]";
  if (key === "settling") return "bg-[#8a4a26]";
  if (key === "closed") return "bg-[#686868]";
  if (key === "failed") return "bg-[#8b3c2f]";
  return "bg-[#adadad]";
}

export function shortText(value, limit = 72) {
  const text = String(value || "").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit - 1)}…`;
}

export function normalizeDag(dag, plan = null) {
  if (Array.isArray(dag?.nodes)) {
    return {
      nodes: dag.nodes.map((node, index) => ({
        id: String(node?.id || `move_${index + 1}`),
        label: String(node?.label || node?.title || `步骤 ${index + 1}`),
        agent: String(node?.agent || ""),
        status: String(node?.status || "pending").toLowerCase(),
      })),
      edges: Array.isArray(dag?.edges)
        ? dag.edges
            .filter((edge) => edge && typeof edge === "object")
            .map((edge) => ({ from: String(edge.from || ""), to: String(edge.to || "") }))
            .filter((edge) => edge.from && edge.to)
        : [],
    };
  }

  const sourceTimeline = Array.isArray(plan?.timeline)
    ? plan.timeline
    : Array.isArray(plan?.plan_display?.timeline)
      ? plan.plan_display.timeline
      : Array.isArray(plan?.moves)
        ? plan.moves
        : [];

  const nodes = sourceTimeline
    .filter((item) => item && typeof item === "object")
    .map((item, index) => ({
      id: String(item.id || `move_${index + 1}`),
      label: String(item.label || item.instruction || item.message || item.title || `步骤 ${index + 1}`),
      agent: String(item.agent || item.role || ""),
      status: String(item.status || "pending").toLowerCase(),
    }));
  const edges = nodes.slice(1).map((node, index) => ({ from: nodes[index].id, to: node.id }));
  return { nodes, edges };
}

export function firstAvailableTarget(sidebar) {
  const recentSlip = sidebar?.live?.[0] || sidebar?.pending?.[0] || sidebar?.recent?.[0];
  if (recentSlip?.slug) {
    return `/slips/${encodeURIComponent(recentSlip.slug)}`;
  }
  if (sidebar?.folios?.[0]?.slug) {
    return `/folios/${encodeURIComponent(sidebar.folios[0].slug)}`;
  }
  return null;
}
