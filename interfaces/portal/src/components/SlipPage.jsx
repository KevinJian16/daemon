import {
  ChevronDown,
  ChevronUp,
  Check,
  Clock3,
  Folder,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Search,
  Waypoints,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useOutletContext, useParams } from "react-router-dom";
import ConversationDock from "./ConversationDock";
import { MoveGraphCanvas, graphNodeStatusMapFromDag } from "./PortalGraphs";
import {
  getDeed,
  getDeedOfferingFiles,
  getSlip,
  getSlipMessages,
  getSlipWritNeighbors,
  pauseDeed,
  rerunSlip,
  resumeDeed,
  sendSlipMessage,
  updateSlipStance,
} from "../lib/api";
import {
  cx,
  deedStatusLabel,
  deedStatusTone,
  deedSubStatusLabel,
  formatDateTime,
  normalizeDag,
  shortText,
  triggerTypeLabel,
} from "../lib/format";

function mergeMessageRows(currentRows, nextRows) {
  const map = new Map();
  [...currentRows, ...nextRows].forEach((row, index) => {
    const key = String(row.message_id || `${row.deed_id || "none"}|${row.created_utc || ""}|${row.role || ""}|${row.content || ""}|${index}`);
    if (!map.has(key)) {
      map.set(key, row);
    }
  });
  return [...map.values()].sort(
    (left, right) => new Date(left.created_utc || 0).getTime() - new Date(right.created_utc || 0).getTime(),
  );
}

function deedSummary(row) {
  if (!row) return null;
  return {
    id: String(row.id || row.deed_id || ""),
    status: String(row.status || row.deed_status || "").toLowerCase(),
    subStatus: String(row.sub_status || row.deed_sub_status || "").toLowerCase(),
    title: String(row.title || row.deed_title || ""),
    createdUtc: String(row.created_utc || ""),
    updatedUtc: String(row.updated_utc || ""),
    phase: String(row.phase || ""),
  };
}

function deedOpacityClass(updatedUtc) {
  const ageHours = (Date.now() - new Date(updatedUtc || 0).getTime()) / 36e5;
  if (ageHours > 48) return "opacity-50";
  if (ageHours > 24) return "opacity-70";
  return "opacity-100";
}

function resolvedTriggerType(slip, neighbors) {
  const explicit = String(slip?.trigger_type || "").toLowerCase();
  if (explicit) return explicit;
  if (slip?.cadence?.active || slip?.standing) return "timer";
  if ((neighbors?.prev || []).length) return "writ_chain";
  return "manual";
}

function deedStatusDotTone(status) {
  const key = String(status || "").toLowerCase();
  if (key === "running") return "#AE5630";
  if (key === "settling") return "#8A4A26";
  if (key === "closed") return "#686868";
  if (key === "failed") return "#8B3C2F";
  return "#ADADAD";
}

function MoveGraphOverlay({ open, title, dag, onClose }) {
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

  if (!open) return null;
  return (
    <div
      data-testid="slip-move-overlay"
      className="fixed inset-0 z-40 overflow-y-auto bg-[#F5F5F0]/96 backdrop-blur-sm"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="mx-auto w-full max-w-[84rem] px-6 pb-10 pt-6">
        <div className="px-1">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
            <Waypoints width={16} height={16} />
            <span>{title}</span>
          </div>
          <MoveGraphCanvas dag={dag} mode="structure" />
        </div>
      </div>
    </div>
  );
}

