-- OVERWATCH Mart Setup - snowsql runner
--
-- Executes the numbered setup files in the correct deployment order within a
-- single snowsql session. Run from this directory:
--
--   snowsql -c <connection> -f 00_run_all.sql
--
-- This is equivalent to deploying ../OVERWATCH_MART_SETUP.sql in one shot.
-- The files must run in order: 01 sets the USE DATABASE/SCHEMA context and 02
-- installs FUTURE grants that later objects inherit.

!source 01_runtime_warehouse.sql
!source 02_roles_grants.sql
!source 03_config_audit_tables.sql
!source 04_mart_tables.sql
!source 05_load_procedures.sql
!source 06_alert_framework.sql
!source 07_tasks.sql
!source 08_validation.sql
