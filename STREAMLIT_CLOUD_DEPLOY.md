# OVERWATCH Streamlit Cloud Deployment

Use this repository with Streamlit Community Cloud:

- Repository: `jfreeze03/OVERWATCH`
- Branch: `main`
- Main file path: `streamlit_app.py`

Community Cloud installs dependencies from the root `requirements.txt`.
The Snowflake-in-Snowflake deployment still uses `.overwatch_final/environment.yml`.
Using the root `streamlit_app.py` wrapper keeps Community Cloud from selecting
the Snowflake-specific conda manifest under `.overwatch_final/`.

## Snowflake Connection

Do not commit Snowflake credentials to GitHub. In Streamlit Cloud, configure
the Snowflake connection in **Advanced settings** or **App settings > Secrets**
using your organization's approved authentication method. Keep all account,
user, password, token, private-key, and SSO settings in Streamlit Cloud or your
Snowflake-managed secret store, not in this repository.

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
streamlit run streamlit_app.py
```

Local development can run without Snowflake credentials. In that mode, the app
loads the interface and shows offline notices for live data panels until it is
deployed to a host with a configured Snowflake connection.
