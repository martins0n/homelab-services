-- Minimal schema for the 'message' table, matching repository.py expectations
CREATE TABLE IF NOT EXISTS public.message (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT NOT NULL,
    -- user_id BIGINT, -- Not explicitly in Message model or queries, but often present
    content TEXT NOT NULL,
    "user" TEXT NOT NULL CHECK ("user" IN ('user', 'assistant')), -- From Message model
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Supabase might add other columns like 'updated_at' automatically
);

-- Index used by get_messages query
CREATE INDEX IF NOT EXISTS idx_message_chat_id_created_at ON public.message (chat_id, created_at DESC);

-- Grant permissions if your test user needs them explicitly.
-- Often, the default Supabase user in the connection string has enough rights on the public schema.
-- Example:
-- ALTER TABLE public.message OWNER TO supabase_admin; -- Or your specific role
-- GRANT ALL ON TABLE public.message TO postgres; -- Or your specific test role
-- GRANT USAGE, SELECT ON SEQUENCE public.message_id_seq TO postgres;
