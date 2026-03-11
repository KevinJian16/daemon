import {
  ChevronDown,
  ChevronUp,
  GripVertical,
  Layers3,
  Link2,
  Loader2,
  Rows3,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import Composer from "./Composer";
import { getFolio, reorderFolio } from "../lib/api";
import { cx, deedStatusLabel, formatDateTime, shortText } from "../lib/format";

function SurfaceCard({ children, className = "" }) {
  return (
    <div className={cx("rounded-[1.35rem] border border-[rgba(0,0,0,0.06)] bg-white shadow-claude", className)}>
      {children}
    </div>
  );
}

function FocusSlipCard({ slip }) {
  const navigate = useNavigate();
  if (!slip) {
    return (
      <SurfaceCard className="p-6">
        <h2 className="portal-serif text-[1.4rem] text-[#1a1a18]">当前焦点签札</h2>
        <p className="mt-3 text-sm leading-6 text-[#6b6a68]">卷里还没有签札，所以这里暂时为空。</p>
      </SurfaceCard>
    );
  }

  return (
    <SurfaceCard className="overflow-hidden">
      <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
        <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Focus Slip</div>
        <h2 className="portal-serif mt-2 text-[1.55rem] leading-8 text-[#1a1a18]">{slip.title}</h2>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-[#6b6a68]">{slip.objective || "这张签札还没有目标摘要。"}</p>
      </div>
      <div className="flex flex-wrap items-center gap-4 px-6 py-5 text-sm">
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">状态</div>
          <div className="mt-2 font-medium text-[#1a1a18]">{deedStatusLabel(slip.deed?.status)}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">结果</div>
          <div className="mt-2 font-medium text-[#1a1a18]">{slip.result_ready ? "已产出" : "未产出"}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">更新</div>
          <div className="mt-2 font-medium text-[#1a1a18]">{formatDateTime(slip.updated_utc)}</div>
        </div>
        <button
          type="button"
          onClick={() => navigate(`/slips/${encodeURIComponent(slip.slug)}`)}
          className="ml-auto inline-flex items-center gap-2 rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a]"
        >
          <Link2 width={15} height={15} />
          打开签札
        </button>
      </div>
    </SurfaceCard>
  );
}

function ReadDeck({ slips, focusedId, onFocus }) {
  const visible = slips.slice(0, 5);

  return (
    <div className="relative h-[320px]">
      {visible.map((slip, index) => {
        const isFocused = slip.id === focusedId;
        const offset = index * 24;
        const scale = isFocused ? 1 : Math.max(0.82, 1 - index * 0.04);
        const zIndex = isFocused ? 30 : visible.length - index;
        return (
          <button
            key={slip.id}
            type="button"
            onClick={() => onFocus(slip.id)}
            className={cx(
              "absolute left-1/2 w-full max-w-[42rem] -translate-x-1/2 rounded-[1.35rem] border px-5 py-5 text-left shadow-claude transition-all duration-300",
              isFocused
                ? "border-[rgba(0,0,0,0.1)] bg-white"
                : "border-[rgba(0,0,0,0.06)] bg-[#f8f7f2] hover:bg-white",
            )}
            style={{
              top: `${offset}px`,
              transform: `translateX(-50%) scale(${scale})`,
              zIndex,
            }}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="truncate text-base font-medium text-[#1a1a18]">{slip.title}</div>
                <div className="mt-2 line-clamp-2 text-sm leading-6 text-[#6b6a68]">{slip.objective || "没有目标摘要"}</div>
              </div>
              <div className="shrink-0 rounded-full bg-[#ece9df] px-2.5 py-1 text-[11px] text-[#6b6a68]">{deedStatusLabel(slip.deed?.status)}</div>
            </div>
            <div className="mt-4 flex items-center gap-3 text-xs text-[#8d8b84]">
              <span>{slip.result_ready ? "有结果" : "无结果"}</span>
              <span>·</span>
              <span>{formatDateTime(slip.updated_utc)}</span>
              {slip.cadence?.active ? (
                <>
                  <span>·</span>
                  <span>节律中</span>
                </>
              ) : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}

function ArrangeDeck({ slips, onCommit }) {
  const [draftOrder, setDraftOrder] = useState(slips);
  const [draggingId, setDraggingId] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraftOrder(slips);
  }, [slips]);

  const moveBefore = (targetId) => {
    if (!draggingId || draggingId === targetId) return;
    const current = [...draftOrder];
    const dragIndex = current.findIndex((item) => item.id === draggingId);
    const targetIndex = current.findIndex((item) => item.id === targetId);
    if (dragIndex < 0 || targetIndex < 0) return;
    const [dragged] = current.splice(dragIndex, 1);
    current.splice(targetIndex, 0, dragged);
    setDraftOrder(current);
  };

  const commitOrder = async () => {
    setSaving(true);
    try {
      await onCommit(draftOrder.map((item) => item.id));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="space-y-2">
        {draftOrder.map((slip) => (
          <div
            key={slip.id}
            draggable
            onDragStart={() => setDraggingId(slip.id)}
            onDragOver={(event) => {
              event.preventDefault();
              moveBefore(slip.id);
            }}
            onDragEnd={() => setDraggingId("")}
            className={cx(
              "flex items-center gap-3 rounded-2xl border border-[rgba(0,0,0,0.06)] bg-white px-4 py-3 text-sm shadow-sm transition",
              draggingId === slip.id && "opacity-70",
            )}
          >
            <GripVertical width={16} height={16} className="text-[#9a9893]" />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium text-[#1a1a18]">{slip.title}</div>
              <div className="truncate text-xs text-[#6b6a68]">{shortText(slip.objective, 60)}</div>
            </div>
            <div className="shrink-0 text-[11px] text-[#8d8b84]">{deedStatusLabel(slip.deed?.status)}</div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={commitOrder}
          disabled={saving}
          className="rounded-xl bg-[#ae5630] px-3 py-2 text-sm text-white transition hover:bg-[#c4633a] disabled:opacity-50"
        >
          {saving ? "保存中…" : "提交卷内顺序"}
        </button>
      </div>
    </div>
  );
}

export default function FolioPage({ onSidebarRefresh, onGap }) {
  const { folioSlug } = useParams();
  const decodedSlug = decodeURIComponent(folioSlug || "");
  const [folio, setFolio] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [arrangeMode, setArrangeMode] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [focusedId, setFocusedId] = useState("");

  const loadFolio = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const payload = await getFolio(decodedSlug);
      setFolio(payload);
      if (!focusedId && payload?.slips?.[0]?.id) {
        setFocusedId(payload.slips[0].id);
      }
      onGap("Folio 页需要卷内对话后端，但当前没有 folio messages / folio message route。");
    } catch (loadError) {
      setError(loadError.message || "卷页装载失败。");
    } finally {
      setLoading(false);
    }
  }, [decodedSlug, focusedId, onGap]);

  useEffect(() => {
    loadFolio();
  }, [loadFolio]);

  const slips = useMemo(() => folio?.slips || [], [folio]);
  const focusedSlip = useMemo(() => slips.find((item) => item.id === focusedId) || slips[0] || null, [focusedId, slips]);
  const allVisibleSlips = showAll ? slips : slips.slice(0, 5);

  const commitOrder = async (orderedIds) => {
    try {
      await reorderFolio(decodedSlug, orderedIds);
      await Promise.all([loadFolio(), onSidebarRefresh?.()]);
    } catch (actionError) {
      setError(actionError.message || "卷内顺序保存失败。");
    }
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
    <div className="flex h-full flex-col bg-[#F5F5F0]">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[58rem] flex-col px-4 pb-12 pt-10">
          {error ? <div className="mb-4 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{error}</div> : null}

          <SurfaceCard className="overflow-hidden">
            <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Folio</div>
              <h1 className="portal-serif mt-2 text-[2rem] leading-[2.35rem] text-[#1a1a18]">{folio.title}</h1>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-[#6b6a68]">{folio.summary || "这卷还没有摘要。"}</p>
            </div>
            <div className="grid gap-4 px-6 py-5 text-sm md:grid-cols-4">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">签札</div>
                <div className="mt-2 font-medium text-[#1a1a18]">{folio.slip_count || 0}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">进行中</div>
                <div className="mt-2 font-medium text-[#1a1a18]">{folio.live_slip_count || 0}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">待收束</div>
                <div className="mt-2 font-medium text-[#1a1a18]">{folio.review_slip_count || 0}</div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">最近更新</div>
                <div className="mt-2 font-medium text-[#1a1a18]">{formatDateTime(folio.updated_utc)}</div>
              </div>
            </div>
          </SurfaceCard>

          <SurfaceCard className="mt-6 px-6 py-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
              <Rows3 width={16} height={16} />
              <span>卷内对话区</span>
            </div>
            <p className="text-sm leading-6 text-[#6b6a68]">
              这块前端壳已经留好了 Claude 式对话区，但当前后端没有 folio message / folio messages 路由，所以这里只能停在静态壳。
            </p>
          </SurfaceCard>

          <div className="mt-6">
            <FocusSlipCard slip={focusedSlip} />
          </div>

          <SurfaceCard className="mt-6 overflow-hidden">
            <div className="flex items-center justify-between border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Slip Deck</div>
                <h2 className="portal-serif mt-2 text-[1.45rem] leading-8 text-[#1a1a18]">卷内签札卡阵</h2>
              </div>
              <div className="flex items-center gap-2 rounded-2xl bg-[#f5f5f0] p-1">
                <button
                  type="button"
                  onClick={() => setArrangeMode(false)}
                  className={cx(
                    "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition",
                    !arrangeMode ? "bg-white text-[#1a1a18] shadow-sm" : "text-[#6b6a68]",
                  )}
                >
                  <Layers3 width={15} height={15} />
                  阅读
                </button>
                <button
                  type="button"
                  onClick={() => setArrangeMode(true)}
                  className={cx(
                    "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition",
                    arrangeMode ? "bg-white text-[#1a1a18] shadow-sm" : "text-[#6b6a68]",
                  )}
                >
                  <GripVertical width={15} height={15} />
                  整理
                </button>
              </div>
            </div>
            <div className="px-6 py-6">
              {slips.length ? (
                arrangeMode ? (
                  <ArrangeDeck slips={slips} onCommit={commitOrder} />
                ) : (
                  <ReadDeck slips={slips} focusedId={focusedSlip?.id} onFocus={setFocusedId} />
                )
              ) : (
                <p className="text-sm leading-6 text-[#6b6a68]">这卷还是空卷，所以没有卡阵可以排。</p>
              )}
            </div>
          </SurfaceCard>

          <SurfaceCard className="mt-6 overflow-hidden">
            <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Recent Results</div>
              <h2 className="portal-serif mt-2 text-[1.45rem] leading-8 text-[#1a1a18]">最近结果</h2>
            </div>
            <div className="px-6 py-5">
              {folio.recent_results?.length ? (
                <div className="space-y-2">
                  {folio.recent_results.map((item) => (
                    <Link
                      key={`${item.deed_id}-${item.slip_id}`}
                      to={`/slips/${encodeURIComponent(item.slip_slug)}`}
                      className="flex items-center justify-between rounded-2xl bg-[#f5f5f0] px-4 py-3 text-sm transition hover:bg-[#ecebe4]"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium text-[#1a1a18]">{item.title}</div>
                        <div className="truncate text-xs text-[#6b6a68]">{item.slip_title}</div>
                      </div>
                      <div className="shrink-0 text-[11px] text-[#8d8b84]">{formatDateTime(item.updated_utc)}</div>
                    </Link>
                  ))}
                </div>
              ) : (
                <p className="text-sm leading-6 text-[#6b6a68]">这卷还没有最近结果可展示。</p>
              )}
            </div>
          </SurfaceCard>

          <SurfaceCard className="mt-6 overflow-hidden">
            <button
              type="button"
              onClick={() => setShowAll((value) => !value)}
              className="flex w-full items-center justify-between px-6 py-5 text-left"
            >
              <div>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">All Slips</div>
                <h2 className="portal-serif mt-2 text-[1.45rem] leading-8 text-[#1a1a18]">全部签札入口</h2>
              </div>
              {showAll ? <ChevronUp width={18} height={18} className="text-[#6b6a68]" /> : <ChevronDown width={18} height={18} className="text-[#6b6a68]" />}
            </button>
            {showAll ? (
              <div className="border-t border-[rgba(0,0,0,0.06)] px-6 py-5">
                {allVisibleSlips.length ? (
                  <div className="space-y-2">
                    {allVisibleSlips.map((slip) => (
                      <Link
                        key={slip.id}
                        to={`/slips/${encodeURIComponent(slip.slug)}`}
                        className="flex items-center justify-between rounded-2xl bg-[#f5f5f0] px-4 py-3 text-sm transition hover:bg-[#ecebe4]"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-medium text-[#1a1a18]">{slip.title}</div>
                          <div className="truncate text-xs text-[#6b6a68]">{shortText(slip.objective, 72)}</div>
                        </div>
                        <div className="shrink-0 text-[11px] text-[#8d8b84]">{deedStatusLabel(slip.deed?.status)}</div>
                      </Link>
                    ))}
                  </div>
                ) : (
                  <p className="text-sm leading-6 text-[#6b6a68]">没有卷内签札。</p>
                )}
              </div>
            ) : null}
          </SurfaceCard>
        </div>
      </div>

      <Composer
        value=""
        onChange={() => {}}
        onSubmit={() => {}}
        disabled
        metaLabel="Folio"
        placeholder="卷内对话后端未接入"
        note="当前只把 Folio 壳体接到了真实数据；卷内对话要等后端补 route。"
      />
    </div>
  );
}
