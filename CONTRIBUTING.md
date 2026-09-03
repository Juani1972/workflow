# Contributing guide

This guide documents the pattern already followed by this repo's 7
modules and 4 workflows, so adding a new one means copying the
structure instead of inventing it from scratch. It's not a formal
policy — it's what already worked here, written down so it doesn't
have to be rediscovered.

## First of all: the technical honesty note

This repo has a convention that runs through everything: **never
claim something is validated if it isn't**. If you write new code
that calls an external API, it has to be made explicit in three
places:

1. A comment at the top of the file (`client.py` or `actions.py`)
   saying where the endpoint format came from (official
   documentation, version, date) and that it hasn't been tested
   against a real account.
2. The field `"external_calls_validated_against_real_account": false`
   in the module's `module_spec.json`.
3. A section in the module's `README.md` listing what's left to
   confirm.

If at some point it IS validated against a real account (following
`VALIDATION.md`), these are the three places that need updating to
`true` — updating just one isn't enough.

## Two kinds of module

### A) Pure-logic module (no network calls)

Examples: `team-health-analyzer`, `meeting-debt-tracker`,
`budget-guardian-core`.

This is the easiest kind of module to trust, because it can be
tested 100% without mocking anything. Use it when the logic you're
writing doesn't need to talk to any external service — it just
transforms data another node in the workflow already fetched.

Structure:
```
modules/my-module/
├── __init__.py          # re-exports the public functions
├── actions.py           # the functions, with complete docstrings
├── module_spec.json      # manifest (see below)
├── README.md
└── tests/
    └── test_actions.py   # no mocks, no network — real edge cases
```

`actions.py` conventions:
- `from __future__ import annotations` at the top.
- Every public function has a docstring: what it does, `Args`,
  `Returns`, and `Raises` if applicable.
- Never mutate the arguments it receives (lists, dicts) — return new
  copies. All existing modules do this on purpose, to make it easy to
  reason about what changed at each step of the workflow.
- For traffic-light style states (🟢/🟡/🔴), follow the pattern in
  `team_health_analyzer.classify_team_health`: `SEVERITY_*` or
  `STATUS_*` constants, a `*_EMOJI` dict, and a `classify_*` function
  that takes optional thresholds with a default.

### B) External provider module (calls a real API)

Examples: `calcom-pro`, `gcal`, `slack`, `sheets`.

Structure:
```
modules/my-provider/
├── __init__.py
├── client.py             # auth + requests, WITHOUT business logic
├── actions.py            # which endpoint to call, with what payload
├── module_spec.json
├── README.md
├── requirements.txt       # typically just "requests>=2.31,<3"
└── tests/
    ├── test_actions.py    # with the HTTP layer mocked (unittest.mock)
    └── test_integration.py  # calls the real API, does NOT run by default
```

**`client.py` vs `actions.py`:** the client only knows how to
authenticate and build generic requests (`get`/`post`/`patch`/`delete`).
All the "which endpoint, which payload" logic lives in `actions.py`.
This is deliberate — it lets the client be reused for a new endpoint
without touching it, and separates "is the auth right?" from "is the
payload right?" when something fails.

**`test_actions.py`** mocks `client.requests.request` (or `.post` for
the OAuth exchange) with `unittest.mock.patch` — it never makes a
real network call, never needs credentials. It verifies that the
URL, headers, and payload are built correctly.

**`test_integration.py`** DOES call the real API, but:
- It never runs by default — it uses `pytest.mark.skipif` gated by
  environment variables (`RUN_LIVE_TESTS=1` at minimum).
- Tests that create/modify data also require `ALLOW_LIVE_WRITES=1` —
  `RUN_LIVE_TESTS=1` alone is never enough to write.
