"""
Vercel Python serverless entry point.

Adds the backend/ directory to sys.path so the FastAPI app can be imported,
then wraps it with Mangum so Vercel can invoke it as a Lambda-style handler.

Vercel routes all /api/* requests here (see vercel.json).  Because the frontend
and this function are deployed under the same origin, no CORS is required for
production traffic.
"""

import os
import sys

# Make backend/ importable regardless of where Vercel places the working directory.
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, _BACKEND_DIR)

from main import app  # noqa: E402 — must come after sys.path modification

from mangum import Mangum  # noqa: E402

# lifespan="off" prevents Mangum from trying to manage ASGI lifespan events,
# which are not supported in the serverless context.
handler = Mangum(app, lifespan="off")
