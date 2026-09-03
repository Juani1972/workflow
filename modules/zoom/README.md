# your-handle/zoom

Looks up the real duration of a finished meeting, used by
`fika-sync/get_zoom_actual_duration` (node 1.4: if the meeting ran
long, recalculate the affected focus block).

## Status

✅ Endpoint verified (`GET /past_meetings/{meetingUUID}`), including a
real, documented Zoom API gotcha: the UUID sometimes needs double
URL-encoding (see the comment in `handler.py`).

⚠️ Not tested against a real account. `module_dependency` in
workflow.csv marks it `optional: true` in `engine_spec.json` -- if
Zoom isn't connected, that node simply doesn't run, the rest of the
workflow keeps working.

## Auth

OAuth2, provider `zoom`. In development/test it's read from the
`ZOOM_ACCESS_TOKEN` environment variable.
