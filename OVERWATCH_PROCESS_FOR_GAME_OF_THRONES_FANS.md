# OVERWATCH Process Explained For Game Of Thrones Fans

Last updated: June 6, 2026

Think of the Snowflake account as the realm. Many houses use the same roads,
keeps, ledgers, and guards. Every decision has a cost. Every change needs a
record. Every urgent issue needs the right person at the table.

OVERWATCH is the Small Council chamber for Snowflake operations.

## The Realm

| OVERWATCH idea | Game of Thrones-style analogy |
|---|---|
| Snowflake account | The realm everyone depends on. |
| Company filter | Which house or territory you are looking at. |
| Environment filter | Whether the matter belongs to production or the training grounds. |
| Warehouse | The workforce doing the labor. |
| Credits | The coin spent to get work done. |
| Mart | The official ledger that summarizes what happened. |
| Action queue | The council docket of unfinished business. |
| Alert | A warning that needs attention. |
| Owner | The person responsible for answering for the issue. |
| Verification | Proof that the order actually fixed the problem. |

## Why The Ledger Matters

The raw Snowflake logs are like stacks of unsorted reports from across the
realm. They are useful, but too slow to read during a crisis.

OVERWATCH creates a cleaner ledger:

1. gather Snowflake activity
2. summarize the important facts
3. store those facts in the OVERWATCH mart
4. let each section read the ledger quickly

That means the council can talk about facts instead of hunting through piles of
paper.

## The Council Seats

| Section | Council role |
|---|---|
| Executive Landing | The royal briefing: what leaders need to know. |
| DBA Control Room | The council agenda: what must be handled first. |
| Alert Center | The warning desk: what has fired, who owns it, and where it goes. |
| Account Health | The realm health check: where the account is strong or weak. |
| Cost & Contract | The master of coin: credits, dollars, contract pace, and savings. |
| Workload Operations | The operations desk: jobs, tasks, procedures, performance, and errors. |
| Warehouse Health | The labor marshal: whether the workforces are overloaded or wasting coin. |
| Security Posture | The guard captain: MFA, logins, roles, grants, and sharing risk. |
| Change & Drift | The record keeper: what changed, who approved it, and whether it drifted. |
| Architecture Readiness | The builder and planner: ownership, recovery, future controls, and readiness. |

## The Master Of Coin Rules

OVERWATCH treats Snowflake credits like coin.

The current rates are:

- normal compute credit: `$3.68`
- Cortex AI credit: `$2.20`

If a warehouse spends 100 credits, the estimated cost is:

```text
100 x $3.68 = $368.00
```

When Snowflake provides exact metering, OVERWATCH uses the exact number. When
the cost must be split between users, roles, databases, or schemas, OVERWATCH
uses query evidence to allocate the coin and labels it as allocated.

## What Happens When Trouble Starts

A good council does not stop at "there is trouble." It needs proof, owner, and
closure.

The OVERWATCH process is:

1. detect the issue
2. rank the severity
3. show the proof
4. name the owner or route
5. recommend the next action
6. record the action
7. verify the result later
8. report the outcome

Example:

```text
Issue: A warehouse spent far more credits than normal.
Proof: metering shows the increase.
Owner: the matching company or workload owner.
Action: inspect top queries and settings.
Verification: compare post-action spend to the baseline.
Report: show whether coin was saved or no improvement was proven.
```

## Why Access Matters

Not everyone in the realm should hold the same keys.

- Executives see the royal briefing.
- Managers see the broad state and owners.
- Analysts see workload evidence.
- DBAs see the full control room, but powerful actions require proof, approval,
  rollback, audit, and verification.

That keeps the realm governed instead of chaotic.

## The Endgame

OVERWATCH becomes strongest when every problem reaches closure:

```text
warning found
proof gathered
owner assigned
action taken
result verified
leaders briefed
```

That is the production goal: not just knowing the realm is noisy, but knowing
what changed, who owns it, what it cost, and whether the fix held.
