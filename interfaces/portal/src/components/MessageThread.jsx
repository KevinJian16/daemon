import { ArrowDown, Copy, PencilLine, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cx, formatChatTime } from "../lib/format";

function Markdown({ children }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      className="portal-markdown"
      components={{
        a: ({ node, ...props }) => <a {...props} className="underline underline-offset-2" target="_blank" rel="noreferrer" />,
      }}
    >
      {children || ""}
    </ReactMarkdown>
  );
}

function UserMessage({ message, onRetryMessage, onEditMessage }) {
  const showActions = Boolean(onRetryMessage || onEditMessage);
  return (
    <div className="group/user relative inline-flex max-w-[75ch] flex-col rounded-xl bg-[#DDD9CE] px-3.5 py-2.5 text-[#1a1a18]">
      <div className="relative grid grid-cols-1 gap-2 py-0.5">
        <div className="whitespace-pre-wrap">
          <Markdown>{message.content}</Markdown>
        </div>
      </div>
      {showActions ? (
        <div className="pointer-events-none absolute bottom-0 right-2">
          <div className="pointer-events-auto min-w-max translate-x-1 translate-y-4 rounded-lg border border-[#00000015] bg-white p-0.5 opacity-0 shadow-sm transition group-hover/user:translate-x-0.5 group-hover/user:opacity-100 group-focus-within/user:translate-x-0.5 group-focus-within/user:opacity-100">
            <div className="flex items-center text-[#6b6a68]">
              {onRetryMessage ? (
                <button
                  type="button"
                  onClick={() => onRetryMessage(message)}
                  className="flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-[#f5f5f0]"
                >
                  <RefreshCw width={18} height={18} />
                </button>
              ) : null}
              {onEditMessage ? (
                <button
                  type="button"
                  onClick={() => onEditMessage(message)}
                  className="flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-[#f5f5f0]"
                >
                  <PencilLine width={18} height={18} />
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function AssistantMessage({ message, onCopyMessage, onRetryMessage, onRateMessage, copiedMessageId }) {
  const showActions = Boolean(onCopyMessage || onRetryMessage || onRateMessage);
  return (
    <div className="group/assistant relative mb-10 font-serif">
      <div className="relative leading-[1.65rem]">
        <div className="grid grid-cols-1 gap-2.5">
          <div className="pr-8 pl-2 text-[#1a1a18]">
            <Markdown>{message.content}</Markdown>
          </div>
        </div>
      </div>
      {showActions ? (
        <div className="pointer-events-none absolute bottom-0 left-2">
          <div className="pointer-events-auto flex min-w-max translate-y-full items-center gap-0.5 rounded-lg border border-[#00000015] bg-white p-0.5 opacity-0 shadow-sm transition group-hover/assistant:opacity-100 group-focus-within/assistant:opacity-100">
            <div className="flex items-center text-[#6b6a68]">
              {onCopyMessage ? (
                <button
                  type="button"
                  onClick={() => onCopyMessage(message)}
                  className={cx(
                    "flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-[#f5f5f0]",
                    copiedMessageId === message.message_id ? "bg-[#f5f5f0] text-[#1a1a18]" : "",
                  )}
                >
                  <Copy width={18} height={18} />
                </button>
              ) : null}
              {onRateMessage ? (
                <button
                  type="button"
                  onClick={() => onRateMessage(message, "up")}
                  className={cx(
                    "flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-[#f5f5f0]",
                    message.reaction === "up" ? "bg-[#f5f5f0] text-[#1a1a18]" : "",
                  )}
                >
                  <ThumbsUp width={16} height={16} />
                </button>
              ) : null}
              {onRateMessage ? (
                <button
                  type="button"
                  onClick={() => onRateMessage(message, "down")}
                  className={cx(
                    "flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-[#f5f5f0]",
                    message.reaction === "down" ? "bg-[#f5f5f0] text-[#1a1a18]" : "",
                  )}
                >
                  <ThumbsDown width={16} height={16} />
                </button>
              ) : null}
              {onRetryMessage ? (
                <button
                  type="button"
                  onClick={() => onRetryMessage(message)}
                  className="flex h-8 w-8 items-center justify-center rounded-md transition hover:bg-[#f5f5f0]"
                >
                  <RefreshCw width={18} height={18} />
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function SystemMessage({ message }) {
  const content = String(message.content || "").replace(/^\[操作\]\s*/, "");
  return (
    <div className="flex justify-center py-1">
      <span className="rounded-full border border-[rgba(0,0,0,0.06)] bg-[#f8f7f2] px-3 py-1 text-[11px] text-[#7e7b75]">
        {content}
      </span>
    </div>
  );
}

export default function MessageThread({
  messages,
  onRetryMessage = null,
  onEditMessage = null,
  onCopyMessage = null,
  onRateMessage = null,
  copiedMessageId = "",
  embedded = false,
  revealed = true,
  renderItem = null,
  getItemKey = null,
  getItemId = null,
  scrollToItemId = "",
  testIdPrefix = "message-thread",
}) {
  const endRef = useRef(null);
  const scrollRef = useRef(null);
  const previousLengthRef = useRef(messages.length);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [hasPendingNewer, setHasPendingNewer] = useState(false);

  function syncScrollState() {
    const node = scrollRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    const nearBottom = distance < 40;
    setIsNearBottom(nearBottom);
    if (nearBottom) {
      setHasPendingNewer(false);
    }
  }

  function scrollToBottom(behavior = "smooth") {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTo({ top: node.scrollHeight, behavior });
    setHasPendingNewer(false);
  }

  useEffect(() => {
    if (!messages.length) return;
    const previousLength = previousLengthRef.current;
    const appended = messages.length > previousLength;
    previousLengthRef.current = messages.length;

    if (!appended) return;
    if (isNearBottom) {
      window.requestAnimationFrame(() => scrollToBottom("smooth"));
    } else {
      setHasPendingNewer(true);
    }
  }, [isNearBottom, messages.length, messages[messages.length - 1]?.message_id]);

  useEffect(() => {
    if (!embedded) {
      const node = endRef.current;
      if (!node || !messages.length) return;
      node.scrollIntoView({ block: "end", behavior: "smooth" });
      return;
    }
    if (revealed) {
      window.requestAnimationFrame(() => scrollToBottom("auto"));
      return;
    }
    syncScrollState();
  }, [embedded, revealed]);

  useEffect(() => {
    if (!embedded || !revealed || !scrollToItemId) return;
    const node = scrollRef.current;
    if (!node) return;
    const target = node.querySelector(`[data-thread-item-id="${scrollToItemId}"]`);
    if (!(target instanceof HTMLElement)) return;
    window.requestAnimationFrame(() => {
      target.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  }, [embedded, revealed, scrollToItemId, messages.length]);

  if (!messages.length) {
    return <div className={embedded ? "h-full" : "min-h-[1px]"} />;
  }

  const body = (
    <>
      {messages.map((message, index) => (
        <div
          key={
            getItemKey?.(message, index) ||
            String(message.message_id || message.id || message.created_utc || `${message.kind || "item"}-${index}`)
          }
          data-thread-item-id={getItemId?.(message, index) || undefined}
          className="group relative mx-auto mb-4 mt-1 block w-full max-w-3xl"
        >
          {(() => {
            const custom = renderItem?.(message, index);
            if (custom !== null && custom !== undefined) {
              return custom;
            }

            const role = String(message.role || "").toLowerCase();
            if (role === "system") {
              return <SystemMessage message={message} />;
            }
            if (role === "user") {
              return (
                <div className="flex flex-col items-end gap-1">
                  <UserMessage message={message} onRetryMessage={onRetryMessage} onEditMessage={onEditMessage} />
                  <span className="pr-2 text-[11px] text-[#9a9893]">{formatChatTime(message.created_utc)}</span>
                </div>
              );
            }
            return (
              <div className="flex flex-col gap-1">
                <AssistantMessage
                  message={message}
                  onCopyMessage={onCopyMessage}
                  onRetryMessage={onRetryMessage}
                  onRateMessage={onRateMessage}
                  copiedMessageId={copiedMessageId}
                />
                <span className="pl-2 text-[11px] text-[#9a9893]">{formatChatTime(message.created_utc)}</span>
              </div>
            );
          })()}
        </div>
      ))}
      <div ref={endRef} className="h-3" />
    </>
  );

  if (embedded) {
    return (
      <div className="relative flex h-full min-h-0 flex-col">
        <div ref={scrollRef} onScroll={syncScrollState} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-8 pt-3">
          <div data-testid={`${testIdPrefix}-scroll`}>{body}</div>
        </div>

        {!isNearBottom || hasPendingNewer ? (
          <button
            type="button"
            onClick={() => scrollToBottom("smooth")}
            data-testid={`${testIdPrefix}-scroll-bottom`}
            className="absolute bottom-3 left-1/2 inline-flex h-9 w-9 -translate-x-1/2 items-center justify-center rounded-full border border-[rgba(0,0,0,0.08)] bg-white text-[#1a1a18] shadow-claude transition hover:bg-[#f5f5f0]"
          >
            <ArrowDown width={16} height={16} />
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <div className="mx-auto mt-8 block w-full max-w-3xl">
      {body}
    </div>
  );
}
