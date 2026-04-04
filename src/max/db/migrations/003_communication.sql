-- Phase 3: Communication Layer tables

CREATE TABLE IF NOT EXISTS conversation_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    direction VARCHAR(10) NOT NULL,
    platform VARCHAR(20) NOT NULL DEFAULT 'telegram',
    platform_message_id INTEGER,
    message_type VARCHAR(20) NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    attachments_meta JSONB DEFAULT '[]'::jsonb,
    intent_id UUID REFERENCES intents(id),
    source_type VARCHAR(30),
    source_id UUID,
    urgency VARCHAR(20),
    delivery_status VARCHAR(20) DEFAULT 'pending',
    scan_result JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_created
    ON conversation_messages(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_direction
    ON conversation_messages(direction);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_intent
    ON conversation_messages(intent_id) WHERE intent_id IS NOT NULL;
