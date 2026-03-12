import { FileText, GripVertical, Loader2, SquarePen } from "lucide-react";
import { useState, useMemo } from "react";
import { Link, useLocation, useNavigate, useOutletContext, useSearchParams } from "react-router-dom";
import DraftTray from "./DraftTray";
import VoiceSheet from "./VoiceSheet";
import { createFolioFromSlips } from "../lib/api";
import { cx, deedStatusLabel, deedStatusTone, shortText, triggerTypeLabel } from "../lib/format";

function collectDeskSlips(sidebar) {
  const rows = [...(sidebar?.pending || []), ...(sidebar?.live || []), ...(sidebar?.recent || [])]
    .filter((row) => row && typeof row === "object" && !row.folio)
    .sort((left, right) => new Date(right.updated_utc || 0).getTime() - new Date(left.updated_utc || 0).getTime());
  const seen = new Set();
  return rows.filter((row) => {
    const key = String(row.id || row.slug || "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function DeskSlipCard({ slip, organizing, dragging, dropTarget, onDragStart, onDragEnd, onDropOnSlip }) {
  const deedStatus = String(slip?.deed?.status || "");
  return (
    <Link
      to={`/slips/${encodeURIComponent(slip.slug)}`}
      data-testid={`desk-slip-card-${slip.slug}`}
      draggable={organizing}
      onClick={(event) => {
        if (organizing) {
          event.preventDefault();
        }
      }}
      onDragStart={(event) => onDragStart?.(event, slip)}
      onDragEnd={() => onDragEnd?.()}
      onDragOver={(event) => {
        if (!organizing) return;
        event.preventDefault();
      }}
      onDrop={(event) => {
        if (!organizing) return;
        event.preventDefault();
        onDropOnSlip?.(slip);
      }}
      className="block rounded-[1.6rem] border border-[rgba(0,0,0,0.05)] bg-[#faf8f5] px-4 py-4 shadow-[0_8px_22px_rgba(41,41,41,0.045),0_1px_0_rgba(255,255,255,0.72)_inset,0_-1px_0_rgba(41,41,41,0.03)_inset] transition hover:bg-[#fdfbf8]"
      style={{
        opacity: dragging ? 0.48 : 1,
        transform: dropTarget ? "translateY(-1px)" : undefined,
        boxShadow: dropTarget
          ? "0 0 0 1px rgba(174,86,48,0.22), 0 16px 34px rgba(41,41,41,0.08), 0 1px 0 rgba(255,255,255,0.72) inset"
          : undefined,
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-medium text-[#1a1a18]">{slip.title}</div>
          <div className="mt-2 text-[12px] leading-5 text-[#6b6a68]">{shortText(slip.objective, 92)}</div>
        </div>
        {deedStatus ? (
          <span className={cx("rounded-full px-2.5 py-1 text-[11px] font-medium", deedStatusTone(deedStatus))}>
            {deedStatusLabel(deedStatus)}
          </span>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-white/90 px-2.5 py-1 text-[11px] text-[#8d8b84]">{triggerTypeLabel(slip.trigger_type)}</span>
        {slip.standing ? <span className="rounded-full bg-white/90 px-2.5 py-1 text-[11px] text-[#8d8b84]">时钟中</span> : null}
      </div>
    </Link>
  );
}

export default function DeskPage() {
  const { sidebar, drafts, sidebarLoading, refreshSidebar, refreshDrafts } = useOutletContext();
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [organizing, setOrganizing] = useState(false);
  const [draggingLooseSlug, setDraggingLooseSlug] = useState("");
  const [dropTargetSlug, setDropTargetSlug] = useState("");
  const [pageError, setPageError] = useState("");

  const looseSlips = useMemo(() => collectDeskSlips(sidebar), [sidebar]);
  const deskDrafts = useMemo(
    () =>
      (Array.isArray(drafts) ? drafts : []).filter(
        (row) => String(row?.status || "").toLowerCase() === "drafting" && !String(row?.folio_id || "").trim(),
      ),
    [drafts],
  );
  const selectedDraftId = useMemo(() => String(new URLSearchParams(location.search).get("draft") || ""), [location.search]);

  const refreshDesk = async () => {
    await Promise.all([refreshSidebar?.(), refreshDrafts?.()]);
  };

  const endDrag = () => {
    setDraggingLooseSlug("");
    setDropTargetSlug("");
  };

  return (
    <div className="h-full bg-[#F5F5F0]" data-testid="desk-page">
      <div className="mx-auto flex h-full w-full max-w-[72rem] flex-col px-6 pb-6 pt-6">
        <div className="min-h-0 flex-1 overflow-y-auto pb-10">
          <div className="px-1 py-2">
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[#8d8b84]">Desk</div>
            <h1 className="portal-serif text-[1.92rem] leading-[2.25rem] text-[#1a1a18]">案头</h1>
          </div>

          <section className="mt-7 px-1" data-testid="desk-loose-section">
            <div className="mb-4 flex items-center justify-between gap-4">
              <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
                <FileText width={16} height={16} />
                <span>散札</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setPageError("");
                    setOrganizing((current) => !current);
                  }}
                  data-testid="desk-organize-toggle"
                  title={organizing ? "退出整理" : "整理散札"}
                  className={cx(
                    "inline-flex h-9 w-9 items-center justify-center rounded-full transition",
                    organizing ? "bg-[#ae5630] text-white" : "bg-[#f8f7f2] text-[#6b6a68] hover:bg-white",
                  )}
                >
                  <GripVertical width={15} height={15} />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPageError("");
                    setVoiceOpen(true);
                  }}
                  data-testid="desk-voice-open"
                  title="收敛一件新事"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#f8f7f2] text-[#6b6a68] transition hover:bg-white"
                >
                  <SquarePen width={15} height={15} />
                </button>
              </div>
            </div>
          </section>

          {organizing ? (
            <div className="mb-4 rounded-[1.35rem] border border-[rgba(0,0,0,0.05)] bg-[#f8f7f2] px-4 py-3 text-sm text-[#8d8b84]">
              把一张散札拖到另一张散札上，会直接合成一卷。
            </div>
          ) : null}

          {pageError ? <div className="mb-4 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{pageError}</div> : null}

          <section className="px-1">

            {sidebarLoading ? (
              <div className="flex h-32 items-center justify-center rounded-[1.55rem] border border-[rgba(0,0,0,0.05)] bg-[#f8f7f2]">
                <Loader2 className="animate-spin text-[#8d8b84]" />
              </div>
            ) : !looseSlips.length ? (
              <div className="rounded-[1.55rem] border border-[rgba(0,0,0,0.05)] bg-[#f8f7f2] px-4 py-4 text-sm text-[#8d8b84]">
                案头上还没有卷外散札。
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {looseSlips.map((slip) => (
                  <DeskSlipCard
                    key={slip.id || slip.slug}
                    slip={slip}
                    organizing={organizing}
                    dragging={draggingLooseSlug === slip.slug}
                    dropTarget={dropTargetSlug === slip.slug}
                    onDragStart={(event, row) => {
                      if (!organizing) return;
                      const slug = String(row?.slug || "");
                      event.dataTransfer.effectAllowed = "move";
                      event.dataTransfer.setData("application/x-daemon-slip", JSON.stringify({ type: "desk-slip", slug }));
                      setDraggingLooseSlug(slug);
                      setDropTargetSlug("");
                    }}
                    onDragEnd={() => {
                      endDrag();
                    }}
                    onDropOnSlip={async (target) => {
                      if (!organizing) return;
                      const sourceSlug = draggingLooseSlug;
                      const targetSlug = String(target?.slug || "");
                      setDropTargetSlug(targetSlug);
                      if (!sourceSlug || !targetSlug || sourceSlug === targetSlug) {
                        endDrag();
                        return;
                      }
                      try {
                        setPageError("");
                        const result = await createFolioFromSlips(sourceSlug, targetSlug);
                        await refreshDesk();
                          if (result?.folio?.slug) {
                            navigate(`/folios/${encodeURIComponent(result.folio.slug)}`);
                        }
                      } catch (actionError) {
                        setPageError(actionError.message || "两张散札暂时无法合成新卷。");
                      } finally {
                        endDrag();
                      }
                    }}
                  />
                ))}
              </div>
            )}
          </section>

          <div className="mt-8">
            <DraftTray
              title="Tray"
              testIdPrefix="desk-tray"
              drafts={deskDrafts}
              selectedDraftId={selectedDraftId}
              onSelectDraft={(draftId) => {
                const next = new URLSearchParams(searchParams);
                if (draftId) {
                  next.set("draft", draftId);
                } else {
                  next.delete("draft");
                }
                setSearchParams(next, { replace: true });
              }}
              onDraftsChanged={refreshDesk}
              onSlipCreated={(slip) => {
                navigate(`/slips/${encodeURIComponent(slip.slug)}`);
              }}
            />
          </div>
        </div>
      </div>

      <VoiceSheet
        open={voiceOpen}
        testId="desk-voice-sheet"
        scope="desk"
        onClose={() => setVoiceOpen(false)}
        onDraftsChanged={refreshDesk}
        onDraftCreated={(draftId) => {
          setVoiceOpen(false);
          setSearchParams({ draft: draftId }, { replace: true });
        }}
      />
    </div>
  );
}
