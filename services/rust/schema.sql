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