- If the module has a delete action (like `gcal.delete_event`), the
  test uses it to clean up after itself. If it doesn't, the test says
  so explicitly in a print statement and in the docstring ("doesn't
  delete, do it by hand").
- Document the necessary setup in `VALIDATION.md` (see the
  corresponding section there as a template — they're all almost
  identical in structure).

**⚠️ Name collision:** all provider modules use the generic names
`client.py` and `actions.py`. This works perfectly when each module
is imported in isolation (which is how every `tests/test_actions.py`
does it), but breaks if the same process needs to import more than
one provider module at once — `import actions` resolves to whichever
was last inserted into `sys.path`, not the one you need. The GUI
(`fika-sync/gui/provider_modules.py`) already solved this with a
loader that isolates each import; if your contribution needs to load
two or more provider modules in the same process, reuse that pattern
(or `sys.modules.pop("client", None)` /
`sys.modules.pop("actions", None)` before each import) instead of
rediscovering the bug.

## `module_spec.json`: the manifest

They all follow the same shape. Required fields:

```json
{
  "_readme": "Explain here whether this manifest's format is a reasoned reconstruction or something confirmed, and against what.",
  "module_id": "my-module",
  "version": "0.1.0",
  "display_name": "Readable Name",
  "description": "One sentence.",
  "language": "python",
  "entrypoint": "actions.py",
  "requires_credentials": true or false,
  "external_calls": true or false,
  "actions": [
    {
      "name": "function_name",
      "function": "function_name",
      "inputs": ["arg1", "arg2"],
      "output": "what_it_returns"
    }
  ],
  "tests": {
    "framework": "pytest",
    "path": "tests/test_actions.py",
    "status_as_of_YYYY_MM_DD": "N/N passing"
  }
}
```

If `external_calls` is `true`, also add:
- `"required_env_vars"`: list of environment variables it needs.
- `"external_calls_validated_against_real_account"`: `false` until
  it's actually validated.

Validate that the JSON is valid before committing (`python3 -c
"import json; json.load(open('module_spec.json'))"`) — it's easy to
break by hand and it goes unnoticed until something tries to parse
it.

## Adding a new workflow

Structure:
```
workflows/my-workflow/
├── workflow.csv
├── engine_spec.json
└── README.md
```

(`fika-sync/` is the only workflow that also has its own `config/`,
`.env.example` and `gui/` folders — the others don't need to repeat
that, they share `fika-sync/`'s `.env.example`.)

### `workflow.csv`

Columns: `node_id,type,provider,action,depends_on,description`.

- `type`: `trigger`, `transform`, or `effect`.
- `provider`: the folder name under `modules/`, or `railcall` /
  `zoom` if it's a capability external to the repo (there's no
  `modules/railcall/` folder because RailCall is the platform itself,
  not something this repo implements).
- `action`: for nodes whose `provider` is a real module, this has to
  be **exactly** the name of a function that exists in that module's
  `actions.py` — not a made-up name that sounds right. For RailCall
  triggers (`cron_weekly`, `slash_command`, `webhook_*`), it's an
  event type, not a function.
- `depends_on`: ids separated by `;`, or empty if it doesn't depend
  on anything (typically triggers).

**Before considering a `workflow.csv` finished, run this validation**
(it's the same one used to verify this repo's 4 workflows):

```python
import csv

with open('workflows/my-workflow/workflow.csv') as f:
    rows = list(csv.DictReader(f))

ids = {r['node_id'] for r in rows}
dep_errors = [
    f"{r['node_id']} -> '{d}' does not exist"
    for r in rows
    for d in (r['depends_on'].split(';') if r['depends_on'] else [])
    if d not in ids
]
print(f"Nodes: {len(rows)} | Broken dependencies: {len(dep_errors)}")
for e in dep_errors:
    print(" -", e)
```

And compare each node's `action` against the real functions exported
by the corresponding module's `actions.py` — by hand or with a script
like the one used in this session (see `README.md`'s history if the
full example is needed). This already caught a real bug once
(`update_threshold` in `fika-sync/workflow.csv` pointing to the wrong
function) — it's worth always running it, not assuming "it's
probably fine".

### `engine_spec.json`

Same shape as `fika-sync/engine_spec.json`: `_readme`, `workflow_id`,
`version`, `airlock`, `providers` (one per distinct `provider` that
appears in `workflow.csv`, with their `capabilities` and
`validated_against_real_account`), `internal_modules` (the
pure-logic modules it uses), and `spend_limits`/`retry_policy`.

If the workflow depends on a RailCall capability that isn't
confirmed (like `webhook_calendar_change` in `meeting-debt`, or
`get_spend_log`/`pause_workflow` in `budget-guardian`), mark it
explicitly under `unconfirmed_capabilities` inside the `railcall`
provider, with a note on what's left to confirm. Don't leave it
implicit.

### Workflow `README.md`

At minimum, cover:
1. What the workflow does, in one or two sentences.
2. Status: how many nodes, whether the DAG is verified, what tests
   back up the logic it reuses.
3. Which capabilities (this repo's own, or RailCall's) are still
   unconfirmed.
4. A "plan B" if those unconfirmed capabilities end up not existing —
   don't leave the workflow as "all or nothing".

## Reuse existing modules before writing a new one

Before creating a new pure-logic module, check whether an existing
one already solves the problem for a different purpose.
`onboarding-automator` reuses `team_health_analyzer.rebalance_queue`
to pick an onboarding buddy, not just to reorder a meeting queue —
same function, different use, zero new code. It's easier to maintain
a behavior that's already tested than a new one that does almost the
same thing.

## Checklist before considering a new module or workflow finished

- [ ] Unit tests passing (`python3 -m pytest tests/test_actions.py -v`).
- [ ] If it calls an external API: `test_integration.py` written,
      guarded with `RUN_LIVE_TESTS`/`ALLOW_LIVE_WRITES`, and a new
      section in `VALIDATION.md`.
- [ ] `module_spec.json` (or `engine_spec.json` for workflows) is
      valid JSON and has the technical honesty note if something
      isn't confirmed.
- [ ] If it's a workflow: `workflow.csv` validated programmatically
      (0 broken dependencies, 0 orphan actions).
- [ ] `README.md` written, without claiming something works if it
      wasn't actually tested.
- [ ] If the module/workflow changes something another README
      already documented (test counts, provider list, etc.), also
      update the repo's root `README.md` — don't leave stale numbers
      floating around.
