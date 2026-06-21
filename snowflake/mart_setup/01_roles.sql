-- OVERWATCH mart setup split: 01_roles.sql

-- Create OVERWATCH access roles. Grants are applied in 08_grants.sql after objects exist.

-- Source bundle: snowflake/OVERWATCH_MART_SETUP.sql




-- -----------------------------------------------------------------------------
-- 1b. Access roles
-- -----------------------------------------------------------------------------

CREATE ROLE IF NOT EXISTS SNOW_ACCOUNTADMINS;

CREATE ROLE IF NOT EXISTS SNOW_SYSADMINS;


COMMENT ON ROLE SNOW_ACCOUNTADMINS IS
    'Temporary OVERWATCH admin access role for account-level DBA monitoring and guarded actions.';

COMMENT ON ROLE SNOW_SYSADMINS IS
    'Temporary OVERWATCH admin access role for system DBA monitoring and guarded actions.';
