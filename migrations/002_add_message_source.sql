-- Add source column to conversation_messages for §4.10 Telegram ↔ desktop sync.
-- Tracks message origin (desktop / telegram) so messages from all interfaces
-- appear in the unified conversation view.

ALTER TABLE conversation_messages
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'desktop';
