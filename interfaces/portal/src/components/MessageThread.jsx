import { useEffect, useRef } from "react";

function PulseBar({ sceneColor }) {
  return (
    <div className="animate-fade-in">
      <div className="h-0.5 w-48 rounded-full overflow-hidden bg-muted">
        <div
          className="h-full rounded-full animate-pulse-bar"
          style={{ backgroundColor: sceneColor }}
        />
      </div>
    </div>
  );
}

function EmptyState({ sceneName, sceneGreeting, sceneDesc }) {
  return (
    <div className="flex flex-col items-center justify-center h-full animate-fade-in px-6">
      <p className="text-lg font-medium text-foreground mb-2">
        {sceneGreeting}
      </p>
      <p className="text-sm text-muted-foreground text-center max-w-sm">
        {sceneDesc}
      </p>
    </div>
  );
}

function formatContent(text) {
  if (!text) return null;
  const parts = text.split(/(```[\s\S]*?```)/g);
  return parts.map((part, i) => {
    if (part.startsWith("```")) {
      const inner = part.slice(3, -3).replace(/^\w+\n/, "");
      return (
        <pre key={i} className="bg-foreground/5 rounded-xl p-3.5 my-2 overflow-x-auto text-xs font-mono">
          <code>{inner}</code>
        </pre>
      );
    }
    const inlined = part.split(/(`[^`]+`)/g).map((seg, j) => {
      if (seg.startsWith("`") && seg.endsWith("`")) {
        return (
          <code key={j} className="bg-foreground/5 px-1.5 py-0.5 rounded font-mono text-[12px]">
            {seg.slice(1, -1)}
          </code>
        );
      }
      return seg.split("\n\n").map((p, k) => (
        <p key={`${j}-${k}`}>{p}</p>
      ));
    });
    return <span key={i}>{inlined}</span>;
  });
}

function Message({ msg }) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center animate-fade-in my-2">
        <span className="text-xs text-muted-foreground bg-muted px-3 py-1.5 rounded-xl">
          {msg.content}
        </span>
      </div>
    );
  }

  if (isUser) {
    return (
      <div className="animate-fade-in flex justify-end">
        <div className="max-w-[85%] bg-secondary text-secondary-foreground rounded-2xl px-4 py-3 text-sm leading-relaxed">
          <p>{msg.content}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="text-sm leading-relaxed text-foreground">
        <div className="space-y-1">{formatContent(msg.content)}</div>
      </div>
    </div>
  );
}

export default function MessageThread({
  messages,
  isLoading,
  sceneName,
  sceneGreeting,
  sceneColor,
  sceneDesc,
}) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  return (
    <div className="flex-1 overflow-y-auto px-5 py-5 bg-gradient-to-b from-background to-muted/30">
      <div className="max-w-2xl mx-auto flex flex-col gap-5">
        {messages.length === 0 && !isLoading && (
          <EmptyState
            sceneName={sceneName}
            sceneGreeting={sceneGreeting}
            sceneDesc={sceneDesc}
          />
        )}

        {messages.map((msg, i) => (
          <Message key={msg.id || i} msg={msg} />
        ))}

        {isLoading && <PulseBar sceneColor={sceneColor} />}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
