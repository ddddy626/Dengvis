-- Jarvis MySQL 8.4 initial schema. Review before use; this file has not been run.
-- Select a dedicated empty database first. No CREATE DATABASE, USE, DROP or seed data.
-- DATETIME(3) values are UTC; applications must set the connection time zone to UTC.

CREATE TABLE users (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  email VARCHAR(254) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'active',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE demo_sessions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  session_token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  quota_used INT UNSIGNED NOT NULL DEFAULT 0,
  seed_version VARCHAR(40) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_demo_sessions_token_hash (session_token_hash),
  KEY ix_demo_sessions_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE user_profiles (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  nickname VARCHAR(100) NOT NULL,
  timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Shanghai',
  goals_json JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_user_profiles_user_id (user_id),
  CONSTRAINT fk_user_profiles_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE personas (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  voice_id VARCHAR(80) NOT NULL,
  character_form VARCHAR(80) NOT NULL,
  style_rules JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_personas_user_id (user_id),
  CONSTRAINT fk_personas_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE devices (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  device_type VARCHAR(40) NOT NULL,
  device_id_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  last_seen DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_devices_user_hash (user_id, device_id_hash),
  KEY ix_devices_user_seen (user_id, last_seen),
  CONSTRAINT fk_devices_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE permission_grants (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  scope VARCHAR(120) NOT NULL,
  data_source VARCHAR(120) NOT NULL,
  grant_type VARCHAR(40) NOT NULL,
  expires_at DATETIME(3) NULL,
  revoked_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_permission_grants_user_scope (user_id, scope, data_source, revoked_at),
  KEY ix_permission_grants_expires_at (expires_at),
  CONSTRAINT fk_permission_grants_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE memory_candidates (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  summary TEXT NOT NULL,
  evidence_ref VARCHAR(512) NOT NULL,
  purpose VARCHAR(255) NOT NULL,
  expires_at DATETIME(3) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'candidate',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_memory_candidates_user_status (user_id, status, expires_at),
  CONSTRAINT fk_memory_candidates_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT ck_memory_candidates_status CHECK (status IN ('candidate', 'confirmed', 'rejected', 'expired'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE memories (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  content TEXT NOT NULL,
  category VARCHAR(80) NOT NULL,
  source_ref VARCHAR(512) NULL,
  confirmed_at DATETIME(3) NOT NULL,
  revoked_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_memories_user_category (user_id, category, revoked_at),
  CONSTRAINT fk_memories_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE conversations (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  demo_session_id BIGINT UNSIGNED NULL,
  started_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  retention_policy VARCHAR(40) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_conversations_user_started (user_id, started_at),
  KEY ix_conversations_demo_started (demo_session_id, started_at),
  UNIQUE KEY uq_conversations_id_user (id, user_id),
  UNIQUE KEY uq_conversations_id_demo (id, demo_session_id),
  CONSTRAINT fk_conversations_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_conversations_demo FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
  CONSTRAINT ck_conversations_owner CHECK ((user_id IS NULL) <> (demo_session_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE messages (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  demo_session_id BIGINT UNSIGNED NULL,
  conversation_id BIGINT UNSIGNED NOT NULL,
  role VARCHAR(24) NOT NULL,
  content_ref VARCHAR(512) NOT NULL,
  safety_flags JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_messages_conversation_created (conversation_id, created_at),
  KEY ix_messages_conversation_user (conversation_id, user_id),
  KEY ix_messages_conversation_demo (conversation_id, demo_session_id),
  KEY ix_messages_user (user_id),
  KEY ix_messages_demo (demo_session_id),
  CONSTRAINT fk_messages_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_messages_demo FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
  CONSTRAINT fk_messages_conversation_user FOREIGN KEY (conversation_id, user_id) REFERENCES conversations (id, user_id),
  CONSTRAINT fk_messages_conversation_demo FOREIGN KEY (conversation_id, demo_session_id) REFERENCES conversations (id, demo_session_id),
  CONSTRAINT ck_messages_owner CHECK ((user_id IS NULL) <> (demo_session_id IS NULL)),
  CONSTRAINT ck_messages_role CHECK (role IN ('system', 'user', 'assistant', 'tool'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE schedules (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(255) NOT NULL,
  starts_at DATETIME(3) NOT NULL,
  ends_at DATETIME(3) NOT NULL,
  status VARCHAR(32) NOT NULL,
  source VARCHAR(120) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_schedules_user_starts (user_id, starts_at),
  CONSTRAINT fk_schedules_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT ck_schedules_time CHECK (ends_at > starts_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE tasks (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(255) NOT NULL,
  due_at DATETIME(3) NULL,
  priority VARCHAR(24) NOT NULL DEFAULT 'normal',
  status VARCHAR(32) NOT NULL DEFAULT 'open',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_tasks_user_status_due (user_id, status, due_at),
  CONSTRAINT fk_tasks_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE agent_jobs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  demo_session_id BIGINT UNSIGNED NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  plan_json JSON NULL,
  budget_json JSON NULL,
  idempotency_key VARCHAR(128) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_agent_jobs_user_idempotency (user_id, idempotency_key),
  UNIQUE KEY uq_agent_jobs_demo_idempotency (demo_session_id, idempotency_key),
  KEY ix_agent_jobs_user_status (user_id, status, created_at),
  KEY ix_agent_jobs_demo_status (demo_session_id, status, created_at),
  UNIQUE KEY uq_agent_jobs_id_user (id, user_id),
  UNIQUE KEY uq_agent_jobs_id_demo (id, demo_session_id),
  CONSTRAINT fk_agent_jobs_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_agent_jobs_demo FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
  CONSTRAINT ck_agent_jobs_owner CHECK ((user_id IS NULL) <> (demo_session_id IS NULL)),
  CONSTRAINT ck_agent_jobs_status CHECK (status IN ('queued', 'running', 'waiting_approval', 'waiting_pc', 'retry_scheduled', 'succeeded', 'failed', 'cancelled'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE agent_job_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  demo_session_id BIGINT UNSIGNED NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  seq_no INT UNSIGNED NOT NULL,
  event_type VARCHAR(80) NOT NULL,
  summary VARCHAR(500) NOT NULL,
  `timestamp` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_agent_job_events_job_seq (job_id, seq_no),
  KEY ix_agent_job_events_user (user_id),
  KEY ix_agent_job_events_demo (demo_session_id),
  KEY ix_agent_job_events_job_user (job_id, user_id),
  KEY ix_agent_job_events_job_demo (job_id, demo_session_id),
  CONSTRAINT fk_agent_job_events_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_agent_job_events_demo FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
  CONSTRAINT fk_agent_job_events_job_user FOREIGN KEY (job_id, user_id) REFERENCES agent_jobs (id, user_id),
  CONSTRAINT fk_agent_job_events_job_demo FOREIGN KEY (job_id, demo_session_id) REFERENCES agent_jobs (id, demo_session_id),
  CONSTRAINT ck_agent_job_events_owner CHECK ((user_id IS NULL) <> (demo_session_id IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE approval_requests (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  demo_session_id BIGINT UNSIGNED NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  scope VARCHAR(120) NOT NULL,
  payload_preview VARCHAR(1000) NOT NULL,
  decision VARCHAR(32) NOT NULL DEFAULT 'pending',
  expires_at DATETIME(3) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_approval_requests_job (job_id),
  KEY ix_approval_requests_job_user (job_id, user_id),
  KEY ix_approval_requests_job_demo (job_id, demo_session_id),
  KEY ix_approval_requests_user_decision (user_id, decision, expires_at),
  KEY ix_approval_requests_demo_decision (demo_session_id, decision, expires_at),
  CONSTRAINT fk_approval_requests_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_approval_requests_demo FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
  CONSTRAINT fk_approval_requests_job_user FOREIGN KEY (job_id, user_id) REFERENCES agent_jobs (id, user_id),
  CONSTRAINT fk_approval_requests_job_demo FOREIGN KEY (job_id, demo_session_id) REFERENCES agent_jobs (id, demo_session_id),
  CONSTRAINT ck_approval_requests_owner CHECK ((user_id IS NULL) <> (demo_session_id IS NULL)),
  CONSTRAINT ck_approval_requests_decision CHECK (decision IN ('pending', 'allow_once', 'allow_scope', 'deny', 'expired'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE morning_reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  report_date DATE NOT NULL,
  data_sources_json JSON NOT NULL,
  content_json JSON NOT NULL,
  status VARCHAR(32) NOT NULL,
  generated_at DATETIME(3) NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_morning_reports_user_date (user_id, report_date),
  CONSTRAINT fk_morning_reports_user FOREIGN KEY (user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE health_summaries (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NOT NULL,
  record_date DATE NOT NULL,
  sleep_minutes SMALLINT UNSIGNED NULL,
  sleep_score TINYINT UNSIGNED NULL,
  source_type VARCHAR(80) NOT NULL,
  source_status VARCHAR(40) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_health_summaries_user_date_source (user_id, record_date, source_type),
  CONSTRAINT fk_health_summaries_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT ck_health_summaries_sleep_score CHECK (sleep_score IS NULL OR sleep_score <= 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE audit_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  demo_session_id BIGINT UNSIGNED NULL,
  actor_id VARCHAR(128) NOT NULL,
  tool_name VARCHAR(120) NOT NULL,
  scope VARCHAR(120) NOT NULL,
  decision VARCHAR(40) NOT NULL,
  request_id VARCHAR(128) NOT NULL,
  result_code VARCHAR(80) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  KEY ix_audit_events_user_created (user_id, created_at),
  KEY ix_audit_events_demo_created (demo_session_id, created_at),
  KEY ix_audit_events_request_id (request_id),
  CONSTRAINT fk_audit_events_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT fk_audit_events_demo FOREIGN KEY (demo_session_id) REFERENCES demo_sessions (id),
  CONSTRAINT ck_audit_events_owner CHECK (user_id IS NULL OR demo_session_id IS NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
