-- Phase 5: Quality Gate
-- New tables: quality_rules, quality_patterns
-- ALTER: audit_reports (fix_instructions, strengths, fix_attempt)

CREATE TABLE IF NOT EXISTS quality_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule TEXT NOT NULL,
    source TEXT NOT NULL,
    category VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'normal',
    superseded_by UUID REFERENCES quality_rules(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_rules_category ON quality_rules(category);
CREATE INDEX IF NOT EXISTS idx_quality_rules_active
    ON quality_rules(category) WHERE superseded_by IS NULL;

CREATE TABLE IF NOT EXISTS quality_patterns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern TEXT NOT NULL,
    source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    category VARCHAR(50) NOT NULL,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quality_patterns_category ON quality_patterns(category);
CREATE INDEX IF NOT EXISTS idx_quality_patterns_reinforcement
    ON quality_patterns(reinforcement_count DESC);

ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS fix_instructions TEXT;
ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS strengths JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE audit_reports
    ADD COLUMN IF NOT EXISTS fix_attempt INTEGER NOT NULL DEFAULT 0;
