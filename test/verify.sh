#!/usr/bin/env bash
# The test suite lives in verify.py (it runs on Windows too); this just uses the venv.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$here/../.venv/bin/python" "$here/verify.py" "$@"
