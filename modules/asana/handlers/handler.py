"""Handlers for the your-handle/asana module.

VALIDATED (29 Aug 2026) against Asana API's current official
documentation (developers.asana.com/reference):

  - Base URL: https://app.asana.com/api/1.0
  - POST /task_templates/{template_gid}/instantiateTask -- instantiates
    a real task from a Task Template. This endpoint DOES exist (not
    obvious: for a long time Asana had no way to instantiate templates
    via API, only "duplicate" existing tasks -- see Asana's developer
    forum, thread "API to use a task template?". It was added later as
    /task_templates/{gid}/instantiateTask).
  - The endpoint returns a JOB (asynchronous processing), NOT the
    created task directly -- similar to the duplicate-task pattern.
    This handler does NOT poll the job until it finishes; it returns
    the job as Asana delivers it. If the caller needs the final
    task_gid, they have to poll GET /jobs/{job_gid} themselves (out of
    this module's scope for now).
  - Auth: Bearer token (personal access token or OAuth2).

Each function receives:
  inputs:  the body already validated against input_schema in module.json
  context: RailCall runtime info (install_pubkey, org_id, etc.)
"""
import os
import requests

BASE_URL = "https://app.asana.com/api/1.0"


def _headers() -> dict:
    token = os.environ.get("ASANA_ACCESS_TOKEN")
    if not token:
        raise RuntimeError(
            "ASANA_ACCESS_TOKEN is not configured. In production this is "
            "injected via RailCall Studio > Integrations, never hardcoded."
        )
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def create_tasks_from_template(inputs: dict, context: dict) -> dict:
    """Instantiates a task for each template_gid in `template_gids`,
    via POST /task_templates/{gid}/instantiateTask. Returns the list
    of jobs (asynchronous -- they are not the final tasks, see the
    module docstring)."""
    name_override = inputs.get("name")
    jobs = []
    for template_gid in inputs["template_gids"]:
        body = {"data": {"name": name_override}} if name_override else {"data": {}}
        resp = requests.post(
            f"{BASE_URL}/task_templates/{template_gid}/instantiateTask",
            headers=_headers(), json=body, timeout=15,
        )
        resp.raise_for_status()
        jobs.append(resp.json())
    return {"jobs": jobs, "template_count": len(inputs["template_gids"])}
