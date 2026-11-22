-- 限气班次排单：班次燃气额度、计划温程、窑次预留占额与幂等请求。
CREATE TABLE gas_shifts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL UNIQUE,
  started_at timestamptz NOT NULL,
  ended_at timestamptz NOT NULL CHECK (ended_at > started_at),
  quota_m3 numeric(12,3) NOT NULL CHECK (quota_m3 > 0),
  created_by text NOT NULL REFERENCES accounts(username),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- 按配方登记的计划温程，供尚未采集曲线的窑次做计划口径回归估算。
CREATE TABLE firing_programs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  recipe text NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  ramp_peak_c numeric(7,2) NOT NULL CHECK (ramp_peak_c BETWEEN 20 AND 1500),
  soak_peak_c numeric(7,2) NOT NULL CHECK (soak_peak_c BETWEEN 20 AND 1500),
  cool_peak_c numeric(7,2) NOT NULL CHECK (cool_peak_c BETWEEN 20 AND 1500),
  ramp_share numeric(5,4) NOT NULL CHECK (ramp_share BETWEEN 0.05 AND 0.9),
  soak_share numeric(5,4) NOT NULL CHECK (soak_share BETWEEN 0.05 AND 0.9),
  created_by text NOT NULL REFERENCES accounts(username),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ramp_share + soak_share < 1),
  UNIQUE(recipe, version)
);

-- 已排窑次对班次额度的占用；未排上的窑次不会留下记录，占额随事务回滚退回。
CREATE TABLE shift_reservations (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  shift_id bigint NOT NULL REFERENCES gas_shifts(id),
  batch_code text NOT NULL REFERENCES firing_batches(code),
  reserved_m3 numeric(12,3) NOT NULL CHECK (reserved_m3 > 0),
  batch_kg numeric(10,2) NOT NULL,
  estimate_snapshot jsonb NOT NULL,
  requested_by text NOT NULL REFERENCES accounts(username),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(shift_id, batch_code),
  UNIQUE(batch_code)
);
CREATE INDEX shift_reservations_shift ON shift_reservations(shift_id, id);

-- 排单请求幂等键：同一请求键重试只生效一次，不能重复扣气。
CREATE TABLE shift_plan_requests (
  request_key text PRIMARY KEY,
  shift_id bigint NOT NULL REFERENCES gas_shifts(id),
  actor text NOT NULL REFERENCES accounts(username),
  status text NOT NULL CHECK (status IN ('placed','failed')),
  detail jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
