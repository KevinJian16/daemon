-- daemon initial schema
-- Reference: SYSTEM_DESIGN_REFERENCE.md Appendix C
-- Run against the 'daemon' database

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- C.1 daemon_tasks
CREATE TABLE IF NOT EXISTS daemon_tasks (
    task_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_issue_id  UUID NOT NULL UNIQUE,
    project_id      UUID,
    trigger_type    TEXT NOT NULL DEFAULT 'manual',
    schedule_id     TEXT,
    chain_source_task_id UUID,
    dag             JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- C.2 jobs
CREATE TABLE IF NOT EXISTS jobs (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES daemon_tasks(task_id),
    workflow_id     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running',
    sub_status      TEXT NOT NULL DEFAULT 'queued',
    is_ephemeral    BOOLEAN NOT NULL DEFAULT false,
    requires_review BOOLEAN NOT NULL DEFAULT false,
    dag_snapshot    JSONB NOT NULL,
    plane_sync_failed BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_task_id ON jobs(task_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

-- C.3 job_steps
CREATE TABLE IF NOT EXISTS job_steps (
    step_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(job_id),
    step_index      INTEGER NOT NULL,
    goal            TEXT NOT NULL,
    agent_id        TEXT,
    execution_type  TEXT NOT NULL DEFAULT 'agent',
    model_hint      TEXT,
    depends_on      INTEGER[] DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    skill_used      TEXT,
    input_artifacts TEXT[],
    token_used      INTEGER,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_job_steps_job_id ON job_steps(job_id);

-- C.4 job_artifacts
CREATE TABLE IF NOT EXISTS job_artifacts (
    artifact_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(job_id),
    step_id         UUID REFERENCES job_steps(step_id),
    artifact_type   TEXT NOT NULL,
    title           TEXT,
    summary         TEXT,
    minio_path      TEXT NOT NULL,
    mime_type       TEXT,
    size_bytes      BIGINT,
    source_markers  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id ON job_artifacts(job_id);

-- C.5 knowledge_cache
CREATE TABLE IF NOT EXISTS knowledge_cache (
    cache_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url      TEXT NOT NULL,
    source_tier     CHAR(1) NOT NULL,
    project_id      UUID,
    title           TEXT,
    content_summary TEXT,
    ragflow_doc_id  TEXT,
    embedding       vector(1024),
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kc_source_url ON knowledge_cache(source_url);
CREATE INDEX IF NOT EXISTS idx_kc_project ON knowledge_cache(project_id);
CREATE INDEX IF NOT EXISTS idx_kc_expires ON knowledge_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_kc_embedding ON knowledge_cache USING ivfflat (embedding vector_cosine_ops);

-- C.6 event_log
CREATE TABLE IF NOT EXISTS event_log (
    event_id        BIGSERIAL PRIMARY KEY,
    channel         TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_event_log_channel ON event_log(channel) WHERE consumed_at IS NULL;

-- C.7 conversation_messages (L1 scene conversations — layer 1 of 4-layer compression)
CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene           TEXT NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_msg_scene ON conversation_messages(scene, created_at);

-- C.8 conversation_digests (L1 summaries — layer 2 of 4-layer compression)
CREATE TABLE IF NOT EXISTS conversation_digests (
    digest_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene           TEXT NOT NULL,
    time_range_start TIMESTAMPTZ NOT NULL,
    time_range_end  TIMESTAMPTZ NOT NULL,
    summary         TEXT NOT NULL,
    token_count     INTEGER,
    source_message_count INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_digest_scene ON conversation_digests(scene, created_at);

-- C.9 conversation_decisions (L1 key decisions — layer 3 of 4-layer compression)
CREATE TABLE IF NOT EXISTS conversation_decisions (
    decision_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene           TEXT NOT NULL,
    decision_type   TEXT NOT NULL,
    content         TEXT NOT NULL,
    context_summary TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_decision_scene ON conversation_decisions(scene, created_at);

-- Notify function for event bus (PG LISTEN/NOTIFY)
CREATE OR REPLACE FUNCTION notify_event_bus()
RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify(NEW.channel, json_build_object(
        'event_id', NEW.event_id,
        'event_type', NEW.event_type,
        'payload', NEW.payload
    )::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER event_log_notify
    AFTER INSERT ON event_log
    FOR EACH ROW
    EXECUTE FUNCTION notify_event_bus();
