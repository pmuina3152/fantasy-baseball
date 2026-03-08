"""
Vercel Python serverless entry point.

At build time, vercel.json runs:
    cp -r ../backend api/_backend
so this function's _backend/ directory is a snapshot of the repo's backend/.

sys.path is set to _backend/ so that `from main import app` resolves cleanly
against the copied backend source.  The cache files (backend/cache/*.parquet)
are also present at _backend/cache/ because they are part of the copy.

In production all /api/* requests are routed here by the rewrites rule in
vercel.json.  Because the frontend and this function share the same Vercel
origin, no CORS headers are required.

For local development this file is never invoked — next.config.js rewrites
/api/* to http://localhost:8000 so the FastAPI dev server handles those
requests directly.
"""

import os
import sys

# _backend/ is backend/ copied here during the Vercel build step.
# Path is anchored to __file__ so it resolves to the same place regardless
# of what directory Vercel uses as the Lambda working directory.
_BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_backend")
sys.path.insert(0, _BACKEND)

from main import app  # noqa: E402

from mangum import Mangum  # noqa: E402

# lifespan="off" — serverless environments do not support ASGI lifespan events.
handler = Mangum(app, lifespan="off")
