import os
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.templating import Jinja2Templates
from starlette.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    AuthenticationBackend, AuthCredentials, SimpleUser, AuthenticationError
)
import base64
import secrets
import subprocess
import time

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    print(f"Generated admin password: {ADMIN_PASSWORD}")

# Глобальные переменные для хранения состояния Gateway
gateway_process = None
gateway_start_time = None

class BasicAuthBackend(AuthenticationBackend):
    async def authenticate(self, conn):
        if "Authorization" not in conn.headers:
            return None
        auth = conn.headers["Authorization"]
        try:
            scheme, credentials = auth.split()
            if scheme.lower() != "basic":
                return None
            decoded = base64.b64decode(credentials).decode("ascii")
            username, _, password = decoded.partition(":")
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                return AuthCredentials(["authenticated"]), SimpleUser(username)
        except:
            pass
        raise AuthenticationError("Invalid credentials")

async def homepage(request):
    return templates.TemplateResponse(request, "index.html")

async def api_status(request):
    global gateway_process, gateway_start_time
    state = "stopped"
    if gateway_process and gateway_process.poll() is None:
        state = "running"
    return JSONResponse({
        "gateway": {
            "state": state,
            "uptime": int(time.time() - gateway_start_time) if gateway_start_time and state == "running" else None,
            "restarts": 0
        },
        "providers": {
            "openrouter": {"configured": bool(os.environ.get("OPENROUTER_API_KEY"))}
        },
        "channels": {
            "telegram": {"enabled": bool(os.environ.get("TELEGRAM_TOKEN"))}
        }
    })

async def api_gateway_start(request):
    global gateway_process, gateway_start_time
    try:
        if gateway_process and gateway_process.poll() is None:
            return JSONResponse({"ok": True, "message": "already running"})
        
        gateway_process = subprocess.Popen(
            ["nanobot", "gateway"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        gateway_start_time = time.time()
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

async def api_gateway_stop(request):
    global gateway_process, gateway_start_time
    try:
        if gateway_process and gateway_process.poll() is None:
            gateway_process.terminate()
            gateway_process.wait(timeout=10)
        gateway_process = None
        gateway_start_time = None
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

async def api_gateway_restart(request):
    await api_gateway_stop(request)
    await api_gateway_start(request)
    return JSONResponse({"ok": True})

routes = [
    Route("/", homepage),
    Route("/api/status", api_status),
    Route("/api/gateway/start", api_gateway_start, methods=["POST"]),
    Route("/api/gateway/stop", api_gateway_stop, methods=["POST"]),
    Route("/api/gateway/restart", api_gateway_restart, methods=["POST"]),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(AuthenticationMiddleware, backend=BasicAuthBackend())],
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
