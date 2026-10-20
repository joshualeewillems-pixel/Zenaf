-- Vision Execution Engine — SQLite schema (Phase 1)
-- Run automatically on first use via storage.init_db()

-- Nested hierarchical checklists for ideas (idea graduation, 2026-10-18).
-- Joshua's decision: instead of fixed "practical fields," each idea defines its
-- own "practical" as a nested checklist, built conversationally ("what would
-- make this real?"). An idea is ready to graduate when its checklist is
-- non-empty and every item is done. On graduation the checklist unfolds into
-- the work breakdown (top-level items -> tasks, nested -> subtasks) and is
-- kept as provenance, marked superseded.
CREATE TABLE IF NOT EXISTS checklist_items (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  idea_id TEXT NOT NULL,
  parent_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'open',
  position INTEGER NOT NULL DEFAULT 0,
  superseded INTEGER NOT NULL DEFAULT 0,
  person_id TEXT,
  asset_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (idea_id) REFERENCES ideas(id),
  FOREIGN KEY (parent_id) REFERENCES checklist_items(id),
  FOREIGN KEY (person_id) REFERENCES persons(id),
  FOREIGN KEY (asset_id) REFERENCES assets(id)
);

CREATE TABLE IF NOT EXISTS checklist_item_dependencies (
  item_id TEXT NOT NULL,
  depends_on_item_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (item_id, depends_on_item_id),
  FOREIGN KEY (item_id) REFERENCES checklist_items(id),
  FOREIGN KEY (depends_on_item_id) REFERENCES checklist_items(id)
);

CREATE TABLE IF NOT EXISTS core_profiles (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  name TEXT NOT NULL DEFAULT '',
  core_definition TEXT NOT NULL DEFAULT '',
  current_goals TEXT NOT NULL DEFAULT '',
  growth_focus_12_months TEXT NOT NULL DEFAULT '',
  economic_engine TEXT NOT NULL DEFAULT '',
  non_negotiables TEXT NOT NULL DEFAULT '',
  strategic_filter TEXT NOT NULL DEFAULT '',
  current_constraints TEXT NOT NULL DEFAULT '',
  capacity_limit TEXT NOT NULL DEFAULT '',
  kill_philosophy TEXT NOT NULL DEFAULT '',
  strength_positioning TEXT NOT NULL DEFAULT '',
  raw_notes TEXT NOT NULL DEFAULT '',
  is_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ideas (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Captured',
  tags TEXT NOT NULL DEFAULT '[]',
  created_by TEXT NOT NULL DEFAULT '',
  desired_outcome TEXT NOT NULL DEFAULT '',
  linked_people TEXT NOT NULL DEFAULT '[]',
  linked_assets TEXT NOT NULL DEFAULT '[]',
  linked_ideas TEXT NOT NULL DEFAULT '[]',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS initiatives (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  source_idea_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  brief TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Draft',
  owner_id TEXT,
  priority_rank_manual INTEGER,
  strategic_value_manual INTEGER,
  energy_impact_manual INTEGER,
  evaluation_priority INTEGER,
  estimated_cost_ai TEXT NOT NULL DEFAULT '',
  estimated_timeframe_ai TEXT NOT NULL DEFAULT '',
  philosophical_alignment_ai TEXT NOT NULL DEFAULT '',
  next_step_ai TEXT NOT NULL DEFAULT '',
  required_people TEXT NOT NULL DEFAULT '[]',
  required_assets TEXT NOT NULL DEFAULT '[]',
  dependencies TEXT NOT NULL DEFAULT '',
  risks TEXT NOT NULL DEFAULT '',
  recommendation TEXT NOT NULL DEFAULT '',
  counts_toward_capacity INTEGER NOT NULL DEFAULT 1,
  manual_override TEXT NOT NULL DEFAULT '',
  kill_criteria TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  seed_key TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (source_idea_id) REFERENCES ideas(id),
  FOREIGN KEY (owner_id) REFERENCES persons(id)
);

-- First-class initiative seats (replaces JSON-in-required_people as the seat transport).
CREATE TABLE IF NOT EXISTS initiative_seats (
  id TEXT PRIMARY KEY,
  initiative_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT '',
  assigned_person_id TEXT,
  estimated_effort TEXT,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (initiative_id) REFERENCES initiatives(id) ON DELETE CASCADE,
  FOREIGN KEY (assigned_person_id) REFERENCES persons(id)
);

-- Phase 1 execution checklist (initiative or project scope). Rows are canonical; next_step_ai is legacy/transitional.
CREATE TABLE IF NOT EXISTS execution_steps (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  scope_type TEXT NOT NULL CHECK (scope_type IN ('initiative', 'project')),
  scope_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_done INTEGER NOT NULL DEFAULT 0 CHECK (is_done IN (0, 1)),
  completed_at TEXT,
  source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('ai', 'user', 'import')),
  source_evaluation_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_execution_steps_scope_list ON execution_steps (user_id, scope_type, scope_id, sort_order);

CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  initiative_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  brief TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Draft',
  owner_id TEXT,
  supporting_owner_ids TEXT NOT NULL DEFAULT '[]',
  required_assets TEXT NOT NULL DEFAULT '[]',
  priority TEXT NOT NULL DEFAULT '',
  start_date TEXT,
  end_date TEXT,
  estimated_weekly_hours REAL,
  deliverables TEXT NOT NULL DEFAULT '',
  complexity TEXT NOT NULL DEFAULT '',
  current_focus TEXT NOT NULL DEFAULT '',
  next_step_ai TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (initiative_id) REFERENCES initiatives(id),
  FOREIGN KEY (owner_id) REFERENCES persons(id)
);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  project_id TEXT,
  parent_task_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  assignee_id TEXT,
  status TEXT NOT NULL DEFAULT 'Todo',
  priority TEXT NOT NULL DEFAULT '',
  estimated_hours REAL,
  due_date TEXT,
  dependency_ids TEXT NOT NULL DEFAULT '[]',
  required_asset_ids TEXT NOT NULL DEFAULT '[]',
  completion_criteria TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  seat_ref TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id),
  FOREIGN KEY (parent_task_id) REFERENCES tasks(id),
  FOREIGN KEY (assignee_id) REFERENCES persons(id)
);

