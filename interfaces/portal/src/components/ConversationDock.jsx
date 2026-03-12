import Composer from "./Composer";
import MessageThread from "./MessageThread";
import { cx } from "../lib/format";

export default function ConversationDock({
  ownerLabel,
  composerPlaceholder = "继续说",
  focused = false,
  onFocusChange,
  messages,
  composerValue,
  onComposerChange,
  onComposerSubmit,
  onComposerHistoryUp = null,
  composerDisabled = false,
  composerLoading = false,
  attachmentLabel = "",
  onAttachClick = null,
  onRetryMessage = null,
  onEditMessage = null,
  onCopyMessage = null,
  onRateMessage = null,
  copiedMessageId = "",
  renderMessage = null,
  getMessageKey = null,
  getMessageId = null,
  scrollToMessageId = "",
  testIdPrefix = "conversation-dock",
}) {
  return (
    <div className="pointer-events-none px-4 pb-4 pt-3" data-testid={`${testIdPrefix}-root`}>
      <div className="mx-auto w-full max-w-3xl">
        <div className="relative">
          <div
            data-testid={`${testIdPrefix}-panel-wrap`}
            className={cx(
              "absolute inset-x-0 bottom-[calc(100%+0.65rem)] transition-all duration-200 ease-out",
              focused
                ? "pointer-events-auto visible translate-y-0 opacity-100"
                : "pointer-events-none invisible translate-y-4 opacity-0",
            )}
          >
            <div className="relative h-[34rem]" data-testid={`${testIdPrefix}-panel`}>
              <div className="absolute inset-0 overflow-hidden rounded-[1.75rem] border border-[rgba(0,0,0,0.04)] bg-white shadow-claude">
                <MessageThread
                  messages={messages}
                  onRetryMessage={onRetryMessage}
                  onEditMessage={onEditMessage}
                  onCopyMessage={onCopyMessage}
                  onRateMessage={onRateMessage}
                  copiedMessageId={copiedMessageId}
                  embedded
                  revealed={focused}
                  renderItem={renderMessage}
                  getItemKey={getMessageKey}
                  getItemId={getMessageId}
                  scrollToItemId={scrollToMessageId}
                  testIdPrefix={`${testIdPrefix}-thread`}
                />
              </div>
              <div className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-[#F5F5F0] via-[#F5F5F0]/78 to-transparent" />
            </div>
          </div>

          <div className="pointer-events-auto">
            <Composer
              value={composerValue}
              onChange={onComposerChange}
              onSubmit={onComposerSubmit}
              placeholder={composerPlaceholder}
              disabled={composerDisabled}
              loading={composerLoading}
              metaLabel={ownerLabel}
              note=""
              attachDisabled={composerDisabled}
              metaDisabled
              onAttachClick={onAttachClick}
              onInputFocus={() => onFocusChange?.(true)}
              onHistoryUp={onComposerHistoryUp}
              attachmentLabel={attachmentLabel}
              embedded
              testIdPrefix={`${testIdPrefix}-composer`}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
