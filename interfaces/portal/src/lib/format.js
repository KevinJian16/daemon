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
  if (key === "settling") return "待比较";
  if (key === "closed") return "已冻结";
  if (key === "awaiting_eval") return "待评价";
  if (key === "failed") return "失败";
  if (key === "paused") return "暂停";
  return key || "未开始";
}

export function deedStatusTone(status) {
  const key = String(status || "").toLowerCase();
  if (key === "running") return "bg-[#f3e9d7] text-[#7d4b24]";
  if (key === "settling" || key === "awaiting_eval") return "bg-[#efe4d7] text-[#8a4a26]";
  if (key === "closed") return "bg-[#e7e5dc] text-[#56544e]";
  if (key === "failed") return "bg-[#f3ded8] text-[#8b3c2f]";
  return "bg-[#ece9df] text-[#6b6a68]";
}

export function slipStanceLabel(status) {
  const key = String(status || "").toLowerCase();
  if (key === "archived") return "归档";
  if (key === "active") return "在场";
  return key || "未定";
}

export function shortText(value, limit = 72) {
  const text = String(value || "").trim();
  if (text.length <= limit) return text;
  return `${text.slice(0, limit - 1)}…`;
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