function DeedHistoryStrip({ deeds, activeDeedId, onOpenDeed }) {
  if (!deeds.length) return null;
  return (
    <div className="mt-6 px-1" data-testid="slip-deed-history">
      <div className="mb-3 text-sm font-medium text-[#1a1a18]">历次行事</div>
      <div className="-mx-1 overflow-x-auto pb-1">
        <div className="flex gap-3 px-1">
          {deeds.map((deed, index) => (
          <button
            key={deed.id}
            type="button"
            data-testid={`slip-deed-history-${deed.id}`}
            onClick={() => onOpenDeed(deed.id)}
            className={cx(
              "w-[12.75rem] shrink-0 rounded-[1.5rem] border px-4 py-3 text-left transition duration-150",
              deed.id === activeDeedId
                ? "border-[rgba(174,86,48,0.28)] bg-[#fffdf8] shadow-[0_12px_26px_rgba(41,41,41,0.06),0_1px_0_rgba(255,255,255,0.9)_inset,0_-1px_0_rgba(174,86,48,0.08)_inset]"
                : "border-[rgba(0,0,0,0.05)] bg-[#f7f3eb] hover:bg-[#fbf8f1] shadow-[0_8px_20px_rgba(41,41,41,0.04),0_1px_0_rgba(255,255,255,0.84)_inset]",
              deed.status === "closed" && deed.id !== activeDeedId ? deedOpacityClass(deed.updatedUtc) : "",
            )}
          >
            <div className="flex min-h-[5.25rem] flex-col justify-between">
              <div className="flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-2 text-[12px] font-medium text-[#1a1a18]">
                  <span
                    className="inline-flex h-2.5 w-2.5 rounded-full"
                    style={{ background: deedStatusDotTone(deed.status) }}
                  />
                  {deedStatusLabel(deed.status)}
                </span>
                {index === 0 ? <span className="text-[11px] text-[#8d8b84]">最近</span> : null}
              </div>
              <div className="mt-3 flex items-end justify-between gap-3">
                <div className="text-[12px] text-[#8d8b84]">{formatDateTime(deed.updatedUtc || deed.createdUtc)}</div>
                {deed.subStatus && deedSubStatusLabel(deed.subStatus) ? (
                  <span className="rounded-full bg-white/84 px-2 py-1 text-[10px] text-[#6b6a68]">
                    {deedSubStatusLabel(deed.subStatus)}
                  </span>
                ) : null}
              </div>
            </div>
          </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function DeedBlock({
  slipDag,
  deed,
  detail,
  files,
  previewText,
  expanded,
  loading,
  runtimeStatuses,
  onToggle,
  onPause,
  onResume,
  onSettle,
}) {
  const normalizedFiles = Array.isArray(files) ? files : [];
  const status = deed.status || detail?.status || detail?.deed_status || "";
  const subStatus = deed.subStatus || detail?.subStatus || detail?.deed_sub_status || "";
  const mergedStatuses = useMemo(() => {
    const next = { ...graphNodeStatusMapFromDag(slipDag) };
    const moveResults = Array.isArray(detail?.plan?.move_results) ? detail.plan.move_results : [];
    if ((status === "closed" || status === "settling") && !moveResults.length) {
      Object.keys(next).forEach((nodeId) => {
        next[nodeId] = status === "closed" ? "completed" : next[nodeId] || "pending";
      });
    }
    moveResults.forEach((result) => {
      const moveId = String(result?.move_id || "");
      if (!moveId) return;
      next[moveId] = result?.ok ? "completed" : "failed";
    });
    return { ...next, ...runtimeStatuses };
  }, [detail?.plan?.move_results, runtimeStatuses, slipDag, status]);

  const canPause = status === "running" && subStatus !== "paused";
  const canResume = status === "running" && subStatus === "paused";
  const canSettle = status === "running" || status === "settling";

  return (
    <div
      data-testid={`slip-deed-block-${deed.id}`}
      className={cx(
        "rounded-[1.6rem] border border-[rgba(0,0,0,0.06)] bg-[#f9f6ef] px-4 py-4 shadow-[0_20px_44px_rgba(41,41,41,0.06),0_1px_0_rgba(255,255,255,0.88)_inset,0_-1px_0_rgba(41,41,41,0.03)_inset] transition",
        status === "closed" && !expanded ? deedOpacityClass(deed.updatedUtc) : "",
      )}
    >
      <button type="button" onClick={onToggle} className="flex w-full items-start justify-between gap-4 text-left">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="inline-flex h-2.5 w-2.5 rounded-full"
              style={{ background: deedStatusDotTone(status) }}
            />
            <span className={cx("rounded-full px-3 py-1 text-xs font-medium", deedStatusTone(status))}>{deedStatusLabel(status)}</span>
            {subStatus && deedSubStatusLabel(subStatus) ? (
              <span className="rounded-full bg-white px-3 py-1 text-[11px] text-[#6b6a68]">{deedSubStatusLabel(subStatus)}</span>
            ) : null}
            {status === "closed" && normalizedFiles.length ? (
              <span className="rounded-full bg-white px-3 py-1 text-[11px] text-[#6b6a68]">{normalizedFiles[0].name}</span>
            ) : null}
          </div>
          <div className="mt-3 text-[12px] text-[#8d8b84]">{formatDateTime(deed.updatedUtc || deed.createdUtc)}</div>
        </div>

        <div className="flex items-center gap-2">
          {loading ? <Loader2 className="h-4 w-4 animate-spin text-[#8d8b84]" /> : null}
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-white/78 text-[#8d8b84] shadow-[0_1px_0_rgba(255,255,255,0.86)_inset]">
            {expanded ? <ChevronUp width={15} height={15} /> : <ChevronDown width={15} height={15} />}
          </span>
        </div>
      </button>

      {expanded ? (
        <div className="mt-4 space-y-4">
          <div className="rounded-[1.45rem] border border-[rgba(0,0,0,0.04)] bg-white/82 p-3">
            <MoveGraphCanvas
              dag={slipDag}
              mode="deed"
              runtimeStatuses={mergedStatuses}
              deedStatus={status}
              compact
              testId={`slip-deed-graph-${deed.id}`}
            />
          </div>

          {previewText || normalizedFiles.length ? (
            <div className="rounded-[1.4rem] border border-[rgba(0,0,0,0.05)] bg-white px-4 py-3">
              {normalizedFiles.length ? (
                <div className="flex flex-wrap gap-2">
                  {normalizedFiles.map((file) => (
                    <a
                      key={file.download_path || file.download || file.relative_path || file.name}
                      href={file.download_path || file.download}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-full bg-[#f6f2ea] px-3 py-1.5 text-[12px] text-[#6b6a68] transition hover:bg-[#efe8dd]"
                    >
                      {file.name}
                    </a>
                  ))}
                </div>
              ) : null}
              {previewText ? (
                <div className={cx("whitespace-pre-wrap text-[13px] leading-6 text-[#1a1a18]", normalizedFiles.length ? "mt-3 line-clamp-6" : "line-clamp-6")}>
                  {previewText}
                </div>
              ) : null}
            </div>
          ) : null}

          {(canPause || canResume || canSettle) ? (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {canPause ? (
                <button
                  type="button"
                  data-testid={`slip-deed-pause-${deed.id}`}
                  onClick={onPause}
                  title="暂停"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#fbfaf7] text-[#6b6a68] transition hover:bg-white"
                >
                  <Pause width={16} height={16} />
                </button>
              ) : null}
              {canResume ? (
                <button
                  type="button"
                  data-testid={`slip-deed-resume-${deed.id}`}
                  onClick={onResume}
                  title="继续"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#fbfaf7] text-[#6b6a68] transition hover:bg-white"
                >
                  <Play width={16} height={16} />
                </button>
              ) : null}
              {canSettle ? (
                <button
                  type="button"
                  data-testid={`slip-deed-settle-${deed.id}`}
                  onClick={onSettle}
                  title="收束"
                  className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#ae5630] text-white transition hover:bg-[#c4633a]"
                >
                  <Check width={16} height={16} />
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default function SlipPage() {
  const { slipSlug, deedId } = useParams();
  const { refreshSidebar, lastWsEvent } = useOutletContext();
  const decodedSlug = decodeURIComponent(slipSlug || "");

  const [slip, setSlip] = useState(null);
  const [messages, setMessages] = useState([]);
  const [neighbors, setNeighbors] = useState({ prev: [], next: [] });
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [dockFocused, setDockFocused] = useState(Boolean(deedId));
  const [composerValue, setComposerValue] = useState("");
  const [composerBusy, setComposerBusy] = useState(false);
  const [messageHistory, setMessageHistory] = useState([]);
  const [copiedMessageId, setCopiedMessageId] = useState("");
  const [messageReactions, setMessageReactions] = useState({});
  const [expandedMoveGraph, setExpandedMoveGraph] = useState(false);
  const [expandedDeedId, setExpandedDeedId] = useState(String(deedId || ""));
  const [scrollTargetId, setScrollTargetId] = useState(deedId ? `deed-block-${deedId}` : "");
  const [deedDetails, setDeedDetails] = useState({});
  const [deedFiles, setDeedFiles] = useState({});
  const [deedPreviews, setDeedPreviews] = useState({});
  const [deedLoading, setDeedLoading] = useState({});
  const [liveMoveStatuses, setLiveMoveStatuses] = useState({});
  const slipLoadedRef = useRef(false);

  const loadSlip = useCallback(async ({ silent = false } = {}) => {
    const initial = !slipLoadedRef.current || !silent;
    if (initial) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError("");
    try {
      const [slipData, messageData, neighborData] = await Promise.all([
        getSlip(decodedSlug),
        getSlipMessages(decodedSlug),
        getSlipWritNeighbors(decodedSlug).catch(() => ({ prev: [], next: [] })),
      ]);
      setSlip(slipData);
      setMessages(Array.isArray(messageData) ? messageData : []);
      setNeighbors(neighborData || { prev: [], next: [] });
      slipLoadedRef.current = true;
    } catch (loadError) {
      setError(loadError.message || "Portal 载入失败。");
    } finally {
      if (initial) {
        setLoading(false);
      } else {
        setRefreshing(false);
      }
    }
  }, [decodedSlug]);

  useEffect(() => {
    loadSlip();
  }, [loadSlip]);

  useEffect(() => {
    setDeedDetails({});
    setDeedFiles({});
    setDeedPreviews({});
    setDeedLoading({});
    setLiveMoveStatuses({});
    setMessages([]);
    setNeighbors({ prev: [], next: [] });
    slipLoadedRef.current = false;
  }, [decodedSlug]);

  const deeds = useMemo(() => {
    const rows = [];
    const current = deedSummary(slip?.current_deed);
    if (current?.id) rows.push(current);
    (slip?.recent_deeds || []).forEach((row) => {
      const summary = deedSummary(row);
      if (summary?.id && !rows.some((item) => item.id === summary.id)) {
        rows.push(summary);
      }
    });
    messages.forEach((message) => {
      const messageDeedId = String(message?.deed_id || "");
      if (messageDeedId && !rows.some((item) => item.id === messageDeedId)) {
        rows.push({
          id: messageDeedId,
          status: "",
          subStatus: "",
          title: "",
          createdUtc: String(message.created_utc || ""),
          updatedUtc: String(message.created_utc || ""),
          phase: "",
        });
      }
    });
    return rows.sort((left, right) => new Date(right.updatedUtc || right.createdUtc || 0).getTime() - new Date(left.updatedUtc || left.createdUtc || 0).getTime());
  }, [messages, slip?.current_deed, slip?.recent_deeds]);

  const deedIds = useMemo(() => new Set(deeds.map((item) => item.id)), [deeds]);
  const currentDeed = useMemo(() => deeds.find((item) => item.status === "running" || item.status === "settling") || deeds[0] || null, [deeds]);
  const slipDag = useMemo(() => normalizeDag(slip?.dag, slip?.plan || slip?.design || {}), [slip?.dag, slip?.plan, slip?.design]);
  const triggerType = useMemo(() => resolvedTriggerType(slip, neighbors), [neighbors, slip]);

  const ensureDeedDetail = useCallback(async (targetDeedId) => {
    if (!targetDeedId || deedDetails[targetDeedId] || deedLoading[targetDeedId]) return;
    setDeedLoading((current) => ({ ...current, [targetDeedId]: true }));
    try {
      const [detailPayload, filePayload] = await Promise.all([
        getDeed(targetDeedId),
        getDeedOfferingFiles(targetDeedId).catch(() => ({ files: [] })),
      ]);
      const files = Array.isArray(filePayload?.files) ? filePayload.files : [];
      setDeedDetails((current) => ({ ...current, [targetDeedId]: detailPayload }));
      setDeedFiles((current) => ({ ...current, [targetDeedId]: files }));
      const previewable = files.find((file) => String(file?.preview_type || "").toLowerCase() === "text" && String(file?.download_path || "").trim());
      if (previewable?.download_path) {
        fetch(previewable.download_path)
          .then((response) => (response.ok ? response.text() : ""))
          .then((text) => {
            if (!text) return;
            setDeedPreviews((current) => ({ ...current, [targetDeedId]: shortText(text, 520) }));
          })
          .catch(() => {});
      }
    } catch (detailError) {
      setError(detailError.message || "行事详情载入失败。");
    } finally {
      setDeedLoading((current) => ({ ...current, [targetDeedId]: false }));
    }
  }, [deedDetails, deedLoading]);

  useEffect(() => {
    if (!deedId) return;
    setExpandedDeedId(String(deedId));
    setScrollTargetId(`deed-block-${deedId}`);
    setDockFocused(true);
    ensureDeedDetail(String(deedId));
  }, [deedId, ensureDeedDetail]);

  useEffect(() => {
    if (!currentDeed?.id) return;
    ensureDeedDetail(currentDeed.id);
  }, [currentDeed?.id, ensureDeedDetail]);

  useEffect(() => {
    if (!lastWsEvent?.event) return;
    const payload = lastWsEvent.payload || {};
    const targetDeedId = String(payload.deed_id || "");
    if (!targetDeedId || !deedIds.has(targetDeedId)) return;

    if (lastWsEvent.event === "deed_message") {
      setMessages((current) => mergeMessageRows(current, [{ ...payload, deed_id: targetDeedId }]));
      return;
    }

    if (lastWsEvent.event === "deed_progress") {
      const moveId = String(payload.move_id || "");
      const phase = String(payload.phase || "").toLowerCase();
      if (!moveId) return;
      const nextStatus = phase === "move_completed" ? "completed" : phase === "degraded" ? "failed" : "running";
      setLiveMoveStatuses((current) => ({
        ...current,
        [targetDeedId]: {
          ...(current[targetDeedId] || {}),
          [moveId]: nextStatus,
        },
      }));
      return;
    }

    if (["deed_closed", "deed_failed", "deed_settling"].includes(lastWsEvent.event)) {
      loadSlip({ silent: true });
      refreshSidebar?.();
    }
  }, [deedIds, lastWsEvent, loadSlip, refreshSidebar]);

  const flowItems = useMemo(() => {
    const deedById = new Map(deeds.map((deed) => [deed.id, deed]));
    const inserted = new Set();
    const items = [];
    const orderedMessages = [...messages].sort(
      (left, right) => new Date(left.created_utc || 0).getTime() - new Date(right.created_utc || 0).getTime(),
    );

    orderedMessages.forEach((message) => {
      const targetDeedId = String(message.deed_id || "");
      if (targetDeedId && deedById.has(targetDeedId) && !inserted.has(targetDeedId)) {
        items.push({ kind: "deed_block", deedId: targetDeedId });
        inserted.add(targetDeedId);
      }
      items.push({
        ...message,
        reaction: messageReactions[String(message.message_id || `${message.created_utc}|${message.content}`)] || "",
      });
    });

    deeds.forEach((deed) => {
      if (!inserted.has(deed.id)) {
        items.push({ kind: "deed_block", deedId: deed.id });
      }
    });

    return items;
  }, [deeds, messageReactions, messages]);

  const runSlipAction = async (runner, fallbackMessage) => {
    setComposerBusy(true);
    setError("");
    try {
      await runner();
      await Promise.all([loadSlip({ silent: true }), refreshSidebar?.()]);
    } catch (actionError) {
      setError(actionError.message || fallbackMessage);
    } finally {
      setComposerBusy(false);
    }
  };

  const handleSend = async () => {
    const text = composerValue.trim();
    if (!text || composerBusy) return;
    setComposerBusy(true);
    setError("");
    try {
      await sendSlipMessage(decodedSlug, text);
      setMessageHistory((current) => [...current.slice(-19), text]);
      setComposerValue("");
      setDockFocused(true);
      await Promise.all([loadSlip({ silent: true }), refreshSidebar?.()]);
    } catch (sendError) {
      setError(sendError.message || "消息发送失败。");
    } finally {
      setComposerBusy(false);
    }
  };

  const handleOpenDeed = async (targetDeedId) => {
    setExpandedDeedId((current) => (current === targetDeedId ? "" : targetDeedId));
    setScrollTargetId(targetDeedId ? `deed-block-${targetDeedId}` : "");
    setDockFocused(true);
    if (targetDeedId) {
      await ensureDeedDetail(targetDeedId);
    }
  };

  const handleRetryMessage = async (message) => {
    if (String(message.role || "").toLowerCase() === "user") {
      setComposerValue(String(message.content || ""));
      setDockFocused(true);
      return;
    }
    await runSlipAction(() => rerunSlip(decodedSlug), "重新执行失败。");
  };

  const handleCopyMessage = async (message) => {
    try {
      await navigator.clipboard.writeText(String(message.content || ""));
      const id = String(message.message_id || `${message.created_utc}|${message.content}`);
      setCopiedMessageId(id);
      window.setTimeout(() => setCopiedMessageId(""), 1400);
    } catch {
      setError("复制失败。");
    }
  };

  const handleRateMessage = (message, reaction) => {
    const id = String(message.message_id || `${message.created_utc}|${message.content}`);
    setMessageReactions((current) => ({
      ...current,
      [id]: current[id] === reaction ? "" : reaction,
    }));
  };

  const waitingPrev = (neighbors.prev || []).filter((item) => String(item.latest_deed_status || "") !== "closed");
  const canRunManual = triggerType === "manual";
  const showCurrentDeedAction = currentDeed && (currentDeed.status === "running" || currentDeed.status === "settling");

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center bg-[#F5F5F0]">
        <Loader2 className="animate-spin text-[#8d8b84]" />
      </div>
    );
  }

  if (!slip) {
    return (
      <div className="flex h-full items-center justify-center bg-[#F5F5F0] px-6 text-center text-[#6b6a68]">
        {error || "这张签札还没有被 Portal 读到。"}
      </div>
    );
  }

  return (
    <div className="h-full bg-[#F5F5F0]" data-testid="slip-page">
      <MoveGraphOverlay open={expandedMoveGraph} title="Move 全图" dag={slipDag} onClose={() => setExpandedMoveGraph(false)} />

      <div className="relative mx-auto flex h-full w-full max-w-[72rem] flex-col px-6 pb-6 pt-6">
        <div className="min-h-0 flex-1 overflow-y-auto pb-44" onPointerDownCapture={() => setDockFocused(false)}>
          {error ? <div className="mb-4 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{error}</div> : null}

          <div className="px-1 py-2">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[#8d8b84]">Slip</div>
                <div className="flex items-center gap-3">
                  <h1 className="portal-serif text-[1.92rem] leading-[2.25rem] text-[#1a1a18]">{slip.title}</h1>
                  {refreshing ? <Loader2 className="h-4 w-4 animate-spin text-[#8d8b84]" /> : null}
                </div>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                <span className="rounded-full bg-[#ece9df] px-3 py-1 text-xs font-medium text-[#6b6a68]">{triggerTypeLabel(triggerType)}</span>
              </div>
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-2 rounded-full bg-[#f8f7f2] px-3 py-1.5 text-[12px] text-[#6b6a68]">
                <Folder width={13} height={13} />
                {slip.folio ? (
                  <Link className="underline decoration-[#d5d0c2] underline-offset-4" to={`/folios/${encodeURIComponent(slip.folio.slug)}`}>
                    {slip.folio.title}
                  </Link>
                ) : (
                  "卷外"
                )}
              </span>

              {triggerType === "timer" ? (
                <span className="inline-flex items-center gap-2 rounded-full bg-[#f8f7f2] px-3 py-1.5 text-[12px] text-[#6b6a68]">
                  <Clock3 width={13} height={13} />
                  {slip.cadence?.next_trigger_utc ? `下次 ${formatDateTime(slip.cadence.next_trigger_utc)}` : "待下一次"}
                </span>
              ) : null}

              {triggerType === "writ_chain" ? (
                <span className="inline-flex items-center gap-2 rounded-full bg-[#f8f7f2] px-3 py-1.5 text-[12px] text-[#6b6a68]">
                  {waitingPrev.length ? `等待前序 ${waitingPrev.length}` : "前序已满足"}
                </span>
              ) : null}
            </div>

            <div className="mt-5 flex flex-wrap gap-2">
              {showCurrentDeedAction ? (
                <button
                  type="button"
                  data-testid="slip-current-deed-button"
                  onClick={() => handleOpenDeed(currentDeed.id)}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a]"
                >
                  <RefreshCw width={15} height={15} />
                  查看当前行事
                </button>
              ) : null}
              {canRunManual && !showCurrentDeedAction ? (
                <button
                  type="button"
                  data-testid="slip-run-button"
                  onClick={() => runSlipAction(() => rerunSlip(decodedSlug), "执行失败。")}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a]"
                >
                  <Play width={15} height={15} />
                  执行
                </button>
              ) : null}
              {triggerType === "writ_chain" && !showCurrentDeedAction ? (
                <button
                  type="button"
                  data-testid="slip-trigger-button"
                  disabled={waitingPrev.length > 0}
                  onClick={() => runSlipAction(() => rerunSlip(decodedSlug), "执行失败。")}
                  className="inline-flex items-center gap-2 rounded-xl bg-[#f1eee5] px-3 py-2 text-sm text-[#1a1a18] transition disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Play width={15} height={15} />
                  触发执行
                </button>
              ) : null}
            </div>
          </div>

          <div className="mt-6 px-1 py-1">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
                <Waypoints width={16} height={16} />
                <span>Move 结构</span>
              </div>
              <button
                type="button"
                data-testid="slip-move-detail"
                onClick={() => setExpandedMoveGraph(true)}
                title="查看全图"
                className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#fbfaf7] text-[#6b6a68] transition hover:bg-white"
              >
                <Search width={15} height={15} />
              </button>
            </div>
            <div className="mt-4">
              <MoveGraphCanvas dag={slipDag} mode="structure" compact testId="slip-move-graph" />
            </div>
          </div>

          <DeedHistoryStrip deeds={deeds} activeDeedId={expandedDeedId} onOpenDeed={handleOpenDeed} />
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10">
          <ConversationDock
            ownerLabel="Slip"
            composerPlaceholder="继续这张札"
            focused={dockFocused}
            onFocusChange={setDockFocused}
            messages={flowItems}
            composerValue={composerValue}
            onComposerChange={setComposerValue}
            onComposerSubmit={handleSend}
            onComposerHistoryUp={() => setComposerValue(messageHistory[messageHistory.length - 1] || "")}
            composerDisabled={composerBusy}
            composerLoading={composerBusy}
            onRetryMessage={handleRetryMessage}
            onEditMessage={(message) => {
              setComposerValue(String(message.content || ""));
              setDockFocused(true);
            }}
            onCopyMessage={handleCopyMessage}
            onRateMessage={handleRateMessage}
            copiedMessageId={copiedMessageId}
            testIdPrefix="slip-dock"
            renderMessage={(item) => {
              if (item.kind !== "deed_block") return null;
              const deed = deeds.find((row) => row.id === item.deedId);
              if (!deed) return null;
              return (
                <DeedBlock
                  slipDag={slipDag}
                  deed={deed}
                  detail={deedDetails[deed.id]}
                  files={deedFiles[deed.id] || []}
                  previewText={deedPreviews[deed.id] || ""}
                  expanded={expandedDeedId === deed.id}
                  loading={Boolean(deedLoading[deed.id])}
                  runtimeStatuses={liveMoveStatuses[deed.id] || {}}
                  onToggle={() => handleOpenDeed(deed.id)}
                  onPause={() => runSlipAction(() => pauseDeed(deed.id), "暂停失败。")}
                  onResume={() => runSlipAction(() => resumeDeed(deed.id), "恢复失败。")}
                  onSettle={() => runSlipAction(() => updateSlipStance(decodedSlug, "settle"), "收束失败。")}
                />
              );
            }}
            getMessageKey={(item, index) =>
              item.kind === "deed_block"
                ? `deed-block:${item.deedId}`
                : String(item.message_id || `${item.deed_id || "none"}|${item.created_utc || ""}|${index}`)
            }
            getMessageId={(item) => (item.kind === "deed_block" ? `deed-block-${item.deedId}` : "")}
            scrollToMessageId={scrollTargetId}
          />
        </div>
      </div>
    </div>
  );
}
