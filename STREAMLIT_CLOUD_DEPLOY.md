# OVERWATCH Streamlit Cloud Deployment

Use this repository with Streamlit Community Cloud:

- Repository: `jfreeze03/OVERWATCH`
- Branch: `main`
- Main file path: `.overwatch_final/app.py`

Community Cloud installs dependencies from the root `requirements.txt`.
The Snowflake-in-Snowflake deployment still uses `.overwatch_final/environment.yml`.

## Secrets

Do not commit secrets to GitHub. In Streamlit Cloud, open **Advanced settings**
or **App settings > Secrets** and add a Snowflake connection block:

```toml
[connections.snowflake]
account = "your_account_identifier"
user = "your_user"
password = "your_password"
role = "SNOW_ACCOUNTADMIN"
warehouse = "COMPUTE_WH"
database = "DBA_MAINT_DB"
schema = "OVERWATCH"
```

For key-pair or SSO authentication, replace the password fields with your
organization's approved Snowflake connection settings.

## Required Snowflake Grants

The running role needs:

```sql
GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE <role>;
GRANT MONITOR ON ACCOUNT TO ROLE <role>;
GRANT USAGE ON DATABASE DBA_MAINT_DB TO ROLE <role>;
GRANT USAGE ON SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
GRANT SELECT, INSERT, UPDATE, DELETE ON FUTURE TABLES IN SCHEMA DBA_MAINT_DB.OVERWATCH TO ROLE <role>;
```

## Local Run

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run .overwatch_final/app.py
```

For local Snowflake credentials, create `.streamlit/secrets.toml` with the
same `[connections.snowflake]` block shown above. Keep that file local only.
