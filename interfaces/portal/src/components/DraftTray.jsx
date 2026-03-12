import { Check, Loader2, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { crystallizeDraft, updateDraft } from "../lib/api";
import { cx, formatDateTime, shortText } from "../lib/format";

function draftTitle(draft) {
  const brief = draft?.candidate_brief;
  const explicit = typeof brief?.title === "string" ? brief.title.trim() : "";
  if (explicit) return explicit;
  const objective = typeof brief?.objective === "string" ? brief.objective.trim() : "";
  if (objective) return shortText(objective, 18);
  return shortText(String(draft?.intent_snapshot || "").trim() || "未成札草稿", 18);
}

function draftObjective(draft) {
  const brief = draft?.candidate_brief;
  const objective = typeof brief?.objective === "string" ? brief.objective.trim() : "";
  if (objective) return objective;
  return String(draft?.intent_snapshot || "").trim();
}

function draftFadeClass(updatedUtc) {
  const ageHours = (Date.now() - new Date(updatedUtc || 0).getTime()) / 36e5;
  if (ageHours > 96) return "opacity-40";
  if (ageHours > 48) return "opacity-60";
  if (ageHours > 24) return "opacity-80";
  return "opacity-100";
}

export default function DraftTray({
  title = "Tray",
  drafts,
  workspaceFolioId = "",
  selectedDraftId = "",
  onSelectDraft = null,
  onDraftsChanged = null,
  onSlipCreated = null,
  testIdPrefix = "draft-tray",
}) {
  const draftingRows = useMemo(
    () =>
      (Array.isArray(drafts) ? drafts : [])
        .filter((row) => String(row?.status || "").toLowerCase() === "drafting")
        .sort((left, right) => new Date(right?.updated_utc || 0).getTime() - new Date(left?.updated_utc || 0).getTime()),
    [drafts],
  );
  const [expandedDraftId, setExpandedDraftId] = useState("");
  const [forms, setForms] = useState({});
  const formsRef = useRef({});
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const effectiveExpandedDraftId = String(selectedDraftId || expandedDraftId || "");

  useEffect(() => {
    const targetDraftId = String(selectedDraftId || "");
    if (!targetDraftId) return;
    if (!draftingRows.some((row) => String(row?.draft_id || "") === targetDraftId)) return;
    setExpandedDraftId(targetDraftId);
  }, [draftingRows, selectedDraftId]);

  const ensureForm = (draft) => {
    const draftId = String(draft?.draft_id || "");
    return (
      forms[draftId] || {
        title: draftTitle(draft),
        objective: draftObjective(draft),
      }
    );
  };

  const updateForm = (draftId, patch) => {
    formsRef.current = {
      ...formsRef.current,
      [draftId]: {
        ...(formsRef.current[draftId] || {}),
        ...patch,
      },
    };
    setForms((current) => ({
      ...current,
      [draftId]: {
        ...(current[draftId] || {}),
        ...patch,
      },
    }));
  };

  const toggleDraft = (draftId) => {
    const nextDraftId = effectiveExpandedDraftId === draftId ? "" : draftId;
    setExpandedDraftId(nextDraftId);
    onSelectDraft?.(nextDraftId);
    setError("");
  };

  const handleAbandon = async (draft) => {
    const draftId = String(draft?.draft_id || "");
    if (!draftId || busyAction) return;
    setBusyAction(`abandon:${draftId}`);
    setError("");
    try {
      await updateDraft(draftId, { status: "gone", sub_status: "abandoned" });
      await onDraftsChanged?.();
      setExpandedDraftId((current) => (current === draftId ? "" : current));
    } catch (actionError) {
      setError(actionError.message || "草稿暂时无法放弃。");
    } finally {
      setBusyAction("");
    }
  };

  const handleCrystallize = async (draft) => {
    const draftId = String(draft?.draft_id || "");
    if (!draftId || busyAction) return;
    const form = {
      ...ensureForm(draft),
      ...(formsRef.current[draftId] || {}),
    };
    const titleInput = document.querySelector(`[data-testid="${testIdPrefix}-title-${draftId}"]`);
    const objectiveInput = document.querySelector(`[data-testid="${testIdPrefix}-objective-${draftId}"]`);
    const titleValue = String(form.title || titleInput?.value || "").trim();
    const objectiveValue = String(form.objective || objectiveInput?.value || "").trim();
    if (!titleValue || !objectiveValue) {
      setError("成札前至少要有标题和目标。");
      setExpandedDraftId(draftId);
      return;
    }
    setBusyAction(`crystallize:${draftId}`);
    setError("");
    try {
      const slip = await crystallizeDraft(draftId, {
        title: titleValue,
        objective: objectiveValue,
        brief: draft?.candidate_brief || {},
        design: draft?.candidate_design || {},
        folio_id: workspaceFolioId || draft?.folio_id || undefined,
        standing: false,
      });
      await onDraftsChanged?.();
      setExpandedDraftId("");
      onSlipCreated?.(slip);
    } catch (actionError) {
      setError(actionError.message || "草稿暂时无法成札。");
    } finally {
      setBusyAction("");
    }
  };

  return (
    <section className="px-1 py-1" data-testid={`${testIdPrefix}-section`}>
      <div className="mb-4 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
        <Sparkles width={16} height={16} />
        <span>{title}</span>
      </div>

      {error ? <div className="mb-3 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{error}</div> : null}

      {!draftingRows.length ? (
        <div className="rounded-[1.55rem] border border-[rgba(0,0,0,0.05)] bg-[#f8f7f2] px-4 py-4 text-sm text-[#8d8b84]">
          托盘里还没有草稿。
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {draftingRows.map((draft) => {
            const draftId = String(draft?.draft_id || "");
            const expanded = effectiveExpandedDraftId === draftId;
            const form = ensureForm(draft);
            const isCrystallizing = busyAction === `crystallize:${draftId}`;
            const isAbandoning = busyAction === `abandon:${draftId}`;
            return (
              <article
                key={draftId}
                data-testid={`${testIdPrefix}-card-${draftId}`}
                className={cx(
                  "rounded-[1.65rem] border border-[rgba(0,0,0,0.05)] bg-[#faf8f5] px-4 py-4 shadow-[0_10px_28px_rgba(41,41,41,0.05),0_1px_0_rgba(255,255,255,0.75)_inset,0_-1px_0_rgba(41,41,41,0.04)_inset] transition",
                  draftFadeClass(draft?.updated_utc),
                  expanded ? "ring-1 ring-[rgba(174,86,48,0.16)]" : "hover:bg-[#fdfbf8]",
                )}
              >
                <button type="button" data-testid={`${testIdPrefix}-toggle-${draftId}`} onClick={() => toggleDraft(draftId)} className="w-full text-left">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-[15px] font-medium text-[#1a1a18]">{draftTitle(draft)}</div>
                      <div className="mt-2 text-[12px] leading-5 text-[#6b6a68]">{shortText(draftObjective(draft), expanded ? 108 : 52)}</div>
                    </div>
                    <div className="rounded-full bg-white/90 px-2.5 py-1 text-[11px] text-[#8d8b84]">
                      {String(draft?.source || "chat")}
                    </div>
                  </div>
                  <div className="mt-3 text-[11px] text-[#9a9893]">{formatDateTime(draft?.updated_utc || draft?.created_utc)}</div>
                </button>

                {expanded ? (
                  <div className="mt-4 space-y-3 border-t border-[rgba(0,0,0,0.05)] pt-4">
                    <input
                      data-testid={`${testIdPrefix}-title-${draftId}`}
                      value={form.title}
                      onChange={(event) => updateForm(draftId, { title: event.target.value })}
                      placeholder="标题"
                      className="w-full rounded-2xl border border-[rgba(0,0,0,0.06)] bg-white px-3 py-2.5 text-sm text-[#1a1a18] outline-none placeholder:text-[#9a9893]"
                    />
                    <textarea
                      data-testid={`${testIdPrefix}-objective-${draftId}`}
                      value={form.objective}
                      onChange={(event) => updateForm(draftId, { objective: event.target.value })}
                      rows={4}
                      placeholder="目标"
                      className="w-full resize-none rounded-[1.15rem] border border-[rgba(0,0,0,0.06)] bg-white px-3 py-3 text-sm leading-6 text-[#1a1a18] outline-none placeholder:text-[#9a9893]"
                    />
                    <div className="flex items-center justify-between gap-2">
                      <button
                        type="button"
                        data-testid={`${testIdPrefix}-abandon-${draftId}`}
                        onClick={() => handleAbandon(draft)}
                        disabled={Boolean(busyAction)}
                        title="放弃"
                        className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-white text-[#8d8b84] transition hover:bg-[#f2eee7] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isAbandoning ? <Loader2 className="h-4 w-4 animate-spin" /> : <X width={15} height={15} />}
                      </button>
                      <button
                        type="button"
                        data-testid={`${testIdPrefix}-crystallize-${draftId}`}
                        onClick={() => handleCrystallize(draft)}
                        disabled={Boolean(busyAction)}
                        title="成札"
                        className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-[#ae5630] text-white transition hover:bg-[#c4633a] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isCrystallizing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check width={15} height={15} />}
                      </button>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
