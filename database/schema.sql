-- Enable UUID extension if needed (PostgreSQL example)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------
-- Tenant table (isolates data per organization/user)
-- ----------------------------
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ----------------------------
-- Sessions (one per chat / generation run)
-- ----------------------------
CREATE TABLE IF NOT EXISTS sessions (
    session_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    prompt          TEXT NOT NULL,
    user_input_json TEXT NOT NULL,          -- original user‑provided JSON
    status          TEXT NOT NULL,          -- e.g. created,running,completed,failed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    current_stage   TEXT,                   -- optional, nullable
    total_lessons   INTEGER DEFAULT 0,
    completed_lessons INTEGER DEFAULT 0,
    error_message   TEXT,
    config          JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- ----------------------------
-- Stage checkpoints (pipeline stages per session)
-- ----------------------------
CREATE TABLE IF NOT EXISTS stage_checkpoints (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    input_data      JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_data     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    UNIQUE(session_id, stage)
);

-- ----------------------------
-- Task checkpoints (individual tasks inside a stage)
-- ----------------------------
CREATE TABLE IF NOT EXISTS task_checkpoints (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    task_type       TEXT NOT NULL,
    task_key        TEXT NOT NULL,
    status          TEXT NOT NULL,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    input_data      JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_data     JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message   TEXT,
    retry_count     INTEGER DEFAULT 0,
    UNIQUE(session_id, stage, task_id)
);

-- ----------------------------
-- Transaction log (captures every user → LLM exchange)
-- ----------------------------
CREATE TABLE IF NOT EXISTS chat_transactions (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
    session_id      UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content         TEXT NOT NULL,          -- raw prompt or LLM output
    metadata        JSONB DEFAULT '{}'::jsonb, -- e.g. model, temperature, token usage
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for frequent queries
CREATE INDEX IF NOT EXISTS idx_sessions_tenant   ON sessions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status   ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_chats_session     ON chat_transactions(session_id);
CREATE INDEX IF NOT EXISTS idx_chats_tenant      ON chat_transactions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_chats_created     ON chat_transactions(created_at);