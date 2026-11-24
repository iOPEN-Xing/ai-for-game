"""Loop Atelier ASGI entry point and background worker lifecycle."""

import asyncio
import os
from contextlib import asynccontextmanager, suppress

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from studio.api import (
    auth,
    blueprints,
    catalog,
    gameplay,
    health,
    library,
    middleware,
    operations_console,
    pages,
)
from studio.application.harness import worker
from studio.infra.store import init
from studio.settings import ROOT, WEB, deployed, load_environment, validate_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_environment()
    validate_runtime()
    init()
    task = asyncio.create_task(worker.serve(), name="studio-worker")
    app.state.worker = task
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    application = FastAPI(
        title="回路制作室",
        version="1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    middleware.install(application)
    application.mount("/static", StaticFiles(directory=WEB), name="static")
    application.mount(
        "/assets",
        StaticFiles(directory=ROOT / "docs/original/assets"),
        name="reference_assets",
    )
    for router in (
        health.router,
        pages.router,
        auth.router,
        catalog.router,
        blueprints.router,
        library.router,
        operations_console.router,
        gameplay.router,
    ):
        application.include_router(router)
    return application


app = create_app()

if __name__ == "__main__":
    load_environment()
    uvicorn.run(
        app,
        host="0.0.0.0" if deployed() else "127.0.0.1",
        port=int(os.getenv("PORT", "7860")),
    )
