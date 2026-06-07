# OVERWATCH Process Explained For A 16 Year Old

Last updated: June 6, 2026

Imagine a big company uses Snowflake like a giant shared computer for data.
People run reports, load data, train AI features, check security, and change
databases. That giant computer costs money every time work runs.

OVERWATCH is the dashboard that helps the DBA team answer:

- Is anything broken?
- What is getting slow?
- What is spending too much money?
- Who owns the problem?
- What proof do we have?
- Did the fix actually work?

## The Simple Version

OVERWATCH is like the control room for Snowflake.

Snowflake produces a lot of logs. Those logs say things like:

- which warehouse ran
- how many credits it used
- which user ran a query
- which task failed
- which role changed access
- which database changed
- how much Cortex AI was used

Instead of making DBAs dig through all those logs manually, OVERWATCH organizes
the logs into smaller tables called marts. The app reads those marts and turns
them into useful screens.

## Why The Mart Exists

Raw Snowflake logs can be huge and slow to scan.

The mart is like a clean notebook:

1. every hour, OVERWATCH reads the big logs
2. it summarizes the important parts
3. it stores the summary in smaller tables
4. the dashboard reads the smaller tables quickly

That makes the app faster and cheaper to use.

## How Cost Works

Snowflake uses credits. Credits turn into dollars.

OVERWATCH uses:

- `$3.68` for normal Snowflake compute credits
- `$2.20` for Cortex AI credits

If a warehouse uses 10 credits, the estimated compute cost is:

```text
10 credits x $3.68 = $36.80
```

When Snowflake gives exact billing numbers, OVERWATCH uses those. When
Snowflake only gives warehouse-level credits, OVERWATCH divides the cost across
users, roles, databases, or schemas based on query evidence.

## What The Main Screens Do

| Screen | Simple explanation |
|---|---|
| Executive Landing | A slide-ready summary for leadership. |
| DBA Control Room | The morning checklist: what needs attention first. |
| Alert Center | Shows alerts and who should receive them. |
| Account Health | Checks whether the Snowflake account looks healthy. |
| Cost & Contract | Explains spending and contract usage. |
| Workload Operations | Shows query, task, job, procedure, and error status. |
| Warehouse Health | Shows whether warehouses are too busy, too slow, or wasting money. |
| Security Posture | Checks login, MFA, roles, grants, and sharing risk. |
| Change & Drift | Shows what changed and whether it has approval evidence. |
| Architecture Readiness | Checks whether the account is organized, owned, and ready for future needs. |

## What Happens When Something Looks Bad

OVERWATCH should not just say "something is wrong." It should help the DBA act.

The process is:

1. find the issue
2. show why it matters
3. show proof
4. identify the owner
5. suggest the next action
6. save the action in the queue
7. track whether the fix worked

Example:

```text
Problem: WH_TRXS_QUERY used way more credits than last week.
Proof: warehouse metering shows a 40 percent increase.
Owner: Trexis data team.
Action: review top queries and warehouse settings.
Verification: compare the next 7 days of cost to the baseline.
```

## Why Roles Matter

Not everyone should see the same controls.

- Executives need summaries.
- Analysts need workload details.
- Managers need status and ownership.
- DBAs need full control, but with approvals and audit trails.

That keeps powerful buttons away from people who do not need them.

## What "Production Ready" Means

For OVERWATCH, production ready means:

- the numbers match the official Snowflake sources
- the app loads quickly
- the docs match the current app
- old names are cleaned up
- risky actions require approval and audit proof
- cost formulas are tested
- alerts and action queues have owners
- a DBA can prove whether a fix worked

## The Big Idea

OVERWATCH is not just a dashboard. It is a system for turning Snowflake activity
into clear DBA decisions:

```text
What happened?
Why did it happen?
Who owns it?
What should we do?
Did the fix work?
What do we tell leadership?
```