CREATE TABLE IF NOT EXISTS persons (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT '',
  relationship_type TEXT NOT NULL DEFAULT '',
  contact_info TEXT NOT NULL DEFAULT '',
  strengths TEXT NOT NULL DEFAULT '',
  needs TEXT NOT NULL DEFAULT '',
  wants TEXT NOT NULL DEFAULT '',
  availability TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capacity_profiles (
  person_id TEXT PRIMARY KEY,
  weekly_capacity_hours REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (person_id) REFERENCES persons(id)
);

CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  asset_type TEXT NOT NULL DEFAULT '',
  owner_id TEXT,
  status TEXT NOT NULL DEFAULT '',
  availability TEXT NOT NULL DEFAULT '',
  cost TEXT NOT NULL DEFAULT '',
  time_availability TEXT NOT NULL DEFAULT '',
  linked_idea_ids TEXT NOT NULL DEFAULT '[]',
  linked_initiative_ids TEXT NOT NULL DEFAULT '[]',
  linked_project_ids TEXT NOT NULL DEFAULT '[]',
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (owner_id) REFERENCES persons(id)
);

-- Decision history for personality learning and decision-graph analysis (append-only).
-- Captures major user decisions in Vision → Execution workflow.
CREATE TABLE IF NOT EXISTS decisions (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  ai_proposal_snapshot TEXT,
  final_values_snapshot TEXT,
  created_at TEXT NOT NULL
);

-- Radar feed items (e.g. meeting-extraction signals: attention, risk, opportunity, blocker).
-- Merged into GET /radar under "signals" for display.
CREATE TABLE IF NOT EXISTS radar_feed (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  severity TEXT NOT NULL DEFAULT 'medium',
  source TEXT NOT NULL DEFAULT 'meeting-extraction',
  source_excerpt TEXT,
  kind TEXT NOT NULL DEFAULT 'attention',
  created_at TEXT NOT NULL
);

