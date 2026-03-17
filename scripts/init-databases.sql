-- Initialize separate databases for each service sharing the same PG instance.
-- This script runs once on first container start via /docker-entrypoint-initdb.d/.

-- Plane database
SELECT 'CREATE DATABASE plane'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'plane')\gexec

-- Langfuse database
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec

-- RAGFlow database
SELECT 'CREATE DATABASE ragflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ragflow')\gexec

-- Firecrawl database
SELECT 'CREATE DATABASE firecrawl'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'firecrawl')\gexec

-- Initialize Firecrawl NUQ schema
\c firecrawl
\i /docker-entrypoint-initdb.d/02-init-firecrawl.sql

-- daemon database (default, created by POSTGRES_DB env var)
-- Ensure pgvector extension is available in daemon DB
\c daemon
CREATE EXTENSION IF NOT EXISTS vector;

-- Also install pgvector in langfuse DB (used for embeddings)
\c langfuse
CREATE EXTENSION IF NOT EXISTS vector;
