-- Open-Omniscience PostgreSQL Initialization Script
-- 
-- This script is executed when the PostgreSQL container starts for the first time.
-- It creates the necessary database, extensions, and initial data.
--
-- Usage: Mount this file to /docker-entrypoint-initdb.d/init.sql in PostgreSQL container
--
-- Author: Open-Omniscience Team
-- License: Open Source (MIT)

-- Create the database if it doesn't exist
-- Note: The database is created by PostgreSQL init based on POSTGRES_DB env var
-- This script runs after the database is created

-- Connect to the database
\c open_omniscience

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create schema for application tables (optional, but recommended)
CREATE SCHEMA IF NOT EXISTS omniscience;

-- Set search path
SET search_path TO omniscience, public;

-- Create tablespace for better performance (optional)
-- CREATE TABLESPACE omniscience_data LOCATION '/var/lib/postgresql/omniscience_data';

-- Create a function to check if a table exists
CREATE OR REPLACE FUNCTION table_exists(table_name text) RETURNS boolean AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = 'omniscience' AND table_name = $1
    );
END;
$$ LANGUAGE plpgsql;

-- Create a function to check if an index exists
CREATE OR REPLACE FUNCTION index_exists(index_name text) RETURNS boolean AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM pg_indexes 
        WHERE schemaname = 'omniscience' AND indexname = $1
    );
END;
$$ LANGUAGE plpgsql;

-- Create a function to check if a sequence exists
CREATE OR REPLACE FUNCTION sequence_exists(sequence_name text) RETURNS boolean AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM pg_sequences 
        WHERE schemaname = 'omniscience' AND sequencename = $1
    );
END;
$$ LANGUAGE plpgsql;

-- Create application user with limited privileges (optional)
-- This is created by PostgreSQL init based on POSTGRES_USER env var

-- Grant necessary permissions
GRANT USAGE ON SCHEMA omniscience TO omniscience;
GRANT ALL PRIVILEGES ON SCHEMA omniscience TO omniscience;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA omniscience TO omniscience;

-- Create a read-only user for analytics (optional)
-- Uncomment and customize as needed
-- CREATE ROLE omniscience_reader WITH LOGIN PASSWORD 'reader_password';
-- GRANT CONNECT ON DATABASE open_omniscience TO omniscience_reader;
-- GRANT USAGE ON SCHEMA omniscience TO omniscience_reader;
-- GRANT SELECT ON ALL TABLES IN SCHEMA omniscience TO omniscience_reader;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA omniscience GRANT SELECT ON TABLES TO omniscience_reader;

-- Create a function to update permissions for new tables
CREATE OR REPLACE FUNCTION update_omniscience_permissions() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'CREATE TABLE' THEN
        GRANT ALL PRIVILEGES ON TABLE omniscience."" || TG_TABLE_NAME || "" TO omniscience;
        -- GRANT SELECT ON TABLE omniscience."" || TG_TABLE_NAME || "" TO omniscience_reader;
    ELSIF TG_OP = 'CREATE SEQUENCE' THEN
        GRANT ALL PRIVILEGES ON SEQUENCE omniscience."" || TG_TABLE_NAME || "" TO omniscience;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Create event triggers for automatic permission updates (PostgreSQL 10+)
-- Note: Event triggers require superuser privileges
-- This is commented out as it may not work in all environments
-- Consider running this manually or using a different approach

-- CREATE EVENT TRIGGER update_permissions_on_create
-- ON ddl_command_end
-- WHEN TAG IN ('CREATE TABLE', 'CREATE SEQUENCE')
-- EXECUTE FUNCTION update_omniscience_permissions();

-- Create a function to create all necessary indexes
CREATE OR REPLACE FUNCTION create_omniscience_indexes() RETURNS VOID AS $$
BEGIN
    -- These indexes will be created by SQLAlchemy when tables are created
    -- This function is here for reference and manual index creation if needed
    
    RAISE NOTICE 'Omniscience indexes will be created by SQLAlchemy';
END;
$$ LANGUAGE plpgsql;

-- Create a function to optimize database performance
CREATE OR REPLACE FUNCTION optimize_omniscience_database() RETURNS VOID AS $$
BEGIN
    -- Run VACUUM ANALYZE on all tables
    PERFORM vacuum(analyze => true, verbose => true);
    
    -- Reindex all indexes
    -- PERFORM reindex schema omniscience;
    
    RAISE NOTICE 'Database optimization completed';
END;
$$ LANGUAGE plpgsql;

-- Create a function to backup the database
CREATE OR REPLACE FUNCTION backup_omniscience_database(backup_name text) RETURNS VOID AS $$
DECLARE
    backup_path text;
    backup_command text;
BEGIN
    backup_path := '/backups/' || backup_name || '.sql';
    backup_command := 'pg_dump -U ' || current_user || ' -d ' || current_database() || 
                      ' -f ' || backup_path || ' -F c --compress=9';
    
    -- Note: This function is for reference only
    -- Actual backup should be done using pg_dump from command line
    RAISE NOTICE 'To backup: %', backup_command;
END;
$$ LANGUAGE plpgsql;

-- Create a function to restore the database
CREATE OR REPLACE FUNCTION restore_omniscience_database(backup_name text) RETURNS VOID AS $$
DECLARE
    backup_path text;
    restore_command text;
BEGIN
    backup_path := '/backups/' || backup_name || '.sql';
    restore_command := 'pg_restore -U ' || current_user || ' -d ' || current_database() || 
                       ' -c ' || backup_path;
    
    -- Note: This function is for reference only
    -- Actual restore should be done using pg_restore from command line
    RAISE NOTICE 'To restore: %', restore_command;
END;
$$ LANGUAGE plpgsql;

-- Create a view for monitoring database size
CREATE OR REPLACE VIEW omniscience.database_size AS
SELECT 
    table_schema,
    table_name,
    pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) as size,
    pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)) as size_bytes
FROM information_schema.tables 
WHERE table_schema = 'omniscience'
ORDER BY pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)) DESC;

-- Create a view for monitoring table statistics
CREATE OR REPLACE VIEW omniscience.table_statistics AS
SELECT 
    table_schema,
    table_name,
    (xpath('/row/cnt/text()', query_to_xml(format('SELECT COUNT(*) as cnt FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text::int as row_count,
    pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) as size,
    pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)) as size_bytes
FROM information_schema.tables 
WHERE table_schema = 'omniscience' AND table_type = 'BASE TABLE'
ORDER BY pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name)) DESC;

-- Create a function to get database health
CREATE OR REPLACE FUNCTION omniscience.get_database_health() RETURNS JSON AS $$
DECLARE
    health_json JSON;
BEGIN
    SELECT json_build_object(
        'status', 'healthy',
        'timestamp', NOW(),
        'database', current_database(),
        'user', current_user,
        'schema', current_schema(),
        'postgres_version', version(),
        'tables_count', (SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'omniscience'),
        'total_size', (SELECT SUM(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) 
                      FROM information_schema.tables WHERE table_schema = 'omniscience')
    ) INTO health_json;
    
    RETURN health_json;
END;
$$ LANGUAGE plpgsql;

-- Log initialization completion
RAISE NOTICE 'Open-Omniscience PostgreSQL initialization completed!';
RAISE NOTICE 'Database: open_omniscience';
RAISE NOTICE 'User: omniscience';
RAISE NOTICE 'Extensions: uuid-ossp, pg_trgm, pgcrypto';
RAISE NOTICE 'Schema: omniscience';
