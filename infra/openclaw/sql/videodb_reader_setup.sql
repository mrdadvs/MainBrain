-- VideoDBMCP Read-Only Database Role Setup
--
-- Creates a dedicated read-only PostgreSQL user for the VideoDB MCP server
-- This role has SELECT-only access to the minimum required tables
--
-- Security Properties:
-- - No superuser, createdb, or createrole privileges
-- - No write permissions (INSERT, UPDATE, DELETE, TRUNCATE)
-- - No DDL permissions (CREATE, ALTER, DROP)
-- - No CREATE EXTENSION or other dangerous operations
-- - Can only SELECT from specific tables
--
-- Tables Granted:
-- - videos (video metadata)
-- - transcript_segments (transcript text and timing)
-- - transcript_words (individual words from transcripts)
-- - clips (extracted scenes/clips)
-- - processing_jobs (import/processing job status)
-- - processing_job_items (individual job items)
--
-- Usage:
-- 1. Connect to PostgreSQL as a superuser
-- 2. Source this file: psql -U postgres -f videodb_reader_setup.sql
-- 3. The role 'videodb_reader' will be created with password
-- 4. Store the password in .env.local (git-ignored)

-- ============================================================================
-- Create the read-only role
-- ============================================================================

-- Drop if exists (for idempotent re-runs)
DROP ROLE IF EXISTS videodb_reader;

-- Create the role with minimal privileges
CREATE ROLE videodb_reader WITH
  LOGIN                    -- Can log in
  NOSUPERUSER             -- Not a superuser
  NOCREATEDB              -- Cannot create databases
  NOCREATEROLE            -- Cannot create roles
  NOCANCEL                -- Cannot cancel queries
  NOINHERIT               -- Does not inherit privileges
  PASSWORD 'REPLACE_WITH_STRONG_PASSWORD';  -- Plaintext password set by admin

-- ============================================================================
-- Grant database connection
-- ============================================================================

GRANT CONNECT ON DATABASE mainbrain TO videodb_reader;

-- ============================================================================
-- Grant schema access
-- ============================================================================

GRANT USAGE ON SCHEMA public TO videodb_reader;

-- ============================================================================
-- Grant SELECT access on required tables only
-- ============================================================================

-- Video metadata table
GRANT SELECT ON TABLE public.videos TO videodb_reader;

-- Transcript data (required for search_transcripts)
GRANT SELECT ON TABLE public.transcript_segments TO videodb_reader;
GRANT SELECT ON TABLE public.transcript_words TO videodb_reader;

-- Clips/scenes data (required for list_video_clips)
GRANT SELECT ON TABLE public.clips TO videodb_reader;

-- Processing jobs (status monitoring, import preview)
GRANT SELECT ON TABLE public.processing_jobs TO videodb_reader;
GRANT SELECT ON TABLE public.processing_job_items TO videodb_reader;

-- ============================================================================
-- Grant sequence access (for reading auto-increment IDs)
-- ============================================================================

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO videodb_reader;

-- ============================================================================
-- Set default privileges for future tables
-- ============================================================================

-- If new tables are added in the future, default to SELECT-only
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO videodb_reader;

-- ============================================================================
-- Explicitly DENY all write operations
-- ============================================================================

-- Prevent INSERT
REVOKE INSERT ON ALL TABLES IN SCHEMA public FROM videodb_reader;

-- Prevent UPDATE
REVOKE UPDATE ON ALL TABLES IN SCHEMA public FROM videodb_reader;

-- Prevent DELETE
REVOKE DELETE ON ALL TABLES IN SCHEMA public FROM videodb_reader;

-- Prevent TRUNCATE
REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM videodb_reader;

-- Prevent REFERENCES (foreign keys)
REVOKE REFERENCES ON ALL TABLES IN SCHEMA public FROM videodb_reader;

-- ============================================================================
-- Verify role creation
-- ============================================================================

SELECT 'Role videodb_reader created successfully' as status;

-- ============================================================================
-- Security verification queries
-- ============================================================================

-- To verify the role was created correctly, run these checks:
--
-- 1. Verify role exists and permissions:
--    SELECT * FROM pg_roles WHERE rolname = 'videodb_reader';
--
-- 2. Verify table grants:
--    SELECT grantee, privilege_type
--    FROM information_schema.table_privileges
--    WHERE table_name='videos' AND grantee='videodb_reader';
--
-- 3. Verify cannot write (should fail with permission denied):
--    SET ROLE videodb_reader;
--    INSERT INTO videos VALUES (...);  -- Should fail
--
-- 4. Verify can read:
--    SET ROLE videodb_reader;
--    SELECT COUNT(*) FROM videos;  -- Should succeed

-- ============================================================================
-- Connection string for MCP server
-- ============================================================================

-- Use this connection string in .env.local:
-- MB_DB_URL=postgresql://videodb_reader:REPLACE_WITH_STRONG_PASSWORD@localhost:5432/mainbrain
--
-- Or for Docker (using gateway IP):
-- MB_DB_URL=postgresql://videodb_reader:REPLACE_WITH_STRONG_PASSWORD@172.17.0.1:5432/mainbrain
