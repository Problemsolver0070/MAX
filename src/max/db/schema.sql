-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Intents (user messages as structured objects)
CREATE TABLE IF NOT EXISTS intents (
    id UUID PRIMARY KEY,
    user_message TEXT NOT NULL,
    source_platform VARCHAR(20) NOT NULL,
    goal_anchor TEXT NOT NULL,
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    attachments JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_intents_platform ON intents(source_platform);
CREATE INDEX IF NOT EXISTS idx_intents_created ON intents(created_at DESC);

-- Tasks (now with FK to intents)
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    goal_anchor TEXT NOT NULL,
    source_intent_id UUID NOT NULL REFERENCES intents(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    quality_criteria JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

-- SubTasks
CREATE TABLE IF NOT EXISTS subtasks (
    id UUID PRIMARY KEY,
    parent_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    assigned_tools JSONB NOT NULL DEFAULT '[]',
    context_package JSONB NOT NULL DEFAULT '{}',
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_subtasks_parent ON subtasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_subtasks_status ON subtasks(status);

-- Audit Reports
CREATE TABLE IF NOT EXISTS audit_reports (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    subtask_id UUID NOT NULL REFERENCES subtasks(id) ON DELETE CASCADE,
    verdict VARCHAR(20) NOT NULL,
    score REAL NOT NULL,
    goal_alignment REAL NOT NULL,
    confidence REAL NOT NULL,
    issues JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_reports(task_id);

-- Results (task outcomes)
CREATE TABLE IF NOT EXISTS results (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    artifacts JSONB NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_results_task ON results(task_id);

-- Clarification Requests
CREATE TABLE IF NOT EXISTS clarification_requests (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    options JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clarifications_task ON clarification_requests(task_id);

-- Status Updates
CREATE TABLE IF NOT EXISTS status_updates (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    progress REAL NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_status_updates_task ON status_updates(task_id);

-- Context Anchors
CREATE TABLE IF NOT EXISTS context_anchors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    anchor_type VARCHAR(50) NOT NULL,
    source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_anchors_type ON context_anchors(anchor_type);

-- Quality Ledger (append-only)
CREATE TABLE IF NOT EXISTS quality_ledger (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_type VARCHAR(50) NOT NULL,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ledger_type ON quality_ledger(entry_type);
CREATE INDEX IF NOT EXISTS idx_ledger_created ON quality_ledger(created_at DESC);

-- Memory embeddings (for semantic search)
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    embedding vector(1536),
    memory_type VARCHAR(50) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_embeddings(memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 2: Memory System tables and alterations
-- ═════════════════════════════════════════════════════════════════════════════

-- ── Graph tables ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS graph_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_type VARCHAR(20) NOT NULL,
    content_id UUID NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_type ON graph_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_content ON graph_nodes(content_id);

CREATE TABLE IF NOT EXISTS graph_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_id UUID NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
    relation VARCHAR(30) NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_traversed TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_id, relation);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_id, relation);
CREATE INDEX IF NOT EXISTS idx_graph_edges_weight ON graph_edges(weight DESC);

-- ── Compaction log ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS compaction_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    item_id UUID NOT NULL,
    item_type VARCHAR(30) NOT NULL,
    from_tier VARCHAR(20) NOT NULL,
    to_tier VARCHAR(20) NOT NULL,
    relevance_before REAL NOT NULL,
    relevance_after REAL NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_compaction_log_item ON compaction_log(item_id);
CREATE INDEX IF NOT EXISTS idx_compaction_log_created ON compaction_log(created_at DESC);

-- ── Performance metrics ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_name VARCHAR(100) NOT NULL,
    value REAL NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metrics_name_time
    ON performance_metrics(metric_name, recorded_at DESC);

-- ── Shelved improvements ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS shelved_improvements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    description TEXT NOT NULL,
    proposed_by VARCHAR(100) NOT NULL,
    failure_reason TEXT NOT NULL,
    metrics_before JSONB NOT NULL,
    metrics_after JSONB NOT NULL,
    regressed_metrics JSONB NOT NULL,
    shelved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retry_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    retry_approach TEXT
);

-- ── ALTER context_anchors (add Phase 2 columns) ────────────────────────────

ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(20) NOT NULL DEFAULT 'active';
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS relevance_score REAL NOT NULL DEFAULT 1.0;
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS decay_rate REAL NOT NULL DEFAULT 0.001;
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS permanence_class VARCHAR(20) NOT NULL DEFAULT 'adaptive';
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES context_anchors(id);
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS parent_anchor_id UUID REFERENCES context_anchors(id);
ALTER TABLE context_anchors
    ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_anchor_lifecycle ON context_anchors(lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_anchor_permanence ON context_anchors(permanence_class);
CREATE INDEX IF NOT EXISTS idx_anchor_fts ON context_anchors USING gin(search_vector);

-- ── ALTER memory_embeddings (add Phase 2 columns) ──────────────────────────

ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS relevance_score REAL NOT NULL DEFAULT 1.0;
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS tier VARCHAR(20) NOT NULL DEFAULT 'full';
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS base_relevance REAL NOT NULL DEFAULT 0.5;
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS decay_rate REAL NOT NULL DEFAULT 0.01;
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE INDEX IF NOT EXISTS idx_memory_tier ON memory_embeddings(tier);
CREATE INDEX IF NOT EXISTS idx_memory_fts ON memory_embeddings USING gin(search_vector);

-- Change vector dimension from 1536 to 1024 (safe: no real embeddings stored yet)
ALTER TABLE memory_embeddings ALTER COLUMN embedding TYPE vector(1024);

-- ── Full-text search triggers ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_search_vector() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', NEW.content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_memory_search_vector ON memory_embeddings;
CREATE TRIGGER trg_memory_search_vector
    BEFORE INSERT OR UPDATE OF content ON memory_embeddings
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();

DROP TRIGGER IF EXISTS trg_anchor_search_vector ON context_anchors;
CREATE TRIGGER trg_anchor_search_vector
    BEFORE INSERT OR UPDATE OF content ON context_anchors
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();

-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 3: Communication Layer tables
-- ═════════════════════════════════════════════════════════════════════════════

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

-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 4: Command Chain alterations
-- ═════════════════════════════════════════════════════════════════════════════

ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS phase_number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS tool_categories JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS worker_agent_id UUID;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS quality_criteria JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS estimated_complexity VARCHAR(20) NOT NULL DEFAULT 'moderate';

CREATE INDEX IF NOT EXISTS idx_subtasks_phase ON subtasks(parent_task_id, phase_number);

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';
