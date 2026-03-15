import { useEffect, useRef } from "react";

function TypingIndicator() {
  return (
    <div className="msg-bubble msg-assistant inline-flex items-center gap-0.5 py-3">
      <span className="typing-dot" />
      <span className="typing-dot" />
      <span className="typing-dot" />
    </div>
  );
}

function formatContent(text) {
  // Simple markdown-ish rendering: code blocks, inline code, paragraphs
  if (!text) return null;

  const parts = text.split(/(```[\s\S]*?```)/g);
  return parts.map((part, i) => {
    if (part.startsWith("```")) {
      const inner = part.slice(3, -3).replace(/^\w+\n/, "");
      return (
        <pre key={i}>
          <code>{inner}</code>
        </pre>
      );
    }
    // Inline code
    const inlined = part.split(/(`[^`]+`)/g).map((seg, j) => {
      if (seg.startsWith("`") && seg.endsWith("`")) {
        return <code key={j}>{seg.slice(1, -1)}</code>;
      }
      // Split by newlines for paragraphs
      return seg.split("\n\n").map((p, k) => (
        <p key={`${j}-${k}`}>{p}</p>
      ));
    });
    return <span key={i}>{inlined}</span>;
  });
}

function Message({ msg }) {
  const roleClass =
    msg.role === "user"
      ? "msg-user"
      : msg.role === "system"
        ? "msg-system"
        : "msg-assistant";

  const align =
    msg.role === "user"
      ? "justify-end"
      : msg.role === "system"
        ? "justify-center"
        : "justify-start";

  return (
    <div className={`flex ${align} mb-3`}>
      <div className={`msg-bubble ${roleClass}`}>
        {formatContent(msg.content)}
      </div>
    </div>
  );
}

export default function MessageThread({ messages, isLoading }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-1">
      {messages.length === 0 && !isLoading && (
        <div className="flex items-center justify-center h-full text-gray-500 text-sm">
          Send a message to start the conversation.
        </div>
      )}

      {messages.map((msg, i) => (
        <Message key={msg.id || i} msg={msg} />
      ))}

      {isLoading && (
        <div className="flex justify-start mb-3">
          <TypingIndicator />
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
