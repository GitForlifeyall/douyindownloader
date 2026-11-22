-- =============================================================================
-- Video Registry & Movie Identity Supabase Schema
-- =============================================================================
-- Mirrors SQLite video_registry.db to cloud Supabase PostgreSQL.
-- Enables real-time synchronization of all Douyin/TikTok video runs, rendered
-- outputs, Google Drive links, movie identities, and pipeline audit events.

-- 1. Video Registry Table (Videos & Rendered Outputs)
CREATE TABLE IF NOT EXISTS public.video_registry (
    id BIGSERIAL PRIMARY KEY,
    video_id TEXT NOT NULL UNIQUE,
    source_url TEXT,
    platform TEXT DEFAULT 'douyin',
    channel TEXT,
    batch TEXT,
    original_filename TEXT,
    local_path TEXT,
    final_filename TEXT,
    drive_filename TEXT,
    title TEXT,
    description TEXT,
    tags TEXT,
    target_language TEXT,
    tts_engine TEXT,
    duration_sec DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'downloaded',
    drive_folder TEXT,
    drive_path TEXT,
    drive_file_id TEXT,
    drive_link TEXT,
    thumbnail_path TEXT,
    thumbnail_link TEXT,
    metadata_json TEXT,
    movie_id BIGINT,
    movie_name TEXT,
    movie_year INTEGER,
    movie_genre TEXT,
    movie_synopsis TEXT,
    movie_context TEXT,
    movie_source TEXT,
    movie_source_url TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    uploaded_at TIMESTAMPTZ
);

-- Indices for rapid querying & CTR dashboards
CREATE UNIQUE INDEX IF NOT EXISTS idx_video_registry_video_id ON public.video_registry(video_id);
CREATE INDEX IF NOT EXISTS idx_video_registry_status ON public.video_registry(status);
CREATE INDEX IF NOT EXISTS idx_video_registry_channel ON public.video_registry(channel);
CREATE INDEX IF NOT EXISTS idx_video_registry_final_filename ON public.video_registry(final_filename);
CREATE INDEX IF NOT EXISTS idx_video_registry_movie_name ON public.video_registry(movie_name);
CREATE INDEX IF NOT EXISTS idx_video_registry_created_at ON public.video_registry(created_at DESC);

-- 2. Movies Table (Movie Recap Identities)
CREATE TABLE IF NOT EXISTS public.registry_movies (
    id BIGSERIAL PRIMARY KEY,
    movie_key TEXT NOT NULL UNIQUE,
    movie_name TEXT NOT NULL,
    movie_year INTEGER,
    movie_genre TEXT,
    movie_synopsis TEXT,
    movie_context TEXT,
    movie_source TEXT,
    movie_source_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_registry_movies_key ON public.registry_movies(movie_key);
CREATE INDEX IF NOT EXISTS idx_registry_movies_name ON public.registry_movies(movie_name);

-- 3. Pipeline Events Table (Audit Log)
CREATE TABLE IF NOT EXISTS public.registry_events (
    id BIGSERIAL PRIMARY KEY,
    video_id TEXT NOT NULL,
    event TEXT NOT NULL,
    detail TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_registry_events_video_id ON public.registry_events(video_id);
CREATE INDEX IF NOT EXISTS idx_registry_events_created_at ON public.registry_events(created_at DESC);

-- Enable Row Level Security (RLS)
ALTER TABLE public.video_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.registry_movies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.registry_events ENABLE ROW LEVEL SECURITY;

-- Allow anon and service_role full read/write access
DROP POLICY IF EXISTS "Allow anon read/write video_registry" ON public.video_registry;
CREATE POLICY "Allow anon read/write video_registry"
    ON public.video_registry
    FOR ALL
    TO anon, authenticated, service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon read/write registry_movies" ON public.registry_movies;
CREATE POLICY "Allow anon read/write registry_movies"
    ON public.registry_movies
    FOR ALL
    TO anon, authenticated, service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon read/write registry_events" ON public.registry_events;
CREATE POLICY "Allow anon read/write registry_events"
    ON public.registry_events
    FOR ALL
    TO anon, authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Auto-update updated_at triggers
CREATE OR REPLACE FUNCTION update_registry_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = timezone('utc'::text, now());
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS set_video_registry_updated_at ON public.video_registry;
CREATE TRIGGER set_video_registry_updated_at
    BEFORE UPDATE ON public.video_registry
    FOR EACH ROW
    EXECUTE FUNCTION update_registry_updated_at_column();

DROP TRIGGER IF EXISTS set_registry_movies_updated_at ON public.registry_movies;
CREATE TRIGGER set_registry_movies_updated_at
    BEFORE UPDATE ON public.registry_movies
    FOR EACH ROW
    EXECUTE FUNCTION update_registry_updated_at_column();
