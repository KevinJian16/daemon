import { BookOpen, ChevronLeft, ChevronRight, FileText, Folder, Inbox, Search, Sparkles, StickyNote } from "lucide-react";
import { Link } from "react-router-dom";
import { cx, deedStatusLabel, shortText } from "../lib/format";

function matchesSearch(search, ...values) {
  const token = String(search || "").trim().toLowerCase();
  if (!token) return true;
  return values
    .map((value) => String(value || "").toLowerCase())
    .join(" ")
    .includes(token);
}

function dedupeRows(rows) {
  const seen = new Set();
  return rows.filter((row) => {
    const key = String(row?.id || row?.draft_id || row?.slug || "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function deskLooseRows(sidebar, search) {
  return dedupeRows([...(sidebar?.pending || []), ...(sidebar?.live || []), ...(sidebar?.recent || [])])
    .filter((row) => !row?.folio)
    .filter((row) => matchesSearch(search, row?.title, row?.objective, row?.slug, row?.deed?.status))
    .sort((left, right) => new Date(right?.updated_utc || 0).getTime() - new Date(left?.updated_utc || 0).getTime());
}

function deskDraftRows(drafts, search) {
  return (Array.isArray(drafts) ? drafts : [])
    .filter((row) => String(row?.status || "").toLowerCase() === "drafting" && !String(row?.folio_id || "").trim())
    .filter((row) =>
      matchesSearch(search, row?.intent_snapshot, row?.candidate_brief?.objective, row?.candidate_brief?.title, row?.source),
    )
    .sort((left, right) => new Date(right?.updated_utc || 0).getTime() - new Date(left?.updated_utc || 0).getTime());
}

function folioRows(sidebar, search) {
  return (sidebar?.folios || [])
    .filter((row) => matchesSearch(search, row?.title, row?.summary, row?.slug))
    .sort((left, right) => new Date(right?.updated_utc || 0).getTime() - new Date(left?.updated_utc || 0).getTime());
}

function topPreviewText(draft) {
  return shortText(draft?.candidate_brief?.objective || draft?.intent_snapshot || "未成札草稿", 18);
}

function SidebarPreviewGroup({ label, children }) {
  if (!children.length) return null;
  return (
    <div className="mt-3" data-testid={`sidebar-preview-group-${label}`}>
      <div className="mb-1 px-3 text-[11px] uppercase tracking-[0.14em] text-[#9a9893]">{label}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function SidebarPreviewItem({ to, title, subtitle, active, icon, testId }) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className={cx(
        "flex items-start gap-3 rounded-2xl px-3 py-2 transition",
        active ? "bg-[#DDD9CE]" : "hover:bg-[#E5E2D8]",
      )}
    >
      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl bg-white/82 text-[#8d8b84] shadow-sm">
        {icon}
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm text-[#1a1a18]">{title}</div>
        {subtitle ? <div className="mt-0.5 truncate text-[11px] text-[#8d8b84]">{subtitle}</div> : null}
      </div>
    </Link>
  );
}

function WorkspaceRow({ to, title, meta, active, collapsed, icon, testId }) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className={cx(
        "group flex items-center gap-3 rounded-2xl px-3 py-2.5 transition-colors",
        active ? "bg-[#DDD9CE]" : "hover:bg-[#E5E2D8]",
      )}
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-2xl bg-white/85 text-[#6b6a68] shadow-sm">
        {icon}
      </div>
      {collapsed ? null : (
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-[#1a1a18]">{title}</div>
          {meta ? <div className="mt-0.5 truncate text-[11px] text-[#8d8b84]">{meta}</div> : null}
        </div>
      )}
    </Link>
  );
}

function WorkspaceHeader({ title, meta, collapsed, icon, testId }) {
  return (
    <div data-testid={testId} className={cx("flex items-center gap-3 rounded-2xl px-3 py-2.5", collapsed && "justify-center")}>
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-2xl bg-white/85 text-[#6b6a68] shadow-sm">
        {icon}
      </div>
      {collapsed ? null : (
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-[#1a1a18]">{title}</div>
          {meta ? <div className="mt-0.5 truncate text-[11px] text-[#8d8b84]">{meta}</div> : null}
        </div>
      )}
    </div>
  );
}

export default function ClaudeSidebar({
  sidebar,
  drafts,
  loading,
  draftsLoading,
  error,
  collapsed,
  onToggleCollapse,
  search,
  onSearchChange,
  pathname,
}) {
  const deskSlips = deskLooseRows(sidebar, search);
  const deskDrafts = deskDraftRows(drafts, search);
  const folios = folioRows(sidebar, search);
  const nothingVisible = !loading && !error && !deskSlips.length && !deskDrafts.length && !folios.length;
  const deskActive = pathname === "/";

  return (
    <aside
      data-testid="portal-sidebar"
      className={cx(
        "h-full shrink-0 border-r border-[rgba(0,0,0,0.06)] bg-[#ECEBE4] transition-all duration-300",
        collapsed ? "w-[82px]" : "w-[320px]",
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
              data-testid="sidebar-collapse-toggle"
              className="flex h-8 w-8 items-center justify-center rounded-xl text-[#6b6a68] transition hover:bg-[#E5E2D8] hover:text-[#1a1a18]"
            >
              {collapsed ? <ChevronRight width={16} height={16} /> : <ChevronLeft width={16} height={16} />}
            </button>
          </div>

          {collapsed ? null : (
            <label className="mt-4 flex items-center gap-2 rounded-2xl border border-[rgba(0,0,0,0.06)] bg-white/70 px-3 py-2 shadow-sm">
              <Search width={15} height={15} className="text-[#8d8b84]" />
              <input
                data-testid="sidebar-search-input"
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder="Search Portal"
                className="w-full border-none bg-transparent text-sm text-[#1a1a18] outline-none placeholder:text-[#9a9893]"
              />
            </label>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-5">
          {loading ? <div className="px-3 pt-5 text-sm text-[#6b6a68]">正在装载案头…</div> : null}
          {error ? <div className="px-3 pt-5 text-sm text-[#8b3c2f]">{error}</div> : null}

          <section className="mt-5">
            <WorkspaceRow
              to="/"
              title="案头"
              meta={`${deskSlips.length} 张散札 · ${draftsLoading ? "…" : deskDrafts.length} 张草稿`}
              active={deskActive}
              collapsed={collapsed}
              icon={<Sparkles width={16} height={16} />}
              testId="sidebar-workspace-desk"
            />

            {collapsed ? null : (
              <div className="mt-2 border-l border-[rgba(0,0,0,0.05)] pl-3 ml-7" data-testid="sidebar-desk-children">
                <SidebarPreviewGroup label="散札">
                  {deskSlips.slice(0, 4).map((row) => (
                    <SidebarPreviewItem
                      key={row.id}
                      to={`/slips/${encodeURIComponent(row.slug)}`}
                      title={row.title}
                      subtitle={deedStatusLabel(row?.deed?.status) || shortText(row.objective, 20)}
                      icon={<StickyNote width={14} height={14} />}
                      active={pathname === `/slips/${encodeURIComponent(row.slug)}`}
                      testId={`sidebar-desk-slip-${row.slug}`}
                    />
                  ))}
                </SidebarPreviewGroup>

                <SidebarPreviewGroup label="Tray">
                  {deskDrafts.slice(0, 4).map((row) => (
                    <SidebarPreviewItem
                      key={row.draft_id}
                      to={`/?draft=${encodeURIComponent(row.draft_id)}`}
                      title={topPreviewText(row)}
                      subtitle={String(row?.source || "chat")}
                      icon={<Inbox width={14} height={14} />}
                      active={deskActive}
                      testId={`sidebar-desk-draft-${row.draft_id}`}
                    />
                  ))}
                </SidebarPreviewGroup>
              </div>
            )}
          </section>

          <section className="mt-6">
            <WorkspaceHeader
              title="卷宗"
              meta={`${folios.length} 卷`}
              collapsed={collapsed}
              icon={<BookOpen width={16} height={16} />}
              testId="sidebar-workspace-folios"
            />
            <div
              data-testid="sidebar-folio-list"
              className={cx("space-y-1", collapsed ? "mt-2" : "mt-2 border-l border-[rgba(0,0,0,0.05)] pl-3 ml-7")}
            >
              {folios.map((folio) => {
                const to = `/folios/${encodeURIComponent(folio.slug)}`;
                return (
                  <WorkspaceRow
                    key={folio.id}
                    to={to}
                    title={folio.title}
                    meta={`${folio.slip_count || 0} 张签札`}
                    active={pathname === to}
                    collapsed={collapsed}
                    icon={<Folder width={16} height={16} />}
                    testId={`sidebar-folio-${folio.slug}`}
                  />
                );
              })}
            </div>
          </section>

          {nothingVisible ? (
            <div className="px-3 pt-10 text-sm text-[#6b6a68]">{String(search || "").trim() ? "没有匹配项。" : "Portal 里还没有可展示的对象。"}</div>
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
