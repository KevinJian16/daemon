import { Loader2, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import ConversationDock from "./ConversationDock";
import { createVoiceSession, sendVoiceMessage } from "../lib/api";

function prefixMessage(scope, folioTitle, text) {
  const clean = String(text || "").trim();
  if (scope === "folio" && folioTitle) {
    return `围绕卷《${folioTitle}》新增一件事：${clean}`;
  }
  return clean;
}

export default function VoiceSheet({
  open,
  scope = "desk",
  folioTitle = "",
  onClose,
  onDraftsChanged = null,
  onDraftCreated = null,
  testId = "voice-sheet",
}) {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [composerValue, setComposerValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) {
      setSessionId("");
      setMessages([]);
      setComposerValue("");
      setBusy(false);
      setError("");
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError("");
    createVoiceSession()
      .then((payload) => {
        if (cancelled) return;
        setSessionId(String(payload?.session_id || ""));
      })
      .catch((createError) => {
        if (cancelled) return;
        setError(createError.message || "Voice 暂时不可用。");
      })
      .finally(() => {
        if (!cancelled) {
          setBusy(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const handleKeydown = (event) => {
      if (event.key === "Escape") {
        onClose?.();
      }
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [onClose, open]);

  const handleSend = async () => {
    const text = composerValue.trim();
    if (!text || !sessionId || busy) return;
    const outgoing = {
      message_id: `voice-user-${Date.now()}`,
      role: "user",
      content: text,
      created_utc: new Date().toISOString(),
    };
    setMessages((current) => [...current, outgoing]);
    setComposerValue("");
    setBusy(true);
    setError("");

    try {
      const result = await sendVoiceMessage(sessionId, { message: prefixMessage(scope, folioTitle, text) });
      const incoming = {
        message_id: `voice-assistant-${Date.now()}`,
        role: "assistant",
        content: String(result?.content || "Voice 暂时没有给出结果。"),
        created_utc: new Date().toISOString(),
      };
      setMessages((current) => [...current, incoming]);
      await onDraftsChanged?.();
      const draftId = String(result?.plan?.metadata?.draft_id || "");
      if (draftId) {
        onDraftCreated?.(draftId, result?.plan?.metadata || {});
      }
    } catch (sendError) {
      setError(sendError.message || "Voice 暂时没有收敛出结果。");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <div
      data-testid={testId}
      className="fixed inset-0 z-50 bg-[#F5F5F0]/84 backdrop-blur-sm"
      onMouseDown={(event) => event.target === event.currentTarget && onClose?.()}
    >
      <div className="absolute inset-x-0 bottom-0 mx-auto w-full max-w-[68rem] px-6 pb-6">
        <div className="overflow-hidden rounded-[2rem] border border-[rgba(0,0,0,0.05)] bg-[#F5F5F0] shadow-[0_28px_80px_rgba(41,41,41,0.14)]">
          <div className="px-6 pb-2 pt-5">
            <div className="flex items-center gap-2 text-sm font-medium text-[#1a1a18]">
              <Sparkles width={16} height={16} />
              <span>{scope === "folio" ? `在卷《${folioTitle}》中收敛新草稿` : "收敛一件新事"}</span>
            </div>
          </div>

          {error ? <div className="mx-6 mb-2 rounded-2xl border border-[#ead1ca] bg-[#f8ebe7] px-4 py-3 text-sm text-[#8b3c2f]">{error}</div> : null}

          {!sessionId && busy ? (
            <div className="flex h-[18rem] items-center justify-center">
              <Loader2 className="animate-spin text-[#8d8b84]" />
            </div>
          ) : (
            <div className="px-2 pb-2">
              <ConversationDock
                ownerLabel="Voice"
                focused
                onFocusChange={() => {}}
                messages={messages}
                composerValue={composerValue}
                onComposerChange={setComposerValue}
                onComposerSubmit={handleSend}
                composerDisabled={!sessionId || busy}
                composerLoading={busy}
                testIdPrefix={`${testId}-dock`}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
