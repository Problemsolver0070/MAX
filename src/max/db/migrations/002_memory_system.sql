-- Phase 2: Memory System migration
-- New tables: graph_nodes, graph_edges, compaction_log, performance_metrics, shelved_improvements
-- ALTER existing: context_anchors, memory_embeddings

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
