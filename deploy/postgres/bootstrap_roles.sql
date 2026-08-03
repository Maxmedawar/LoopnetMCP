\set ON_ERROR_STOP on

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'medawarcre_migration') THEN
        CREATE ROLE medawarcre_migration NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'medawarcre_app') THEN
        CREATE ROLE medawarcre_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            INHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'medawarcre_admin') THEN
        CREATE ROLE medawarcre_admin NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            INHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'medawarcre_backup') THEN
        CREATE ROLE medawarcre_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            INHERIT NOREPLICATION BYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'medawarcre_admission') THEN
        CREATE ROLE medawarcre_admission NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
END
$roles$;

ALTER ROLE medawarcre_migration WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE medawarcre_app WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT NOREPLICATION NOBYPASSRLS;
ALTER ROLE medawarcre_admin WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT NOREPLICATION NOBYPASSRLS;
-- The backup role bypasses tenant RLS only so pg_dump can see every row. It
-- receives SELECT-only object ACLs and is rejected by the runtime pool.
ALTER ROLE medawarcre_backup WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    INHERIT NOREPLICATION BYPASSRLS;
ALTER ROLE medawarcre_admission WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOREPLICATION NOBYPASSRLS;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Create each application database with medawarcre_migration as its owner and
-- leave datacl at the PostgreSQL default. Explicit database ACL entries are
-- release-contract drift. Login roles, exact PG16 membership options, and
-- passwords are supplied by the deployment secret manager and intentionally
-- remain outside this repository.
