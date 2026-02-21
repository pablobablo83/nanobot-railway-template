import os
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import (
    AuthenticationBackend, AuthCredentials, SimpleUser, AuthenticationError
)
import base64
import secrets
import requests
import uvicorn

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    ADMIN_PASSWORD = secrets.token_urlsafe(16)
    print(f"Generated admin password: {ADMIN_PASSWORD}")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ALLOWED_USERS = [uid.strip() for uid in os.environ.get("TELEGRAM_ALLOW_FROM", "").split(",") if uid.strip()]

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

async def telegram_webhook(request):
    try:
        # Получаем данные от Telegram
        data = await request.json()
        print(f"📩 Получено сообщение: {data}")
        
        # Извлекаем информацию
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        
        # Проверяем, разрешён ли пользователь
        if str(chat_id) in ALLOWED_USERS:
            # Отправляем ответ
            response_text = f"Вы написали: {text}\n\n✅ Бот работает в облаке через вебхуки!"
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": response_text}
            )
            print(f"✅ Ответ отправлен пользователю {chat_id}")
        else:
            print(f"⛔ Запрещённый пользователь: {chat_id}")
        
        return JSONResponse({"ok": True})
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

async def api_status(request):
    return JSONResponse({
        "status": "ok",
        "mode": "webhook",
        "telegram_token_configured": bool(TELEGRAM_TOKEN),
        "allowed_users": ALLOWED_USERS
    })

# Маршруты
routes = [
    Route(f"/webhook/{TELEGRAM_TOKEN}", telegram_webhook, methods=["POST"]),
    Route("/api/status", api_status),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(AuthenticationMiddleware, backend=BasicAuthBackend())],
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
