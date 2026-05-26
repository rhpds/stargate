CREATE TABLE IF NOT EXISTS applied_migrations (
    id SERIAL PRIMARY KEY,
    filename TEXT UNIQUE NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(255) UNIQUE NOT NULL,
    demo_id VARCHAR(255) NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    requested_by VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    rubric_version VARCHAR(50) NOT NULL,
    git_sha VARCHAR(64),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS stages (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(255) NOT NULL,
    stage_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_seconds DOUBLE PRECISION,
    result_outcome VARCHAR(50),
    result_failure_class VARCHAR(255),
    result_message TEXT,
    UNIQUE (run_id, stage_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id SERIAL PRIMARY KEY,
    evidence_id VARCHAR(255) UNIQUE NOT NULL,
    run_id VARCHAR(255) NOT NULL,
    stage_id VARCHAR(255) NOT NULL,
    type VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL,
    resource JSONB,
    observed JSONB NOT NULL DEFAULT '{}',
    result VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    raw_ref TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_run_id ON runs(run_id);
CREATE INDEX IF NOT EXISTS idx_stages_run_id ON stages(run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_run_id ON evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_stage_id ON evidence(stage_id);
