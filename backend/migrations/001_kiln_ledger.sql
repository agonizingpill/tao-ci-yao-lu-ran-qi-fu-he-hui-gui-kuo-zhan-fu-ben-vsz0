CREATE TABLE accounts (
  username text PRIMARY KEY,
  password_digest text NOT NULL,
  role text NOT NULL CHECK (role IN ('operator','supervisor','viewer'))
);
CREATE TABLE firing_batches (
  code text PRIMARY KEY,
  kiln text NOT NULL,
  recipe text NOT NULL,
  baseline_version integer NOT NULL CHECK (baseline_version > 0),
  batch_kg numeric(10,2) NOT NULL CHECK (batch_kg > 0),
  opened_at timestamptz NOT NULL,
  closed_at timestamptz NOT NULL CHECK (closed_at > opened_at),
  planned_minutes integer NOT NULL CHECK (planned_minutes > 0),
  status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','recording','analyzed','confirmed')),
  created_by text NOT NULL REFERENCES accounts(username)
);
CREATE TABLE kiln_curve (
  batch_code text NOT NULL REFERENCES firing_batches(code),
  phase text NOT NULL CHECK (phase IN ('ramp','soak','cool')),
  started_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL CHECK (ended_at > started_at),
  peak_c numeric(7,2) NOT NULL CHECK (peak_c BETWEEN 20 AND 1500),
  source_file text NOT NULL,
  recorded_by text NOT NULL REFERENCES accounts(username),
  PRIMARY KEY(batch_code, started_at),
  UNIQUE(batch_code, phase)
);
CREATE TABLE gas_meter (
  batch_code text NOT NULL REFERENCES firing_batches(code),
  sampled_at timestamptz NOT NULL,
  meter_serial text NOT NULL,
  reading_m3 numeric(13,3) NOT NULL CHECK (reading_m3 >= 0),
  source_file text NOT NULL,
  recorded_by text NOT NULL REFERENCES accounts(username),
  PRIMARY KEY(batch_code, sampled_at)
);
CREATE TABLE recipe_changes (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch_code text NOT NULL REFERENCES firing_batches(code),
  version integer NOT NULL CHECK (version > 0),
  description text NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  submitted_by text NOT NULL REFERENCES accounts(username),
  reviewed_by text REFERENCES accounts(username),
  reviewed_at timestamptz,
  note text,
  UNIQUE(batch_code, version)
);
CREATE TABLE load_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch_code text NOT NULL REFERENCES firing_batches(code),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','ready','failed')),
  requested_by text NOT NULL REFERENCES accounts(username),
  input_hash text NOT NULL,
  input_snapshot jsonb NOT NULL,
  result jsonb,
  error text,
  attempts integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(batch_code, input_hash),
  UNIQUE(batch_code, id)
);
CREATE TABLE cycle_reviews (
  batch_code text PRIMARY KEY REFERENCES firing_batches(code),
  run_id bigint NOT NULL,
  recipe_change_id bigint REFERENCES recipe_changes(id),
  next_minutes integer NOT NULL CHECK (next_minutes BETWEEN 30 AND 1440),
  attribution text NOT NULL CHECK (attribution IN ('observed','recipe')),
  rationale text NOT NULL,
  proposed_by text NOT NULL REFERENCES accounts(username),
  confirmed_by text REFERENCES accounts(username),
  confirmed_at timestamptz,
  FOREIGN KEY(batch_code, run_id) REFERENCES load_runs(batch_code,id)
);
CREATE TABLE ledger_audit (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  batch_code text,
  actor text NOT NULL,
  event text NOT NULL,
  detail jsonb NOT NULL,
  happened_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX load_queue ON load_runs (id) WHERE status = 'queued';
CREATE INDEX audit_batch ON ledger_audit (batch_code, id);
