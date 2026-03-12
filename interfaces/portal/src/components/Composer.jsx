import { ArrowUp, Plus } from "lucide-react";
import { useEffect, useRef } from "react";
import { cx } from "../lib/format";

export default function Composer({
  value,
  onChange,
  onSubmit,
  placeholder = "继续说",
  disabled = false,
  loading = false,
  metaLabel = "Slip",
  note = "",
  attachmentLabel = "",
  attachDisabled = true,
  metaDisabled = true,
  onAttachClick = null,
  onMetaClick = null,
  onInputFocus = null,
  onHistoryUp = null,
  embedded = false,
  testIdPrefix = "composer",
}) {
  const inputRef = useRef(null);

  useEffect(() => {
    const node = inputRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 220)}px`;
  }, [value]);

  const handleKeyDown = (event) => {
    if (disabled) return;
    if (event.key === "ArrowUp" && !event.shiftKey && !String(value || "").trim()) {
      event.preventDefault();
      onHistoryUp?.();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      onSubmit();
    }
  };

  return (
    <div
      data-testid={`${testIdPrefix}-root`}
      className={
        embedded
          ? "px-4 pb-4 pt-3"
          : "sticky bottom-0 z-20 bg-gradient-to-t from-[#F5F5F0] from-75% to-transparent px-4 pb-4 pt-8"
      }
    >
      <div className="mx-auto w-full max-w-3xl">
        <div className="flex w-full flex-col rounded-2xl border border-transparent bg-white p-0.5 shadow-claude transition-shadow duration-200 focus-within:shadow-claude-strong hover:shadow-claude-strong/80">
          <div className="m-3.5 flex flex-col gap-3.5">
            <div className="relative">
              <textarea
                ref={inputRef}
                data-testid={`${testIdPrefix}-input`}
                value={value}
                onChange={(event) => onChange(event.target.value)}
                onFocus={onInputFocus || undefined}
                onKeyDown={handleKeyDown}
                placeholder={placeholder}
                disabled={disabled}
                rows={1}
                className="portal-serif block min-h-6 max-h-56 w-full resize-none overflow-y-auto bg-transparent text-[#1a1a18] outline-none placeholder:text-[#9a9893] disabled:cursor-not-allowed disabled:opacity-60"
              />
            </div>

            {attachmentLabel ? (
              <div className="flex flex-wrap gap-2">
                <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-[#00000012] bg-[#f5f5f0] px-3 py-1 text-xs text-[#6b6a68]">
                  <Plus width={12} height={12} />
                  <span className="truncate">{attachmentLabel}</span>
                </span>
              </div>
            ) : null}

            <div className="flex w-full items-center gap-2">
              <div className="relative flex min-w-0 flex-1 shrink items-center gap-2">
                <button
                  type="button"
                  disabled={attachDisabled}
                  onClick={onAttachClick || undefined}
                  data-testid={`${testIdPrefix}-attach`}
                  title={attachDisabled ? "材料上传后端未接入" : "挂一份假材料"}
                  className="flex h-8 min-w-8 items-center justify-center overflow-hidden rounded-lg border border-[#00000015] bg-transparent px-1.5 text-[#6b6a68] transition hover:bg-[#f5f5f0] disabled:opacity-60"
                >
                  <Plus width={16} height={16} />
                </button>
              </div>

              {metaDisabled || !onMetaClick ? (
                <div className="inline-flex h-8 min-w-16 items-center justify-center rounded-md bg-[#f5f5f0] px-3 text-[14px] text-[#6b6a68]">
                  <span data-testid={`${testIdPrefix}-meta-label`}>{metaLabel}</span>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={onMetaClick}
                  data-testid={`${testIdPrefix}-meta-button`}
                  className="flex h-8 min-w-16 items-center justify-center whitespace-nowrap rounded-md px-3 text-[14px] text-[#1a1a18] transition hover:bg-[#f5f5f0]"
                >
                  {metaLabel}
                </button>
              )}

              <button
                type="button"
                onClick={onSubmit}
                data-testid={`${testIdPrefix}-submit`}
                disabled={disabled || loading || !String(value || "").trim()}
                className={cx(
                  "flex h-8 w-8 items-center justify-center rounded-lg transition-colors disabled:pointer-events-none disabled:opacity-50",
                  disabled || loading || !String(value || "").trim()
                    ? "bg-[#d5d2c8]"
                    : "bg-[#ae5630] hover:bg-[#c4633a]",
                )}
              >
                <ArrowUp width={16} height={16} className="text-white" />
              </button>
            </div>
          </div>
        </div>

        {note ? <p className="mt-2 px-1 text-xs text-[#8a8985]">{note}</p> : null}
      </div>
    </div>
  );
}
