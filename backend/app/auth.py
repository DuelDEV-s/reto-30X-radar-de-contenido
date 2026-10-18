"""Acceso mínimo por PIN fijo (APP_PIN). Vacío = sin autenticación.

El navegador guarda una cookie httpOnly tras el login; así también viajan con ella
las imágenes servidas por /api (avatares, media) sin tocar cada petición.
"""
import hashlib
import hmac
import os

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

COOKIE = "radar_pin"
PUBLIC_PATHS = {"/api/health", "/api/auth/status", "/api/auth/login", "/api/auth/logout"}
router = APIRouter(prefix="/api/auth", tags=["system"])


def _pin() -> str:
    return os.getenv("APP_PIN", "").strip()


def _token(pin: str) -> str:
    return hashlib.sha256(f"radar:{pin}".encode()).hexdigest()


def is_authenticated(request: Request) -> bool:
    pin = _pin()
    if not pin:
        return True
    supplied = request.cookies.get(COOKIE) or ""
    header = request.headers.get("X-App-Pin")
    if header:
        supplied = _token(header)
    return hmac.compare_digest(supplied, _token(pin))


async def require_pin(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api") or path in PUBLIC_PATHS or is_authenticated(request):
        return await call_next(request)
    return JSONResponse({"detail": "PIN requerido"}, status_code=401)


class Login(BaseModel):
    pin: str


@router.get("/status")
def status(request: Request):
    return {"required": bool(_pin()), "authenticated": is_authenticated(request)}


@router.post("/login")
def login(body: Login, response: Response):
    pin = _pin()
    if pin and not hmac.compare_digest(body.pin.strip(), pin):
        raise HTTPException(401, "PIN incorrecto")
    response.set_cookie(COOKIE, _token(pin), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"authenticated": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"authenticated": False}
