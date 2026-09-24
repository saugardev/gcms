CREATE TABLE IF NOT EXISTS analyses (
    id text PRIMARY KEY CHECK (id ~ '^[a-f0-9]{64}$'),
    sample_name text NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL,
    chromatogram jsonb NOT NULL,
    peaks jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS components (
    analysis_id text NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    id text NOT NULL,
    data jsonb NOT NULL,
    PRIMARY KEY (analysis_id, id)
);

CREATE INDEX IF NOT EXISTS analyses_imported_at ON analyses (imported_at DESC, id);

CREATE TABLE IF NOT EXISTS raw_acquisitions (
    analysis_id text PRIMARY KEY REFERENCES analyses(id) ON DELETE CASCADE,
    source_sha256 text NOT NULL,
    chromatogram jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_scans (
    analysis_id text NOT NULL REFERENCES raw_acquisitions(analysis_id) ON DELETE CASCADE,
    scan_index integer NOT NULL CHECK (scan_index >= 0),
    time_seconds double precision NOT NULL CHECK (time_seconds >= 0 AND time_seconds < 'Infinity'),
    spectrum jsonb NOT NULL,
    PRIMARY KEY (analysis_id, scan_index)
);
CREATE UNIQUE INDEX IF NOT EXISTS raw_scans_time ON raw_scans (analysis_id, time_seconds);

CREATE TABLE IF NOT EXISTS raw_ion_traces (
    analysis_id text NOT NULL REFERENCES raw_acquisitions(analysis_id) ON DELETE CASCADE,
    mass_key integer NOT NULL CHECK (mass_key BETWEEN 0 AND 65535),
    points jsonb NOT NULL,
    PRIMARY KEY (analysis_id, mass_key)
);

-- Browser accounts are shared lab reviewers; computed reports stay immutable.
CREATE TABLE IF NOT EXISTS app_users (
    id text PRIMARY KEY,
    email text NOT NULL UNIQUE CHECK (email = lower(email)),
    name text NOT NULL,
    password_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS app_sessions (
    token_hash bytea PRIMARY KEY,
    user_id text NOT NULL REFERENCES app_users(id),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_sessions_user ON app_sessions(user_id);
