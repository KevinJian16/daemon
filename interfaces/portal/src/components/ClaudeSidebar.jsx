import { ChevronLeft, ChevronRight, MoreHorizontal, Search, Sparkles, SquarePen } from "lucide-react";
import { Link } from "react-router-dom";
import { cx, deedStatusLabel, shortText, slipStanceLabel } from "../lib/format";

function SidebarItem({ to, title, subtitle, active, collapsed, meta }) {
  return (
    <Link
      to={to}
      className={cx(
        "group flex items-start gap-3 rounded-2xl px-3 py-2.5 transition-colors",
        active ? "bg-[#DDD9CE]" : "hover:bg-[#E5E2D8]",
      )}
    >
      <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#c8c2b3]" />
      {collapsed ? null : (
        <>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-[#1a1a18]">{title}</div>
            {subtitle ? <div className="mt-0.5 truncate text-xs text-[#6b6a68]">{subtitle}</div> : null}
            {meta ? <div className="mt-1 text-[11px] text-[#9a9893]">{meta}</div> : null}
          </div>
          <button type="button" disabled className="mt-0.5 opacity-0 transition group-hover:opacity-100">
            <MoreHorizontal width={16} height={16} className="text-[#8d8b84]" />
          </button>
        </>
      )}
    </Link>
  );
}

function SidebarSection({ title, children, collapsed }) {
  if (!children.length) return null;
  return (
    <section className="mt-6">
      {collapsed ? null : <div className="mb-2 px-3 text-[11px] font-medium uppercase tracking-[0.16em] text-[#8d8b84]">{title}</div>}
      <div className="space-y-1">{children}</div>
    </section>
  );
}

export default function ClaudeSidebar({
  sidebar,
  loading,
  error,
  collapsed,
  onToggleCollapse,
  search,
  onSearchChange,
  pathname,
}) {
  const normalizedSearch = String(search || "").trim().toLowerCase();
  const filterItems = (items, type) =>
    (items || []).filter((item) => {
      if (!normalizedSearch) return true;
      const haystack = [item.title, item.summary, item.objective, item.slug, item.status].join(" ").toLowerCase();
      return haystack.includes(normalizedSearch);
    }).map((item) => {
      if (type === "folio") {
        return {
          key: item.id,
          to: `/folios/${encodeURIComponent(item.slug)}`,
          title: item.title,
          subtitle: shortText(item.summary || `${item.slip_count || 0} 张签札`, 38),
          meta: `${item.slip_count || 0} 张签札 · ${item.writ_count || 0} 道成文`,
        };
      }
      return {
        key: item.id,
        to: `/slips/${encodeURIComponent(item.slug)}`,
        title: item.title,
        subtitle: shortText(item.objective || item.summary, 38),
        meta: `${slipStanceLabel(item.stance)} · ${deedStatusLabel(item.deed?.status)}`,
      };
    });

  const reviewItems = filterItems(sidebar?.pending, "slip");
  const liveItems = filterItems(sidebar?.live, "slip");
  const folioItems = filterItems(sidebar?.folios, "folio");
  const recentItems = filterItems(sidebar?.recent, "slip");

  return (
    <aside
      className={cx(
        "h-full shrink-0 border-r border-[rgba(0,0,0,0.06)] bg-[#ECEBE4] transition-all duration-300",
        collapsed ? "w-[78px]" : "w-[306px]",
      )}
    >
      <div className="flex h-full flex-col">
        <div className="border-b border-[rgba(0,0,0,0.05)] px-3 pb-4 pt-4">
          <div className={cx("flex items-center justify-between gap-2", collapsed && "justify-center")}>
            {collapsed ? null : (
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Portal</div>
                <div className="mt-1 text-[15px] font-medium text-[#1a1a18]">Daemon</div>
              </div>
            )}
            <button
              type="button"
              onClick={onToggleCollapse}
              className="flex h-8 w-8 items-center justify-center rounded-xl text-[#6b6a68] transition hover:bg-[#E5E2D8] hover:text-[#1a1a18]"
            >
              {collapsed ? <ChevronRight width={16} height={16} /> : <ChevronLeft width={16} height={16} />}
            </button>
          </div>

          <div className={cx("mt-4 flex items-center gap-2", collapsed && "flex-col")}>
            <button
              type="button"
              disabled
              title="新建对象后端未接入"
              className="flex h-9 min-w-0 flex-1 items-center justify-center gap-2 rounded-2xl border border-[rgba(0,0,0,0.08)] bg-white/80 px-3 text-sm font-medium text-[#1a1a18] shadow-sm disabled:cursor-not-allowed disabled:opacity-70"
            >
              <SquarePen width={16} height={16} />
              {collapsed ? null : <span>新建</span>}
            </button>
            <button
              type="button"
              disabled
              title="系统搜索后端未接入"
              className="flex h-9 w-9 items-center justify-center rounded-2xl border border-[rgba(0,0,0,0.08)] bg-white/80 text-[#6b6a68] shadow-sm disabled:cursor-not-allowed"
            >
              <Sparkles width={16} height={16} />
            </button>
          </div>

          {collapsed ? null : (
            <label className="mt-4 flex items-center gap-2 rounded-2xl border border-[rgba(0,0,0,0.06)] bg-white/70 px-3 py-2 shadow-sm">
              <Search width={15} height={15} className="text-[#8d8b84]" />
              <input
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder="Search Portal"
                className="w-full border-none bg-transparent text-sm text-[#1a1a18] outline-none placeholder:text-[#9a9893]"
              />
            </label>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-5">
          {loading ? <div className="px-3 pt-5 text-sm text-[#6b6a68]">正在装载目录…</div> : null}
          {error ? <div className="px-3 pt-5 text-sm text-[#8b3c2f]">{error}</div> : null}

          <SidebarSection title="待收束" collapsed={collapsed}>
            {reviewItems.map((item) => (
              <SidebarItem key={item.key} {...item} active={pathname === item.to} collapsed={collapsed} />
            ))}
          </SidebarSection>

          <SidebarSection title="进行中" collapsed={collapsed}>
            {liveItems.map((item) => (
              <SidebarItem key={item.key} {...item} active={pathname === item.to} collapsed={collapsed} />
            ))}
          </SidebarSection>

          <SidebarSection title="卷宗" collapsed={collapsed}>
            {folioItems.map((item) => (
              <SidebarItem key={item.key} {...item} active={pathname === item.to} collapsed={collapsed} />
            ))}
          </SidebarSection>

          <SidebarSection title="散札" collapsed={collapsed}>
            {recentItems.map((item) => (
              <SidebarItem key={item.key} {...item} active={pathname === item.to} collapsed={collapsed} />
            ))}
          </SidebarSection>

          {!loading && !error && !reviewItems.length && !liveItems.length && !folioItems.length && !recentItems.length ? (
            <div className="px-3 pt-10 text-sm text-[#6b6a68]">{normalizedSearch ? "没有匹配项。" : "Portal 里还没有可展示的对象。"}</div>
          ) : null}
        </div>

        <div className="border-t border-[rgba(0,0,0,0.05)] px-3 py-3">
          <div className={cx("flex items-center gap-3 rounded-2xl px-3 py-2 hover:bg-[#E5E2D8]", collapsed && "justify-center px-0")}>
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#1a1a18] text-xs font-semibold text-white">D</div>
            {collapsed ? null : (
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-[#1a1a18]">Daemon</div>
                <div className="mt-0.5 text-[11px] text-[#8d8b84]">Portal</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
