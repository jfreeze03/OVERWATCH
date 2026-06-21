# OVERWATCH mart setup deployment order

The monolithic `snowflake/OVERWATCH_MART_SETUP.sql` has been split into ordered
files to keep reviews and deployments maintainable. Run the files in numeric
order from this directory:

1. `01_roles.sql` - access roles and role comments.
2. `02_databases.sql` - database, warehouse, resource monitor, and database context.
3. `03_schemas.sql` - schema and schema context.
4. `04_tables.sql` - configuration, audit, alert, and mart tables plus seed rows.
5. `05_views.sql` - views used by the app and validation surfaces.
6. `06_procedures.sql` - functions and refresh/staging procedures.
7. `07_tasks.sql` - scheduled task graph and resume statements.
8. `08_grants.sql` - role grants after objects exist.
9. `09_validation.sql` - smoke checks and optional initial refresh calls.

For SnowSQL-style clients you can run each file explicitly, for example:

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

Snowflake Worksheets do not support `!source`; paste or execute the files in the
same numeric order. Keep object edits in the numbered files rather than rebuilding
a monolithic setup script.
