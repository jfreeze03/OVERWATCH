# OVERWATCH mart setup deployment order

The canonical one-shot bundle remains `snowflake/OVERWATCH_MART_SETUP.sql` for
existing deployments and tests. The same setup is now split into numbered files
for reviewable, production deployment runs.

Run the files in this order from a role that can create the database, schema,
warehouse, tasks, procedures, and Snowflake account-usage readers:

1. `01_roles.sql` - create app access roles only.
2. `02_databases.sql` - create `DBA_MAINT_DB`, `OVERWATCH_WH`, and the resource monitor.
3. `03_schemas.sql` - create/select `DBA_MAINT_DB.OVERWATCH`.
4. `04_tables.sql` - create/evolve tables and seed configuration rows.
5. `05_views.sql` - create review and triage views.
6. `06_procedures.sql` - create SQL functions and load/refresh procedures.
7. `07_tasks.sql` - create and resume scheduled tasks.
8. `08_grants.sql` - apply role grants after objects exist.
9. `09_validation.sql` - run smoke checks and optional initial refresh calls.

If your SQL client supports SnowSQL-style source commands, you can run the same
order with:

```sql
!source snowflake/mart_setup/01_roles.sql
!source snowflake/mart_setup/02_databases.sql
!source snowflake/mart_setup/03_schemas.sql
!source snowflake/mart_setup/04_tables.sql
!source snowflake/mart_setup/05_views.sql
!source snowflake/mart_setup/06_procedures.sql
!source snowflake/mart_setup/07_tasks.sql
!source snowflake/mart_setup/08_grants.sql
!source snowflake/mart_setup/09_validation.sql
```

Use `snowflake/OVERWATCH_MART_VALIDATION.sql` after deployment to verify object
counts and readiness-contract views. Keep first-paint app paths on mart tables;
do not replace the split deployment with full ACCOUNT_USAGE scans during app
render.
