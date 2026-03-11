import {
  Copy,
  ExternalLink,
  FolderOutput,
  Loader2,
  Play,
  RefreshCw,
  TimerReset,
  Waypoints,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Composer from "./Composer";
import MessageThread from "./MessageThread";
import {
  copySlip,
  deleteSlipCadence,
  getSlip,
  getSlipMessages,
  getSlipResultFiles,
  rerunSlip,
  sendSlipMessage,
  setSlipCadence,
  takeOutSlip,
  updateSlipStance,
} from "../lib/api";
import {
  cx,
  deedStatusLabel,
  deedStatusTone,
  formatDateTime,
  shortText,
  slipStanceLabel,
} from "../lib/format";

function SurfaceCard({ children, className = "" }) {
  return (
    <div className={cx("rounded-[1.35rem] border border-[rgba(0,0,0,0.06)] bg-white shadow-claude", className)}>
      {children}
    </div>
  );
}

function ActionButton({ icon: Icon, label, onClick, disabled = false, subtle = false }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cx(
        "inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition",
        subtle
          ? "border border-[rgba(0,0,0,0.08)] bg-[#f5f5f0] text-[#1a1a18] hover:bg-[#ecebe4]"
          : "bg-[#ae5630] text-white hover:bg-[#c4633a]",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <Icon width={16} height={16} />
      <span>{label}</span>
    </button>
  );
}

function SlipHero({ slip, onRerun, onCopy, onTakeOut, onArchive, cadenceDraft, setCadenceDraft, onSaveCadence, onDisableCadence, cadenceSaving, actionBusy }) {
  const timeline = slip?.plan?.timeline || [];

  return (
    <SurfaceCard className="overflow-hidden">
      <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="mb-2 text-[11px] uppercase tracking-[0.18em] text-[#8d8b84]">Slip</div>
            <h1 className="portal-serif text-[2rem] leading-[2.35rem] text-[#1a1a18]">{slip.title}</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[#6b6a68]">{slip.objective || "这张签札还没有写下目标。"}</p>
          </div>
          <span className="rounded-full bg-[#ece9df] px-3 py-1 text-xs font-medium text-[#6b6a68]">
            {slipStanceLabel(slip.stance)}
          </span>
        </div>

        <div className="flex flex-wrap gap-2">
          <ActionButton icon={Play} label="开始执行" onClick={onRerun} disabled={actionBusy} />
          <ActionButton icon={Copy} label="复制" onClick={onCopy} disabled={actionBusy} subtle />
          {slip.folio ? <ActionButton icon={FolderOutput} label="移出卷" onClick={onTakeOut} disabled={actionBusy} subtle /> : null}
          <ActionButton icon={TimerReset} label="归档" onClick={onArchive} disabled={actionBusy} subtle />
        </div>
      </div>

      <div className="grid gap-0 border-b border-[rgba(0,0,0,0.06)] md:grid-cols-[1.15fr_0.85fr]">
        <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5 md:border-b-0 md:border-r">
          <div className="mb-4 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
            <Waypoints width={16} height={16} />
            <span>当前结构</span>
          </div>
          {timeline.length ? (
            <ol className="space-y-2">
              {timeline.map((item, index) => (
                <li key={item.id || index} className="flex items-start gap-3 rounded-2xl bg-[#f5f5f0] px-4 py-3">
                  <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white text-[11px] font-medium text-[#6b6a68]">
                    {index + 1}
                  </span>
                  <span className="text-sm leading-6 text-[#1a1a18]">{item.label}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-sm leading-6 text-[#6b6a68]">这张签札还没有结构化步骤，执行时会被后端拒绝。</p>
          )}
        </div>

        <div className="px-6 py-5">
          <div className="mb-4 text-sm font-medium text-[#1a1a18]">节律</div>
          <div className="rounded-2xl bg-[#f5f5f0] p-4">
            <p className="text-sm text-[#1a1a18]">
              {slip.cadence?.active ? `已启用 · ${slip.cadence.schedule}` : "未启用"}
            </p>
            <p className="mt-2 text-xs leading-5 text-[#6b6a68]">
              节律已接到后端 writ。输入框支持直接写后端当前接受的 schedule。
            </p>
            <div className="mt-4 flex flex-col gap-2">
              <input
                value={cadenceDraft}
                onChange={(event) => setCadenceDraft(event.target.value)}
                placeholder="例如：daily@09:00"
                className="rounded-xl border border-[rgba(0,0,0,0.08)] bg-white px-3 py-2 text-sm outline-none"
              />
              <div className="flex gap-2">
                <ActionButton icon={TimerReset} label="保存节律" onClick={onSaveCadence} disabled={cadenceSaving} subtle />
                <ActionButton icon={TimerReset} label="停用" onClick={onDisableCadence} disabled={cadenceSaving} subtle />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 px-6 py-5 text-sm md:grid-cols-4">
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">卷</div>
          <div className="mt-2 font-medium text-[#1a1a18]">
            {slip.folio ? (
              <Link className="underline decoration-[#d5d0c2] underline-offset-4" to={`/folios/${encodeURIComponent(slip.folio.slug)}`}>
                {slip.folio.title}
              </Link>
            ) : (
              "卷外"
            )}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">最近更新</div>
          <div className="mt-2 font-medium text-[#1a1a18]">{formatDateTime(slip.updated_utc)}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">消息数</div>
          <div className="mt-2 font-medium text-[#1a1a18]">{slip.message_count || 0}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">正式结果</div>
          <div className="mt-2 font-medium text-[#1a1a18]">{slip.result_ready ? "已产出" : "未产出"}</div>
        </div>
      </div>
    </SurfaceCard>
  );
}

function DeedCard({ slip, resultFiles, onRerun }) {
  const deed = slip.current_deed || slip.deed || {};
  const compareUnavailable = ["settling", "awaiting_eval"].includes(String(deed.status || "").toLowerCase());

  return (
    <SurfaceCard className="mt-6">
      <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Deed</div>
            <div className="mt-2 flex items-center gap-3">
              <h2 className="portal-serif text-[1.45rem] leading-8 text-[#1a1a18]">最近一次行事</h2>
              <span className={cx("rounded-full px-3 py-1 text-xs font-medium", deedStatusTone(deed.status))}>
                {deedStatusLabel(deed.status)}
              </span>
            </div>
          </div>
          <ActionButton icon={RefreshCw} label="再运行" onClick={onRerun} subtle />
        </div>
      </div>

      <div className="grid gap-0 md:grid-cols-[0.9fr_1.1fr]">
        <div className="border-b border-[rgba(0,0,0,0.06)] px-6 py-5 md:border-b-0 md:border-r">
          <div className="space-y-3 text-sm text-[#1a1a18]">
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">Deed ID</div>
              <div className="mt-2 break-all font-medium">{deed.id || "还没有 deed"}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">开始时间</div>
              <div className="mt-2 font-medium">{formatDateTime(deed.created_utc)}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-[#8d8b84]">反馈状态</div>
              <div className="mt-2 font-medium">{shortText(slip.feedback?.status || "未记录", 24)}</div>
            </div>
          </div>
        </div>

        <div className="px-6 py-5">
          <div className="mb-3 flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
            <FolderOutput width={16} height={16} />
            <span>正式结果</span>
          </div>
          {resultFiles.length ? (
            <div className="space-y-2">
              {resultFiles.map((file) => (
                <a
                  key={file.download}
                  href={file.download}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center justify-between rounded-2xl border border-[rgba(0,0,0,0.06)] bg-[#f5f5f0] px-4 py-3 text-sm transition hover:bg-[#ecebe4]"
                >
                  <span className="truncate">{file.name}</span>
                  <ExternalLink width={15} height={15} className="shrink-0 text-[#8d8b84]" />
                </a>
              ))}
            </div>
          ) : (
            <p className="text-sm leading-6 text-[#6b6a68]">这次 deed 还没有正式结果文件。</p>
          )}

          <div className="mt-5 rounded-2xl border border-dashed border-[rgba(0,0,0,0.09)] bg-[#fbfaf7] px-4 py-3">
            <div className="text-sm font-medium text-[#1a1a18]">比较与阶段页</div>
            <p className="mt-2 text-xs leading-5 text-[#6b6a68]">
              {compareUnavailable
                ? "当前 deed 已进入可评价阶段，但 Portal 还缺当前阶段页和候选比较接口。"
                : "当前状态下不需要比较；阶段页只会在 running / settling 内存在。"}
            </p>
          </div>
        </div>
      </div>
    </SurfaceCard>
  );
}

export default function SlipPage({ onSidebarRefresh, onGap }) {
  const { slipSlug } = useParams();
  const decodedSlug = decodeURIComponent(slipSlug || "");
  const [slip, setSlip] = useState(null);
  const [messages, setMessages] = useState([]);
  const [resultFiles, setResultFiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [composerValue, setComposerValue] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [cadenceDraft, setCadenceDraft] = useState("");
  const [cadenceSaving, setCadenceSaving] = useState(false);

  const loadSlip = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [slipData, messageData, resultData] = await Promise.all([
        getSlip(decodedSlug),
        getSlipMessages(decodedSlug),
        getSlipResultFiles(decodedSlug),
      ]);
      setSlip(slipData);
      setMessages(Array.isArray(messageData) ? messageData : []);
      setResultFiles(Array.isArray(resultData?.files) ? resultData.files : []);
      setCadenceDraft(slipData?.cadence?.schedule || "");
      if (String(slipData?.current_deed?.status || slipData?.deed?.status || "").toLowerCase() === "awaiting_eval") {
        onGap("Slip deed 已进入 awaiting_eval，但后端还没有阶段页或比较接口。");
      }
    } catch (loadError) {
      setError(loadError.message || "Portal 载入失败。");
    } finally {
      setLoading(false);
    }
  }, [decodedSlug, onGap]);

  useEffect(() => {
    loadSlip();
  }, [loadSlip]);

  const reloadAll = async () => {
    await Promise.all([loadSlip(), onSidebarRefresh?.()]);
  };

  const runAction = async (handler) => {
    setActionBusy(true);
    setError("");
    try {
      await handler();
      await reloadAll();
    } catch (actionError) {
      setError(actionError.message || "动作执行失败。");
    } finally {
      setActionBusy(false);
    }
  };

  const handleSend = async () => {
    const text = composerValue.trim();
    if (!text || actionBusy) return;
    setActionBusy(true);
    setError("");
    try {
      await sendSlipMessage(decodedSlug, text);
      setComposerValue("");
      await reloadAll();
    } catch (actionError) {
      setError(actionError.message || "消息发送失败。");
    } finally {
      setActionBusy(false);
    }
  };

  const handleSaveCadence = async () => {
    setCadenceSaving(true);
    setError("");
    try {
      await setSlipCadence(decodedSlug, cadenceDraft.trim(), true);
      await reloadAll();
    } catch (actionError) {
      setError(actionError.message || "节律保存失败。");
    } finally {
      setCadenceSaving(false);
    }
  };

  const handleDisableCadence = async () => {
    setCadenceSaving(true);
    setError("");
    try {
      await deleteSlipCadence(decodedSlug);
      await reloadAll();
    } catch (actionError) {
      setError(actionError.message || "节律停用失败。");
    } finally {
      setCadenceSaving(false);
    }
  };

  const sortedMessages = useMemo(() => {
    return [...messages].sort((left, right) => new Date(left.created_utc || 0).getTime() - new Date(right.created_utc || 0).getTime());
  }, [messages]);

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
    <div className="flex h-full flex-col bg-[#F5F5F0]">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-[58rem] flex-col px-4 pb-12 pt-10">
          {slip.folio ? (
            <Link to={`/folios/${encodeURIComponent(slip.folio.slug)}`} className="mb-4 text-sm text-[#8d8b84] hover:text-[#1a1a18]">
              返回卷宗 · {slip.folio.title}
            </Link>
          ) : null}

          {error ? <div className="mb-4 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{error}</div> : null}

          <SlipHero
            slip={slip}
            onRerun={() => runAction(() => rerunSlip(decodedSlug))}
            onCopy={() => runAction(() => copySlip(decodedSlug))}
            onTakeOut={() => runAction(() => takeOutSlip(decodedSlug))}
            onArchive={() => runAction(() => updateSlipStance(decodedSlug, "archive"))}
            cadenceDraft={cadenceDraft}
            setCadenceDraft={setCadenceDraft}
            onSaveCadence={handleSaveCadence}
            onDisableCadence={handleDisableCadence}
            cadenceSaving={cadenceSaving}
            actionBusy={actionBusy}
          />

          <DeedCard slip={slip} resultFiles={resultFiles} onRerun={() => runAction(() => rerunSlip(decodedSlug))} />

          <MessageThread
            messages={sortedMessages}
            emptyTitle="How can I help you today?"
            emptySubtitle="这张签札已经打开，但目前还没有对话。你可以先开始执行，或者直接在下方补记。"
          />
        </div>
      </div>

      <Composer
        value={composerValue}
        onChange={setComposerValue}
        onSubmit={handleSend}
        loading={actionBusy}
        disabled={actionBusy}
        placeholder="继续补记这张签札…"
        metaLabel={slip.folio ? "Slip" : "Loose Slip"}
        note="上传材料还没有接到后端材料集；当前只接文字补记。"
      />
    </div>
  );
}
