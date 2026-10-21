"""Application factory. Run with:  uvicorn app.main:app --host 127.0.0.1 --port 8000"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import Settings
from app.core.errors import install_handlers
from app.db.init import init_database
from app.services.scoring import HeuristicScorer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

CSP = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
FALLBACK = """<!doctype html><meta charset="utf-8"><title>Fraud Desk</title>
<body style="font:16px system-ui;max-width:40rem;margin:4rem auto;padding:0 1rem">
<h1>Fraud Desk API</h1><p>The API is running, but the frontend has not been built.</p>
<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, or start the dev server with <code>npm run dev</code>.
API docs: <a href="/docs">/docs</a>.</p></body>"""


def create_app(settings: Settings | None = None, scorer=None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Fraud Desk API", version="2.0.0", description="Synthetic-data credit card fraud review demonstrator (not a payment system).")
    app.state.settings = settings
    app.state.scorer = scorer or HeuristicScorer()
    app.state.secret = init_database(settings)
    install_handlers(app)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["Authorization", "Content-Type"], allow_credentials=False)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            resp.headers.setdefault("Content-Security-Policy", CSP)
        if request.url.path.startswith("/api"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    app.include_router(router)
    dist: Path = settings.frontend_dist
    if (dist / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                return HTMLResponse("Not found", status_code=404)
            candidate = (dist / path).resolve()
            if path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        def fallback():
            return HTMLResponse(FALLBACK)
    return app


app = create_app()
