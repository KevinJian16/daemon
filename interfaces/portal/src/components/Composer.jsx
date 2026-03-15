import { useState, useRef, useCallback } from "react";

export default function Composer({ onSend, disabled }) {
  const [text, setText] = useState("");
  const textareaRef = useRef(null);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
    // Reset height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [text, disabled, onSend]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleInput = (e) => {
    setText(e.target.value);
    // Auto-resize
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  return (
    <div className="border-t border-surface-3 px-4 py-3">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={disabled ? "Connecting..." : "Type a message... (Enter to send, Shift+Enter for newline)"}
          disabled={disabled}
          rows={1}
          className="flex-1 bg-surface-2 border border-surface-3 rounded-xl px-4 py-2.5 text-sm
                     text-gray-100 placeholder-gray-500 resize-none outline-none
                     focus:border-accent/50 focus:ring-1 focus:ring-accent/20
                     disabled:opacity-50 transition-colors"
        />
        <button
          onClick={handleSend}
          disabled={disabled || !text.trim()}
          className="bg-accent hover:bg-accent-hover disabled:bg-surface-3 disabled:text-gray-600
                     text-white rounded-xl px-4 py-2.5 text-sm font-medium
                     transition-colors shrink-0"
        >
          Send
        </button>
      </div>
    </div>
  );
}
