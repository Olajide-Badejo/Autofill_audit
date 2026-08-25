# CI proof of failure

Continuous integration that has never failed has not been shown to work. A gate
check observed only in its green state is indistinguishable from a gate check
that always returns green, and the difference between those two only becomes
visible on the day something is actually wrong, which is the worst possible day
to discover it.

So every job in [`ci.yml`](../.github/workflows/ci.yml) has been deliberately
broken once, on its own scratch branch, from a single change, and the resulting
red run is linked below. The scratch branches were deleted afterwards, locally
and on the remote; the run records outlive them.

This file is updated whenever a job is added or its contents change materially.
A new job without a red run recorded here is a job that is not yet trusted.

## Green reference

The state every red run below is measured against.

| Run | Branch | Result |
|---|---|---|
| GREEN_RUN_URL | `main` | all six jobs green |

## The six red runs

| Job | Deliberate breakage | Red run |
|---|---|---|
| `lint` | RED_LINT_BREAKAGE | RED_LINT_URL |
| `types` | RED_TYPES_BREAKAGE | RED_TYPES_URL |
| `test` | RED_TEST_BREAKAGE | RED_TEST_URL |
| `reachability` | RED_REACH_BREAKAGE | RED_REACH_URL |
| `traceability` | RED_TRACE_BREAKAGE | RED_TRACE_URL |
| `build` | RED_BUILD_BREAKAGE | RED_BUILD_URL |
