-- ═════════════════════════════════════════════════════════════════════════════
-- Phase 4: Command Chain alterations
-- ═════════════════════════════════════════════════════════════════════════════

-- ── Subtasks: add execution metadata ───────────────────────────────────────
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS phase_number INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS tool_categories JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS worker_agent_id UUID;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS quality_criteria JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS estimated_complexity VARCHAR(20) NOT NULL DEFAULT 'moderate';

CREATE INDEX IF NOT EXISTS idx_subtasks_phase ON subtasks(parent_task_id, phase_number);

-- ── Tasks: add priority ────────────────────────────────────────────────────
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';
