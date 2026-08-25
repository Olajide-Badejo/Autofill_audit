# CI proof of failure

Continuous integration that has never failed has not been shown to work. A gate
check observed only in its green state is indistinguishable from a gate check
that always returns green, and the difference between those two only becomes
visible on the day something is actually wrong, which is the worst possible day
to discover it.

So every job in [`ci.yml`](../.github/workflows/ci.yml) has been deliberately
broken once, on its own scratch branch, by a single change, and the resulting
red run is linked below with the message it produced. The scratch branches were
deleted afterwards, locally and on the remote; the run records outlive them.

This file is updated whenever a job is added or its contents change materially.
A new job without a red run recorded here is a job that is not yet trusted.

## Green reference

The state every red run below is measured against. Same workflow file, same
commit lineage, all six jobs green.

| Run | Branch | Result |
|---|---|---|
| [`32795830668`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795830668) | `main` | six of six jobs green |

## The six red runs

Each row is one scratch branch carrying one change.

### `lint`

Run: [`32795840659`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795840659)

Breakage: an em dash pasted into a module docstring. ruff and mypy are both
indifferent to the character, so the dash check inside the lint job is the only
thing that can catch it.

```
check_dashes: 1 violation found
src/autofill_audit/loader.py:3:14: forbidden U+2014 em dash
```

Other five jobs: green.

### `types`

Run: [`32795843313`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795843313)

Breakage: a return annotation changed to contradict the function body. Runtime
behaviour is unchanged, so no test can see it.

```
src/autofill_audit/taxonomy.py:212: error: Incompatible return value type (got "str", expected "int")  [return-value]
Found 1 error in 1 file (checked 33 source files)
```

Other five jobs: green.

### `test`

Run: [`32795844236`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795844236)

Breakage: an assertion changed to contradict the specification's token count.

```
FAILED tests/unit/test_taxonomy.py::test_spec_token_count_is_thirty_seven - AssertionError: assert 37 == 38
```

Other five jobs: green.

### `reachability`

Run: [`32795850460`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795850460)

Breakage: a second enum member declared with a value an existing member already
holds. Python does not raise on this. The new member silently becomes an alias,
disappears from iteration, and shrinks the label space while still looking live
at every call site, which is exactly the drift law 2 exists to catch.

```
check_reachability: 1 check(s) failed
  [PASS] taxonomy populated: 37 specification tokens plus 5 extras
  [FAIL] no duplicate label values: POSTCODE aliases POSTAL_CODE on value 'postal-code'
  [PASS] groups partition the taxonomy: 6 groups cover 42 labels exactly once
  [PASS] no stray label literals: 36 modules scanned, taxonomy remains the only definition
```

**The `test` job also went red on this branch, and that is the intended
behaviour rather than a leak.** Two unit tests assert the same property
independently: one checks the enum directly, the other asserts that the
reachability check passes on the real tree. A taxonomy defect that only the CI
script noticed, and that no test noticed, would mean the property was enforced
in one place instead of two.

```
FAILED tests/unit/test_taxonomy.py::test_no_duplicate_values_and_no_hidden_aliases - AssertionError: assert 43 == 42
FAILED tests/unit/test_check_reachability.py::test_main_exits_zero_on_the_real_tree - AssertionError: assert 1 == 0
```

Other four jobs: green.

### `traceability`

Run: [`32795852532`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795852532)

Breakage: a bare percentage added to README prose with nothing behind it. This
is the exact shape law 3 forbids: a number a reader would take as measured, with
no committed result file to resolve it to.

```
check_traceability: 1 untraceable number found
README.md:49: percentage in prose with no result-file reference: 'It classifies 94% of fields correctly.'
```

Other five jobs: green.

### `build`

Run: [`32795858179`](https://github.com/Olajide-Badejo/Autofill_audit/actions/runs/32795858179)

Breakage: the console entry point pointed at a function that does not exist. The
wheel still builds and pipx still installs it cleanly, which is the point: only
running the installed command catches this, which is why the build job installs
the artefact into a clean environment and runs it rather than stopping at a
successful build.

```
File "/home/runner/work/_temp/pipx-bin/autofill-audit", line 3, in <module>
    from autofill_audit.cli import does_not_exist
ImportError: cannot import name 'does_not_exist' from 'autofill_audit.cli'
```

Other five jobs: green.
