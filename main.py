import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from database import engine, Base, SessionLocal
from models import User
from auth import get_password_hash
import web as web_router
import api as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            initial_password = secrets.token_urlsafe(12)
            db.add(User(
                username="admin",
                password_hash=get_password_hash(initial_password),
                is_admin=True,
            ))
            db.commit()
            print(f"\n✅  Initial admin created → username: admin  |  password: {initial_password}\n")
    finally:
        db.close()

    yield


app = FastAPI(
    title="Home Control Server",
    description="Smart home device management with REST API and MCP support",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=86400,
    https_only=False,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/sw.js", include_in_schema=False)
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/manifest.webmanifest", include_in_schema=False)
async def web_manifest():
    return FileResponse("static/manifest.webmanifest", media_type="application/manifest+json")

app.include_router(web_router.router)
app.include_router(api_router.router, prefix="/api/v1")
app.include_router(api_router.ping_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", 8000)),
        reload=os.environ.get("RELOAD", "true").lower() == "true",
    )
