"""
Repo root conftest.

Why this exists
----------------
The modules under modules/, railcall-submission/ and fika-sync/gui use
"flat" imports (`from client import ...`, `from actions import ...`,
`from handler import ...`) without package namespacing, because that's
how RailCall loads each module in production (module.json + flat code
in the same folder, without installing the repo as a package).

Several different modules therefore have files with the same name
(client.py, actions.py, handler.py, test_handler.py...). A single
`pytest` process run from the root imports all of them into the same
interpreter, and Python caches each module name the first time it's
seen: the second "client.py" that's imported wrongly reuses the first
one already cached, and those tests fail even though the code itself
is correct.

The supported solution is to run each test folder in its own Python
process (a clean sys.modules in each one):

    ./run_all_tests.sh

This is NOT a suite failure: it's a direct consequence of production
code needing to keep flat imports to be valid for RailCall. Changing
the imports to a full package would break the module format the
platform requires.

This file simply makes a bare `pytest` run from the root fail fast
with a useful message instead of a wall of hard-to-interpret
ImportError/"import file mismatch" output.
"""

import sys

import pytest

_HINT = (
    "\n"
    "This repo does not support a bare `pytest` run from the root: several "
    "modules use repeated file names (client.py, actions.py, "
    "test_handler.py...) on purpose, because RailCall requires flat "
    "imports inside each module.\n\n"
    "Use instead:\n\n"
    "    ./run_all_tests.sh\n\n"
    "which runs each test folder in its own process (clean sys.modules) "
    "and prints a total summary. See conftest.py for the detail.\n"
)


def pytest_configure(config):
    # If the invocation targets a specific subdirectory/file (as
    # run_all_tests.sh does, or `cd module && pytest`), don't interfere:
    # those cases ARE supported and work with a clean sys.modules.
    invocation_dir = str(config.invocation_params.dir)
    rootdir = str(config.rootpath)
    if invocation_dir != rootdir:
        return

    args = [a for a in config.invocation_params.args if not a.startswith("-")]
    if args:
        # The user already pointed at specific paths (e.g. pytest modules/gcal/tests).
        return

    sys.stderr.write(_HINT)
    raise pytest.UsageError(
        "A bare pytest run from the root is not supported in this repo. "
        "Use ./run_all_tests.sh (see conftest.py)."
    )
