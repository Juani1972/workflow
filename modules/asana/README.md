# your-handle/asana

Instantiates real tasks from Task Templates, used by
`onboarding-automator/assign_onboarding_tasks`.

## Status

✅ Real, confirmed endpoint: `POST /task_templates/{gid}/instantiateTask`.
This was **not obvious** -- for a long time Asana offered no way to
instantiate templates via API (only duplicating existing tasks, see
the official developer forum threads cited in `handler.py`). It was
added later as a dedicated endpoint.

⚠️ The endpoint returns an **asynchronous job**, not the created task
directly. This handler doesn't poll `GET /jobs/{job_gid}` until the
job finishes -- that's left pending if the caller needs to confirm
the task already exists (for example before sending the welcome
message on Slack, to avoid announcing something that hasn't been
created yet).

⚠️ Not tested against a real account.

## Auth

Personal access token or OAuth2, `ASANA_ACCESS_TOKEN` environment
variable.
