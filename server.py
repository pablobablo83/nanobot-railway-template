import os
import asyncio
import base64
import secrets
import requests
import time
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    AuthenticationBackend, AuthCredentials, SimpleUser, AuthenticationError
)
import uvicorn

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    print(f"Generated admin password: {ADMIN_PASSWORD}")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_USERS = [uid.strip() for uid in os.environ.get("TELEGRAM_ALLOW_FROM", "").split(",") if uid.strip()]

# Класс для управления Gateway с автоматическим переподключением
class RobustGateway:
    def __init__(self):
        self.process = None
        self.state = "stopped"
        self.start_time = None
        self._retry_count = 0
        self._max_retries = 10  # Будет пытаться 10 раз
        self._keep_running = False
        
    async def start(self):
        if self.state == "running":
            return
        
        self.state = "starting"
        self._keep_running = True
        self._retry_count = 0
        self.start_time = time.time()
        
        # Запускаем в фоне с автопереподключением
        asyncio.create_task(self._run_with_retry())
    
    async def _run_with_retry(self):
        while self._keep_running:
            try:
                # Пытаемся запустить gateway
                self.process = await asyncio.create_subprocess_exec(
                    "nanobot", "gateway",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                self.state = "running"
                self._retry_count = 0
                
                # Ждем завершения процесса
                await self.process.wait()
                
                # Если процесс завершился, а мы должны работать - перезапускаем
                if self._keep_running:
                    self.state = "restarting"
                    # Экспоненциальная задержка: 2^n секунд (но не больше 30 сек)
                    delay = min(2 ** self._retry_count, 30)
                    self._retry_count += 1
                    print(f"Gateway crashed, restarting in {delay}s (attempt {self._retry_count})")
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                print(f"Gateway error: {e}")
                if self._keep_running:
                    await asyncio.sleep(5)
        
        self.state = "stopped"
        self.process = None
    
    async def stop(self):
        self._keep_running = False
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except:
                self.process.kill()
        self.state = "stopped"
        self.start_time = None
    
    def get_status(self):
        return {
            "state": self.state,
            "uptime": int(time.time() - self.start_time) if self.start_time and self.state == "running" else None,
            "restarts": self._retry_count
        }

gateway = RobustGateway()

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

async def api_status(request):
    return JSONResponse({
        "gateway": gateway.get_status(),
        "providers": {"openrouter": {"configured": bool(os.environ.get("OPENROUTER_API_KEY"))}},
        "channels": {"telegram": {"enabled": bool(TELEGRAM_TOKEN)}}
    })

async def api_gateway_start(request):
    await gateway.start()
    return JSONResponse({"ok": True})

async def api_gateway_stop(request):
    await gateway.stop()
    return JSONResponse({"ok": True})

async def api_gateway_restart(request):
    await gateway.stop()
    await gateway.start()
    return JSONResponse({"ok": True})

routes = [
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
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
