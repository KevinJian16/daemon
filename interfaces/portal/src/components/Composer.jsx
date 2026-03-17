import { useState, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { ArrowUpIcon, PlusIcon } from "lucide-react";

export default function Composer({ onSend, disabled, sceneName }) {
  const [text, setText] = useState("");
  const textareaRef = useRef(null);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
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
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  const handleAttach = () => {
    // TODO: implement file upload when backend supports multipart
  };

  return (
    <div className="px-5 pb-4 pt-2 shrink-0">
      <div className="max-w-2xl mx-auto">
        <div className="flex items-center gap-2 rounded-xl border border-input bg-background p-2.5 shadow-xs focus-within:ring-1 focus-within:ring-ring transition-shadow">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleAttach}
            disabled={disabled}
            className="text-muted-foreground shrink-0"
          >
            <PlusIcon className="h-4 w-4" />
          </Button>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={disabled ? "Connecting..." : `Message ${sceneName || "Daemon"}...`}
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent border-none outline-none resize-none
                       min-h-[28px] max-h-[200px] text-sm leading-[28px]
                       placeholder:text-muted-foreground disabled:opacity-50"
          />
          <Button
            size="icon-sm"
            variant={text.trim() ? "default" : "ghost"}
            onClick={handleSend}
            disabled={disabled || !text.trim()}
            className="shrink-0"
          >
            <ArrowUpIcon className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}
