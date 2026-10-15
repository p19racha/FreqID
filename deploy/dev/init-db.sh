#!/bin/bash
set -e

# Initialize application and maintenance roles in PostgreSQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'freqid_app') THEN
            CREATE ROLE freqid_app WITH LOGIN PASSWORD '${FREQID_APP_PASSWORD:-freqid_app_dev_secret}';
        END IF;
        IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'freqid_maint') THEN
            CREATE ROLE freqid_maint WITH LOGIN PASSWORD '${FREQID_MAINT_PASSWORD:-freqid_maint_dev_secret}';
        END IF;
    END
    \$\$;

    GRANT USAGE ON SCHEMA public TO freqid_app;
    GRANT USAGE ON SCHEMA public TO freqid_maint;

    ALTER DEFAULT PRIVILEGES FOR ROLE $POSTGRES_USER IN SCHEMA public
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO freqid_app;
EOSQL