-- Canonical Signal entity (Layer 1). Radar is a view over signals.
CREATE TABLE IF NOT EXISTS signals (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  detail TEXT,
  source TEXT NOT NULL DEFAULT '',
  source_excerpt TEXT,
  source_ref TEXT,
  confidence TEXT,
  linked_initiative_id TEXT,
  linked_project_id TEXT,
  linked_task_id TEXT,
  linked_asset_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Content pipeline: briefs (first-class list, lifecycle status).
CREATE TABLE IF NOT EXISTS content_briefs (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  payload TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Shareable collaboration slices (Phase S2/S3/S4-lite source objects).
-- Deterministic matching is derived on demand from these records.
CREATE TABLE IF NOT EXISTS seat_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  context_type TEXT NOT NULL DEFAULT '',
  context_id TEXT,
  role_tags TEXT NOT NULL DEFAULT '[]',
  capability_tags TEXT NOT NULL DEFAULT '[]',
  availability_window TEXT,
  commitment_type TEXT NOT NULL DEFAULT '',
  collaboration_mode TEXT NOT NULL DEFAULT '',
  timezone_pref TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'private',
  index_state TEXT NOT NULL DEFAULT 'private',
  consent_version TEXT NOT NULL DEFAULT '',
  consent_at TEXT,
  share_until TEXT,
  share_revoked_at TEXT,
  state_changed_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_offers (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  capability_tags TEXT NOT NULL DEFAULT '[]',
  role_tags TEXT NOT NULL DEFAULT '[]',
  availability_window TEXT,
  commitment_type TEXT NOT NULL DEFAULT '',
  collaboration_mode TEXT NOT NULL DEFAULT '',
  timezone_pref TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'private',
  index_state TEXT NOT NULL DEFAULT 'private',
  consent_version TEXT NOT NULL DEFAULT '',
  consent_at TEXT,
  share_until TEXT,
  share_revoked_at TEXT,
  state_changed_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS material_requests (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  material_type TEXT NOT NULL DEFAULT '',
  resource_nature TEXT NOT NULL DEFAULT '',
  category_tags TEXT NOT NULL DEFAULT '[]',
  quantity_needed REAL NOT NULL DEFAULT 0,
  quantity_unit TEXT NOT NULL DEFAULT '',
  availability_start TEXT,
  availability_end TEXT,
  condition_min TEXT NOT NULL DEFAULT '',
  access_mode TEXT NOT NULL DEFAULT '',
  location_region TEXT NOT NULL DEFAULT '',
  max_distance_km REAL,
  usage_constraints TEXT NOT NULL DEFAULT '[]',
  cost_band_max TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'private',
  index_state TEXT NOT NULL DEFAULT 'private',
  consent_version TEXT NOT NULL DEFAULT '',
  consent_at TEXT,
  share_until TEXT,
  share_revoked_at TEXT,
  state_changed_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS material_offers (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  material_type TEXT NOT NULL DEFAULT '',
  resource_nature TEXT NOT NULL DEFAULT '',
  category_tags TEXT NOT NULL DEFAULT '[]',
  quantity_available REAL NOT NULL DEFAULT 0,
  quantity_unit TEXT NOT NULL DEFAULT '',
  availability_start TEXT,
  availability_end TEXT,
  condition_state TEXT NOT NULL DEFAULT '',
  access_mode TEXT NOT NULL DEFAULT '',
  location_region TEXT NOT NULL DEFAULT '',
  service_area_km REAL,
  usage_constraints TEXT NOT NULL DEFAULT '[]',
  cost_band TEXT NOT NULL DEFAULT '',
  visibility TEXT NOT NULL DEFAULT 'private',
  index_state TEXT NOT NULL DEFAULT 'private',
  consent_version TEXT NOT NULL DEFAULT '',
  consent_at TEXT,
  share_until TEXT,
  share_revoked_at TEXT,
  state_changed_at TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Minimal local auth (Phase 1A): users + sessions.
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  avatar_data_url TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_ideas_user_id ON ideas(user_id);
CREATE INDEX IF NOT EXISTS idx_initiatives_user_id ON initiatives(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_user_id ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_seat_requests_user_id ON seat_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_seat_requests_index_state ON seat_requests(index_state);
CREATE INDEX IF NOT EXISTS idx_capability_offers_user_id ON capability_offers(user_id);
CREATE INDEX IF NOT EXISTS idx_capability_offers_index_state ON capability_offers(index_state);
CREATE INDEX IF NOT EXISTS idx_material_requests_user_id ON material_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_material_requests_index_state ON material_requests(index_state);
CREATE INDEX IF NOT EXISTS idx_material_requests_material_type ON material_requests(material_type);
CREATE INDEX IF NOT EXISTS idx_material_offers_user_id ON material_offers(user_id);
CREATE INDEX IF NOT EXISTS idx_material_offers_index_state ON material_offers(index_state);
CREATE INDEX IF NOT EXISTS idx_material_offers_material_type ON material_offers(material_type);

-- User settings (LLM profile, encrypted provider keys, notification prefs)
CREATE TABLE IF NOT EXISTS user_llm_profile (
  user_id TEXT PRIMARY KEY,
  default_provider TEXT NOT NULL DEFAULT 'ollama',
  default_model TEXT,
  ollama_base_url TEXT,
  ollama_model TEXT,
  llm_provider_prefs_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS user_llm_provider_credentials (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  api_key_ciphertext TEXT NOT NULL,
  extra_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, provider),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_llm_provider_credentials_user ON user_llm_provider_credentials(user_id);

CREATE TABLE IF NOT EXISTS user_notification_settings (
  user_id TEXT PRIMARY KEY,
  prefs_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Server-owned council workspace: perspective agents JSON (cockpit council seat definitions).
CREATE TABLE IF NOT EXISTS user_council_workspace (
  user_id TEXT PRIMARY KEY,
  perspectives_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- User actions on system prompts (developmental guidance only for now). Append-only; no scheduler.
-- engaged = opened discussion (not “resolved”); deferred = revisit later (not endorsement);
-- dismissed = suppress reinjection for a window (not permanent rejection). Match suppression by exact prompt_id.
CREATE TABLE IF NOT EXISTS prompt_signals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  prompt_id TEXT NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('engaged', 'dismissed', 'deferred')),
  entity_type TEXT,
  entity_id TEXT,
  prompt_summary TEXT NOT NULL DEFAULT '',
  deferred_until TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_prompt_signals_user_prompt_created ON prompt_signals (user_id, prompt_id, created_at);
CREATE INDEX IF NOT EXISTS idx_prompt_signals_user_entity ON prompt_signals (user_id, entity_type, entity_id, created_at);

-- Native council stream runs (POST /run/stream); artifact_json is CouncilRunArtifact.model_dump(mode="json").
CREATE TABLE IF NOT EXISTS council_stream_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    user_id TEXT,
    integrity_run_id TEXT,
    artifact_json TEXT NOT NULL,
    full_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_council_stream_runs_integrity ON council_stream_runs (integrity_run_id);
CREATE INDEX IF NOT EXISTS idx_council_stream_runs_user_created ON council_stream_runs (user_id, created_at);

-- Node memory: per-entity vitality (health) index; scores filled incrementally.
CREATE TABLE IF NOT EXISTS node_vitality (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    water REAL DEFAULT 0.0,
    soil REAL DEFAULT 0.0,
    fruit REAL DEFAULT 0.0,
    staleness_days REAL DEFAULT 0.0,
    last_activity_at TEXT,
    last_assessed_at TEXT NOT NULL,
    triggered_by_event_id TEXT,
    rules_version TEXT DEFAULT 'v1',
    payload_json TEXT,
    UNIQUE(user_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_node_vitality_user_entity ON node_vitality (user_id, entity_type);

-- Append-only judgment history keyed by SubjectRef (entity_type, entity_id).
CREATE TABLE IF NOT EXISTS node_judgment_history (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    verdict_kind TEXT NOT NULL,
    effect TEXT NOT NULL,
    state TEXT NOT NULL,
    mechanism_mode TEXT NOT NULL,
    observation_pointer TEXT,
    council_stream_run_id TEXT,
    decision_id TEXT,
    intake_judgment_id TEXT,
    trunk_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_njh_subject
    ON node_judgment_history (user_id, entity_type, entity_id, created_at);

-- Arc detection lab: heuristic proposals only (no minting, no ledger, no embeddings).
-- accepted = accepted as a useful system-detected arc candidate, not proven inner transformation.
CREATE TABLE IF NOT EXISTS arc_detection_candidates (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_entity_type TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    heuristic_version TEXT NOT NULL,
    t_avoid_reading_id TEXT NOT NULL,
    t_eng_reading_id TEXT NOT NULL,
    t_complete_at TEXT NOT NULL,
    detector_confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'accepted', 'rejected')),
    notes_json TEXT NOT NULL DEFAULT '{}',
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, source_entity_type, source_entity_id, heuristic_version)
);

CREATE INDEX IF NOT EXISTS idx_arc_candidates_user ON arc_detection_candidates (user_id);
CREATE INDEX IF NOT EXISTS idx_arc_candidates_status ON arc_detection_candidates (status);

-- User-authored aspiration profile (canonical) + derived operational signals (API).
CREATE TABLE IF NOT EXISTS aspiration_profile (
  user_id TEXT PRIMARY KEY,
  core_aim TEXT NOT NULL DEFAULT '',
  growth_domains TEXT NOT NULL DEFAULT '[]',
  current_edge TEXT NOT NULL DEFAULT '',
  current_obstacles TEXT NOT NULL DEFAULT '',
  near_term_aspirations TEXT NOT NULL DEFAULT '',
  long_term_aspirations TEXT NOT NULL DEFAULT '',
  guidance_preferences TEXT NOT NULL DEFAULT '{}',
  anti_goals TEXT NOT NULL DEFAULT '',
  use_in_guidance INTEGER NOT NULL DEFAULT 0 CHECK (use_in_guidance IN (0, 1)),
  allow_inference INTEGER NOT NULL DEFAULT 0 CHECK (allow_inference IN (0, 1)),
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS aspiration_inference_log (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_aspiration_inference_log_user ON aspiration_inference_log(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS aspiration_proposals (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  theme TEXT NOT NULL DEFAULT '',
  detail TEXT NOT NULL DEFAULT '',
  basis_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'dismissed')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_aspiration_proposals_user_status ON aspiration_proposals(user_id, status);
