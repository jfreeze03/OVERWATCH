# OVERWATCH Release Process

Use this process when turning a candidate commit into a release. The release
manifest is the source of truth for the current candidate; historical evidence
files are allowed, but they cannot stand in for current release evidence unless
their commit SHA matches the manifest.

## Steps

1. Choose the release candidate SHA and record it in `docs/OVERWATCH_RELEASE_MANIFEST.md`.
2. Run the validation commands listed in `docs/OVERWATCH_PRODUCTION_READINESS.md`.
3. Fill a release evidence file under `docs/releases/` and make the manifest point to it.
4. Confirm the evidence file commit SHA matches the manifest commit SHA.
5. Record browser, performance, deployment, mart, secrets, and guarded-operation results honestly.
6. Treat live Snowflake regression as current evidence only when it actually ran for the candidate; otherwise cite prior evidence and say it was not rerun with a reason.
7. Deploy or stage using `STREAMLIT_CLOUD_DEPLOY.md` only after the manifest gates are release-ready.
8. Tag the release only after `docs/OVERWATCH_RELEASE_MANIFEST.md` is release-ready and points to matching evidence.
9. Use `snowflake/OVERWATCH_MART_DROP.sql` only as a reset or rollback reference, not as a normal release step.

## Guardrails

- Never use historical evidence as current release evidence unless the SHA matches the manifest.
- Never claim live Snowflake regression passed unless the credentialed run actually happened.
- Do not drop, rename, disable, or rewrite mart objects during release evidence collection.
- Keep rollback/reset notes linked to `STREAMLIT_CLOUD_DEPLOY.md` and `snowflake/OVERWATCH_MART_DROP.sql`.
