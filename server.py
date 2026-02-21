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
import json
from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Читаем переменные окружения
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    print(f"Generated admin password: {ADMIN_PASSWORD}")

# Принудительно применяем переменные Telegram к конфигу при старте
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_ALLOW_FROM = os.environ.get("TELEGRAM_ALLOW_FROM")

if TELEGRAM_TOKEN and TELEGRAM_ALLOW_FROM:
    try:
        config = load_config()
        # Обновляем настройки Telegram
        if "channels" not in config.__dict__:
            config.channels = {}
        if "telegram" not in config.channels:
            config.channels.telegram = {}
        
        config.channels.telegram.enabled = True
        config.channels.telegram.token = TELEGRAM_TOKEN
        # Парсим allow_from (может быть как число, так и строка)
        try:
            allow_list = json.loads(TELEGRAM_ALLOW_FROM) if TELEGRAM_ALLOW_FROM.startswith('[') else [int(TELEGRAM_ALLOW_FROM)]
        except:
            allow_list = [str(TELEGRAM_ALLOW_FROM)]
        config.channels.telegram.allow_from = allow_list
        
        save_config(config)
        print(f"✓ Telegram configured from environment variables")
    except Exception as e:
        print(f"! Failed to configure Telegram from env: {e}")

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

async def api_config_get(request):
    config = load_config()
    return JSONResponse(config.model_dump())

async def api_config_put(request):
    try:
        data = await request.json()
        config = Config.model_validate(data)
        save_config(config)
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

async def api_status(request):
    config = load_config()
    providers = {}
    for name, prov in config.providers.items():
        providers[name] = {"configured": bool(prov and prov.get("api_key"))}
    channels = {}
    for name, chan in config.channels.items():
        channels[name] = {"enabled": getattr(chan, "enabled", False)}
    return JSONResponse({
        "gateway": {"state": "unknown"},
        "providers": providers,
        "channels": channels
    })

routes = [
    Route("/", homepage),
    Route("/api/config", api_config_get, methods=["GET"]),
    Route("/api/config", api_config_put, methods=["PUT"]),
    Route("/api/status", api_status),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(AuthenticationMiddleware, backend=BasicAuthBackend())],
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
