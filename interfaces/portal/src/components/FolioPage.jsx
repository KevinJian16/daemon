import { FileText, FolderOpen, GripVertical, House, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";
import ConversationDock from "./ConversationDock";
import DraftTray from "./DraftTray";
import { FolioBoard } from "./PortalGraphs";
import {
  adoptSlipToFolio,
  createVoiceSession,
  getFolio,
  reorderFolioByPair,
  sendVoiceMessage,
  takeOutSlip,
  updateDraft,
} from "../lib/api";

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

function prefixVoiceMessage(folioTitle, text) {
  const clean = String(text || "").trim();
  if (!clean) return "";
  return `围绕卷《${folioTitle}》新增一件事：${clean}`;
}

function LooseSlipStrip({ slips, draggingSlipSlug, onDragStart, onDragEnd }) {
  if (!slips.length) return null;
  return (
    <div className="mt-4" data-testid="folio-loose-slip-strip">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
        <FileText width={16} height={16} />
        <span>卷外散札</span>
      </div>
      <div className="flex gap-3 overflow-x-auto pb-2">
        {slips.map((slip) => (
          <div
            key={slip.id || slip.slug}
            data-testid={`folio-loose-slip-${slip.slug}`}
            draggable
            onDragStart={(event) => onDragStart?.(event, slip)}
            onDragEnd={() => onDragEnd?.()}
            className="w-[11.6rem] shrink-0 rounded-[1.42rem] border border-[rgba(0,0,0,0.05)] bg-[#faf8f5] px-3.5 py-3 shadow-[0_10px_24px_rgba(41,41,41,0.05),0_1px_0_rgba(255,255,255,0.76)_inset,0_-1px_0_rgba(41,41,41,0.03)_inset] transition"
            style={{ opacity: draggingSlipSlug === slip.slug ? 0.42 : 1, cursor: "grab" }}
          >
            <div className="flex min-h-[4.4rem] flex-col justify-between">
              <span className="inline-flex h-2.5 w-2.5 rounded-full bg-[#adadad]" />
              <div className="line-clamp-2 text-[13px] font-medium leading-[1.18] text-[#1a1a18]">{slip.title}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FolioBoardOverlay({ open, folio, onClose, onOpenSlip }) {
  useEffect(() => {
    if (!open) return undefined;
    const handleKeydown = (event) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [onClose, open]);

  if (!open || !folio) return null;
  return (
    <div
      data-testid="folio-board-overlay"
      className="fixed inset-0 z-40 overflow-y-auto bg-[#F5F5F0]/96 backdrop-blur-sm"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="mx-auto w-full max-w-[88rem] px-6 pb-10 pt-6">
        <div className="px-1">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
            <FolderOpen width={16} height={16} />
            <span>{folio.title}</span>
          </div>
          <FolioBoard slips={folio.slips || []} writs={folio.writs || []} onSelectSlip={onOpenSlip} />
        </div>
      </div>
    </div>
  );
}

export default function FolioPage() {
  const { folioSlug } = useParams();
  const { sidebar, drafts, refreshSidebar, refreshDrafts, lastWsEvent } = useOutletContext();
  const decodedSlug = decodeURIComponent(folioSlug || "");
  const navigate = useNavigate();

  const [folio, setFolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [expandedBoard, setExpandedBoard] = useState(false);
  const [organizing, setOrganizing] = useState(false);
  const [dragPayload, setDragPayload] = useState(null);
  const [dropTargetSlug, setDropTargetSlug] = useState("");
  const [boardDropActive, setBoardDropActive] = useState(false);
  const [deskDropActive, setDeskDropActive] = useState(false);
  const [selectedDraftId, setSelectedDraftId] = useState("");
  const [dockFocused, setDockFocused] = useState(false);
  const [voiceSessionId, setVoiceSessionId] = useState("");
  const [voiceMessages, setVoiceMessages] = useState([]);
  const [voiceComposerValue, setVoiceComposerValue] = useState("");
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const [voiceHistory, setVoiceHistory] = useState([]);
  const [voiceCopiedMessageId, setVoiceCopiedMessageId] = useState("");
  const folioLoadedRef = useRef(false);

  const loadFolio = useCallback(async ({ silent = false } = {}) => {
    const initial = !folioLoadedRef.current || !silent;
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError("");
    try {
      const payload = await getFolio(decodedSlug);
      setFolio(payload);
      folioLoadedRef.current = true;
    } catch (loadError) {
      setError(loadError.message || "卷页装载失败。");
    } finally {
      if (initial) {
        setLoading(false);
      } else {
        setRefreshing(false);
      }
    }
  }, [decodedSlug]);

  useEffect(() => {
    loadFolio();
  }, [loadFolio]);

  useEffect(() => {
    setVoiceSessionId("");
    setVoiceMessages([]);
    setVoiceComposerValue("");
    setVoiceBusy(false);
    setVoiceError("");
    setVoiceHistory([]);
    setVoiceCopiedMessageId("");
    setSelectedDraftId("");
    setDockFocused(false);
    folioLoadedRef.current = false;
  }, [decodedSlug]);

  useEffect(() => {
    if (!folio || !lastWsEvent?.event) return;
    if (["deed_closed", "deed_failed", "deed_settling", "folio_progress_update"].includes(String(lastWsEvent.event || ""))) {
      loadFolio({ silent: true });
      refreshSidebar?.();
    }
  }, [folio, lastWsEvent, loadFolio, refreshSidebar]);

  const folioDrafts = useMemo(
    () =>
      (Array.isArray(drafts) ? drafts : []).filter(
        (row) =>
          String(row?.status || "").toLowerCase() === "drafting" &&
          String(row?.folio_id || "").trim() === String(folio?.id || "").trim(),
      ),
    [drafts, folio?.id],
  );
  const deskLooseSlips = useMemo(() => collectDeskSlips(sidebar), [sidebar]);

  const refreshFolio = useCallback(async () => {
    await Promise.all([loadFolio({ silent: true }), refreshDrafts?.(), refreshSidebar?.()]);
  }, [loadFolio, refreshDrafts, refreshSidebar]);

  const ensureVoiceSession = useCallback(async () => {
    if (voiceSessionId) return voiceSessionId;
    const payload = await createVoiceSession();
    const nextSessionId = String(payload?.session_id || "");
    setVoiceSessionId(nextSessionId);
    return nextSessionId;
  }, [voiceSessionId]);

  const handleVoiceSend = useCallback(async () => {
    const text = voiceComposerValue.trim();
    if (!text || voiceBusy) return;
    setVoiceBusy(true);
    setVoiceError("");
    try {
      const sessionId = await ensureVoiceSession();
      const outgoing = {
        message_id: `voice-user-${Date.now()}`,
        role: "user",
        content: text,
        created_utc: new Date().toISOString(),
      };
      setVoiceMessages((current) => [...current, outgoing]);
      setVoiceHistory((current) => [...current.slice(-19), text]);
      setVoiceComposerValue("");
      setDockFocused(true);

      const result = await sendVoiceMessage(sessionId, { message: prefixVoiceMessage(folio?.title, text) });
      const incoming = {
        message_id: `voice-assistant-${Date.now()}`,
        role: "assistant",
        content: String(result?.content || "这卷里先记下了。"),
        created_utc: new Date().toISOString(),
      };
      setVoiceMessages((current) => [...current, incoming]);

      const draftId = String(result?.plan?.metadata?.draft_id || "");
      if (draftId && folio?.id) {
        await updateDraft(draftId, { folio_id: folio.id });
        setSelectedDraftId(draftId);
      }
      await refreshFolio();
    } catch (sendError) {
      setVoiceError(sendError.message || "这卷暂时还收不进新事。");
    } finally {
      setVoiceBusy(false);
    }
  }, [ensureVoiceSession, folio?.id, folio?.title, refreshFolio, voiceBusy, voiceComposerValue]);

  const handleCopyVoiceMessage = useCallback(async (message) => {
    try {
      await navigator.clipboard.writeText(String(message.content || ""));
      const id = String(message.message_id || `${message.created_utc}|${message.content}`);
      setVoiceCopiedMessageId(id);
      window.setTimeout(() => setVoiceCopiedMessageId(""), 1400);
    } catch {
      setVoiceError("复制失败。");
    }
  }, []);

  const beginDrag = (type, slip) => (event) => {
    const payload = { type, slug: String(slip?.slug || "") };
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-daemon-slip", JSON.stringify(payload));
    setDragPayload(payload);
    setDropTargetSlug("");
    setBoardDropActive(false);
    setDeskDropActive(false);
  };

  const endDrag = () => {
    setDragPayload(null);
    setDropTargetSlug("");
    setBoardDropActive(false);
    setDeskDropActive(false);
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-[#F5F5F0]">
        <Loader2 className="animate-spin text-[#8d8b84]" />
      </div>
    );
  }

  if (!folio) {
    return (
      <div className="flex h-full items-center justify-center bg-[#F5F5F0] px-6 text-center text-[#6b6a68]">
        {error || "这卷还没有被 Portal 读到。"}
      </div>
    );
  }

  return (
    <div className="h-full bg-[#F5F5F0]" data-testid="folio-page">
      <FolioBoardOverlay
        open={expandedBoard}
        folio={folio}
        onClose={() => setExpandedBoard(false)}
        onOpenSlip={(slip) => navigate(`/slips/${encodeURIComponent(slip.slug)}`)}
      />

      <div className="relative mx-auto flex h-full w-full max-w-[72rem] flex-col px-6 pb-6 pt-6">
        <div className="min-h-0 flex-1 overflow-y-auto pb-44" onPointerDownCapture={() => setDockFocused(false)}>
          {error ? <div className="mb-4 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{error}</div> : null}

          <div className="px-1 py-2">
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[#8d8b84]">Folio</div>
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <h1 className="portal-serif text-[1.92rem] leading-[2.25rem] text-[#1a1a18]">{folio.title}</h1>
                {refreshing ? <Loader2 className="h-4 w-4 animate-spin text-[#8d8b84]" /> : null}
              </div>
              <button
                type="button"
                onClick={() => {
                  setError("");
                  setOrganizing((current) => !current);
                }}
                data-testid="folio-organize-toggle"
                title={organizing ? "退出整理" : "整理卷内对象"}
                className={`inline-flex h-9 w-9 items-center justify-center rounded-full transition ${
                  organizing ? "bg-[#ae5630] text-white" : "bg-[#f8f7f2] text-[#6b6a68] hover:bg-white"
                }`}
              >
                <GripVertical width={15} height={15} />
              </button>
            </div>
          </div>

          {organizing ? (
            <div
              data-testid="folio-return-to-desk-dropzone"
              className="mt-5 rounded-[1.4rem] border border-[rgba(0,0,0,0.05)] bg-[#f8f7f2] px-4 py-3 transition"
              onDragOver={(event) => {
                if (!dragPayload || dragPayload.type !== "folio-slip") return;
                event.preventDefault();
                setDeskDropActive(true);
              }}
              onDragLeave={() => setDeskDropActive(false)}
              onDrop={async (event) => {
                if (!dragPayload || dragPayload.type !== "folio-slip") return;
                event.preventDefault();
                setDeskDropActive(false);
                try {
                  setError("");
                  await takeOutSlip(dragPayload.slug);
                  await refreshFolio();
                } catch (actionError) {
                  setError(actionError.message || "这张签札暂时无法放回案头。");
                } finally {
                  endDrag();
                }
              }}
              style={{
                boxShadow: deskDropActive ? "inset 0 0 0 1px rgba(174,86,48,0.24)" : undefined,
                background: deskDropActive ? "#fcf7f1" : undefined,
              }}
            >
              <div className="flex items-center gap-2 text-sm font-medium text-[#6b6a68]">
                <House width={15} height={15} />
                <span>放回案头</span>
              </div>
            </div>
          ) : null}

          <div className="mt-6">
            <FolioBoard
              slips={folio.slips || []}
              writs={folio.writs || []}
              compact
              testId="folio-board-compact"
              organizing={organizing}
              draggingSlipSlug={String(dragPayload?.type === "folio-slip" ? dragPayload.slug : "")}
              dropTargetSlug={dropTargetSlug}
              boardDropActive={boardDropActive}
              onSelectSlip={(slip) => navigate(`/slips/${encodeURIComponent(slip.slug)}`)}
              onDetailClick={() => setExpandedBoard(true)}
              onCardDragStart={(event, slip) => beginDrag("folio-slip", slip)(event)}
              onCardDragEnd={() => endDrag()}
              onCardDragOver={(_event, targetSlip) => {
                if (!dragPayload || dragPayload.type !== "folio-slip") return;
                setDropTargetSlug(String(targetSlip?.slug || ""));
              }}
              onCardDrop={async (_event, targetSlip) => {
                if (!dragPayload || dragPayload.type !== "folio-slip") return;
                const sourceSlug = dragPayload.slug;
                const targetSlug = String(targetSlip?.slug || "");
                setDropTargetSlug(targetSlug);
                if (!sourceSlug || !targetSlug || sourceSlug === targetSlug) {
                  endDrag();
                  return;
                }
                try {
                  setError("");
                  await reorderFolioByPair(decodedSlug, sourceSlug, targetSlug);
                  await refreshFolio();
                } catch (actionError) {
                  setError(actionError.message || "卷内顺序暂时无法调整。");
                } finally {
                  endDrag();
                }
              }}
              onBoardDragOver={(event) => {
                if (!dragPayload || dragPayload.type !== "desk-slip") return;
                event.preventDefault();
                setBoardDropActive(true);
              }}
              onBoardDragLeave={() => setBoardDropActive(false)}
              onBoardDrop={async (event) => {
                if (!dragPayload || dragPayload.type !== "desk-slip") return;
                event.preventDefault();
                setBoardDropActive(false);
                try {
                  setError("");
                  await adoptSlipToFolio(decodedSlug, dragPayload.slug);
                  await refreshFolio();
                } catch (actionError) {
                  setError(actionError.message || "这张签札暂时无法收入卷。");
                } finally {
                  endDrag();
                }
              }}
            />
          </div>

          {organizing ? (
            <LooseSlipStrip
              slips={deskLooseSlips}
              draggingSlipSlug={String(dragPayload?.type === "desk-slip" ? dragPayload.slug : "")}
              onDragStart={(event, slip) => beginDrag("desk-slip", slip)(event)}
              onDragEnd={endDrag}
            />
          ) : null}

          <div className="mt-8">
            <DraftTray
              title="Tray"
              drafts={folioDrafts}
              workspaceFolioId={folio.id}
              testIdPrefix="folio-tray"
              selectedDraftId={selectedDraftId}
              onSelectDraft={setSelectedDraftId}
              onDraftsChanged={refreshFolio}
              onSlipCreated={(slip) => navigate(`/slips/${encodeURIComponent(slip.slug)}`)}
            />
          </div>
        </div>

        {voiceError ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-28 z-10 px-4">
            <div className="mx-auto w-full max-w-3xl rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">
              {voiceError}
            </div>
          </div>
        ) : null}

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10">
          <ConversationDock
            ownerLabel="Folio"
            composerPlaceholder="把一件新事放进这卷里"
            focused={dockFocused}
            onFocusChange={setDockFocused}
            messages={voiceMessages}
            composerValue={voiceComposerValue}
            onComposerChange={setVoiceComposerValue}
            onComposerSubmit={handleVoiceSend}
            onComposerHistoryUp={() => setVoiceComposerValue(voiceHistory[voiceHistory.length - 1] || "")}
            composerDisabled={voiceBusy}
            composerLoading={voiceBusy}
            onEditMessage={(message) => {
              setVoiceComposerValue(String(message.content || ""));
              setDockFocused(true);
            }}
            onCopyMessage={handleCopyVoiceMessage}
            copiedMessageId={voiceCopiedMessageId}
            testIdPrefix="folio-dock"
          />
        </div>
      </div>
    </div>
  );
}
