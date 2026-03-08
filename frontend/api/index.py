"""
Vercel Python serverless entry point.

At build time, vercel.json runs:
    cp -r ../backend api/_backend
so this function's _backend/ directory is a snapshot of the repo's backend/.

sys.path is set to _backend/ so that `from main import app` resolves cleanly
against the copied backend source.  The cache files (backend/cache/*.parquet)
are also present at _backend/cache/ because they are part of the copy.

Vercel's Python runtime speaks ASGI natively — it inspects the exported `app`
object directly.  Mangum (an AWS Lambda adapter) must NOT be used here because
Vercel's vc_init.py calls issubclass() on the handler and Mangum's wrapper
function fails that check with "issubclass() arg 1 must be a class".

For local development this file is never invoked — next.config.js rewrites
/api/* to http://localhost:8000 so the FastAPI dev server handles requests.
"""

import os
import sys

# _backend/ is backend/ copied here during the Vercel build step.
# Path is anchored to __file__ so it resolves correctly regardless of
# what working directory Vercel uses for the Lambda.
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_backend")
sys.path.insert(0, _BACKEND)

from main import app  # noqa: E402 — must come after sys.path modification

# `app` is a FastAPI instance (subclass of Starlette, which is an ASGI app).
# Vercel's Python runtime detects it automatically — no adapter needed.
