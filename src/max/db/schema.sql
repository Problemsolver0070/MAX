-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Tasks
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    goal_anchor TEXT NOT NULL,
    source_intent_id UUID NOT NULL,
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
