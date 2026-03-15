import json
import os
import inspect
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.structs import (
    AuthenticationCredential,
    AuthenticatorSelectionCriteria,
    RegistrationCredential,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from database import get_db
from models import ApiKey, Device, DeviceAction, DeviceLog, User, UserPasskey
from auth import authenticate_user, generate_api_key, get_password_hash

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="templates")


# ─── Passkey helpers ───────────────────────────────────────────────────────────

def _rp_id_from_request(request: Request) -> str:
    return os.environ.get("WEBAUTHN_RP_ID") or request.url.hostname or "localhost"


def _origin_from_request(request: Request) -> str:
    return os.environ.get("WEBAUTHN_ORIGIN") or f"{request.url.scheme}://{request.url.netloc}"


def _store_challenge(request: Request, key: str, challenge: bytes) -> None:
    request.session[key] = bytes_to_base64url(challenge)


def _load_challenge(request: Request, key: str) -> Optional[bytes]:
    encoded = request.session.pop(key, None)
    if not encoded:
        return None
    return base64url_to_bytes(encoded)


def _parse_registration_credential(payload: dict):
    if hasattr(RegistrationCredential, "model_validate"):
        return RegistrationCredential.model_validate(payload)
    if hasattr(RegistrationCredential, "parse_obj"):
        return RegistrationCredential.parse_obj(payload)
    if hasattr(RegistrationCredential, "parse_raw"):
        return RegistrationCredential.parse_raw(json.dumps(payload))
    if hasattr(RegistrationCredential, "from_dict"):
        return RegistrationCredential.from_dict(payload)
    return RegistrationCredential(**payload)


def _parse_authentication_credential(payload: dict):
    if hasattr(AuthenticationCredential, "model_validate"):
        return AuthenticationCredential.model_validate(payload)
    if hasattr(AuthenticationCredential, "parse_obj"):
        return AuthenticationCredential.parse_obj(payload)
    if hasattr(AuthenticationCredential, "parse_raw"):
        return AuthenticationCredential.parse_raw(json.dumps(payload))
    if hasattr(AuthenticationCredential, "from_dict"):
        return AuthenticationCredential.from_dict(payload)
    return AuthenticationCredential(**payload)


def _call_with_supported_kwargs(func, **kwargs):
    sig = inspect.signature(func)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return func(**allowed)


# ─── Session helpers ───────────────────────────────────────────────────────────

def get_current_user(request: Request, db: Session) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


# ─── Auth ──────────────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    if request.session.get("user_id"):
        return RedirectResponse("/", status_code=302)
    has_passkeys = db.query(UserPasskey.id).first() is not None
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None, "has_passkeys": has_passkeys},
    )


@router.post("/login", response_class=HTMLResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate_user(db, username, password)
    if not user:
        has_passkeys = db.query(UserPasskey.id).first() is not None
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Geçersiz kullanıcı adı veya şifre.",
                "has_passkeys": has_passkeys,
            },
        )
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    return RedirectResponse("/", status_code=302)


@router.post("/auth/passkey/register/begin")
async def passkey_register_begin(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    rp_id = _rp_id_from_request(request)
    options = _call_with_supported_kwargs(
        generate_registration_options,
        rp_id=rp_id,
        rp_name="Home Control",
        user_id=str(user.id).encode("utf-8"),
        user_name=user.username,
        user_display_name=user.username,
        user_verification=UserVerificationRequirement.REQUIRED,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _store_challenge(request, "passkey_register_challenge", options.challenge)
    return JSONResponse(json.loads(options_to_json(options)))


@router.post("/auth/passkey/register/finish")
async def passkey_register_finish(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    challenge = _load_challenge(request, "passkey_register_challenge")
    if not challenge:
        return JSONResponse({"error": "Challenge expired"}, status_code=400)

    payload = await request.json()
    try:
        credential = _parse_registration_credential(payload)
        verification = _call_with_supported_kwargs(
            verify_registration_response,
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_rp_id_from_request(request),
            expected_origin=_origin_from_request(request),
            require_user_verification=True,
        )
    except Exception as exc:
        return JSONResponse({"error": f"Registration failed: {exc}"}, status_code=400)

    existing = db.query(UserPasskey).filter(
        UserPasskey.credential_id == verification.credential_id
    ).first()
    if existing:
        return JSONResponse({"error": "Passkey already registered"}, status_code=409)

    response_data = payload.get("response", {})
    transports = response_data.get("transports")
    passkey = UserPasskey(
        user_id=user.id,
        name=f"{user.username} passkey",
        credential_id=verification.credential_id,
        credential_public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        transports=",".join(transports) if transports else None,
    )
    db.add(passkey)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/auth/passkey/login/begin")
async def passkey_login_begin(request: Request):
    rp_id = _rp_id_from_request(request)
    options = _call_with_supported_kwargs(
        generate_authentication_options,
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _store_challenge(request, "passkey_login_challenge", options.challenge)
    return JSONResponse(json.loads(options_to_json(options)))


@router.post("/auth/passkey/login/finish")
async def passkey_login_finish(request: Request, db: Session = Depends(get_db)):
    challenge = _load_challenge(request, "passkey_login_challenge")
    if not challenge:
        return JSONResponse({"error": "Challenge expired"}, status_code=400)

    payload = await request.json()
    credential_id = base64url_to_bytes(payload.get("rawId") or payload.get("id", ""))
    passkey = db.query(UserPasskey).filter(UserPasskey.credential_id == credential_id).first()
    if not passkey:
        return JSONResponse({"error": "Passkey not found"}, status_code=401)

    try:
        credential = _parse_authentication_credential(payload)
        verification = _call_with_supported_kwargs(
            verify_authentication_response,
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=_rp_id_from_request(request),
            expected_origin=_origin_from_request(request),
            credential_public_key=passkey.credential_public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        return JSONResponse({"error": f"Authentication failed: {exc}"}, status_code=401)

    user = db.query(User).filter(User.id == passkey.user_id).first()
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=401)

    passkey.sign_count = verification.new_sign_count
    passkey.last_used_at = datetime.utcnow()
    db.commit()

    request.session["user_id"] = user.id
    request.session["username"] = user.username
    return JSONResponse({"ok": True, "redirect": "/"})


@router.post("/auth/passkeys/{passkey_id}/delete")
async def delete_passkey(request: Request, passkey_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)

    passkey = db.query(UserPasskey).filter(
        UserPasskey.id == passkey_id,
        UserPasskey.user_id == user.id,
    ).first()
    if passkey:
        db.delete(passkey)
        db.commit()
    return RedirectResponse("/", status_code=302)


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


# ─── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    devices = db.query(Device).order_by(Device.name).all()
    user_passkeys = (
        db.query(UserPasskey)
        .filter(UserPasskey.user_id == user.id)
        .order_by(UserPasskey.created_at.desc())
        .all()
    )
    recent_logs = (
        db.query(DeviceLog)
        .order_by(DeviceLog.created_at.desc())
        .limit(20)
        .all()
    )
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "devices": devices,
            "logs": recent_logs,
            "passkeys": user_passkeys,
        },
    )


# ─── Devices ───────────────────────────────────────────────────────────────────

@router.get("/devices", response_class=HTMLResponse)
async def devices_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    devices = db.query(Device).order_by(Device.name).all()
    return templates.TemplateResponse(
        "devices.html", {"request": request, "user": user, "devices": devices}
    )


@router.post("/devices/add")
async def add_device(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    ip_address: str = Form(...),
    base_url: str = Form(...),
    auth_header_name: str = Form(""),
    auth_header_value: str = Form(""),
    icon: str = Form("device"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    device = Device(
        name=name,
        description=description,
        ip_address=ip_address,
        base_url=base_url.rstrip("/"),
        auth_header_name=auth_header_name or None,
        auth_header_value=auth_header_value or None,
        icon=icon,
    )
    db.add(device)
    db.commit()
    return RedirectResponse("/devices", status_code=302)


@router.post("/devices/{device_id}/delete")
async def delete_device(request: Request, device_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    device = db.query(Device).filter(Device.id == device_id).first()
    if device:
        db.delete(device)
        db.commit()
    return RedirectResponse("/devices", status_code=302)


@router.post("/devices/{device_id}/toggle")
async def toggle_device(request: Request, device_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    device = db.query(Device).filter(Device.id == device_id).first()
    if device:
        device.is_active = not device.is_active
        db.commit()
    return RedirectResponse("/devices", status_code=302)


@router.get("/devices/{device_id}", response_class=HTMLResponse)
async def device_detail(request: Request, device_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        return RedirectResponse("/devices", status_code=302)
    logs = (
        db.query(DeviceLog)
        .filter(DeviceLog.device_id == device_id)
        .order_by(DeviceLog.created_at.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse(
        "device_detail.html",
        {"request": request, "user": user, "device": device, "logs": logs},
    )


@router.post("/devices/{device_id}/edit")
async def edit_device(
    request: Request,
    device_id: int,
    name: str = Form(...),
    description: str = Form(""),
    ip_address: str = Form(...),
    base_url: str = Form(...),
    auth_header_name: str = Form(""),
    auth_header_value: str = Form(""),
    icon: str = Form("device"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    device = db.query(Device).filter(Device.id == device_id).first()
    if device:
        device.name = name
        device.description = description
        device.ip_address = ip_address
        device.base_url = base_url.rstrip("/")
        device.auth_header_name = auth_header_name or None
        device.auth_header_value = auth_header_value or None
        device.icon = icon
        db.commit()
    return RedirectResponse(f"/devices/{device_id}", status_code=302)


# ─── Device Actions ────────────────────────────────────────────────────────────

@router.post("/devices/{device_id}/actions/add")
async def add_action(
    request: Request,
    device_id: int,
    name: str = Form(...),
    description: str = Form(""),
    path: str = Form(...),
    method: str = Form("GET"),
    body: str = Form(""),
    extra_headers: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    action = DeviceAction(
        device_id=device_id,
        name=name,
        description=description,
        path=path,
        method=method,
        body=body or None,
        extra_headers=extra_headers or None,
    )
    db.add(action)
    db.commit()
    return RedirectResponse(f"/devices/{device_id}", status_code=302)


@router.post("/devices/{device_id}/actions/{action_id}/delete")
async def delete_action(
    request: Request, device_id: int, action_id: int, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    action = db.query(DeviceAction).filter(DeviceAction.id == action_id).first()
    if action:
        db.delete(action)
        db.commit()
    return RedirectResponse(f"/devices/{device_id}", status_code=302)


# ─── Trigger from web ─────────────────────────────────────────────────────────

@router.post("/devices/{device_id}/actions/{action_id}/trigger")
async def trigger_action_web(
    request: Request, device_id: int, action_id: int, db: Session = Depends(get_db)
):
    import httpx, json
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    device = db.query(Device).filter(Device.id == device_id).first()
    action = db.query(DeviceAction).filter(DeviceAction.id == action_id).first()
    if not device or not action:
        return RedirectResponse(f"/devices/{device_id}", status_code=302)

    url = device.base_url + action.path
    headers = {}
    if device.auth_header_name and device.auth_header_value:
        headers[device.auth_header_name] = device.auth_header_value
    if action.extra_headers:
        try:
            extra = json.loads(action.extra_headers)
            headers.update(extra)
        except Exception:
            pass

    log = DeviceLog(device_id=device_id, action_name=action.name, triggered_by="web")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.request(
                method=action.method,
                url=url,
                headers=headers,
                content=action.body.encode() if action.body else None,
            )
        log.status_code = resp.status_code
        log.response_body = resp.text[:2000]
    except Exception as e:
        log.error = str(e)
    db.add(log)
    db.commit()
    return RedirectResponse(f"/devices/{device_id}", status_code=302)


# ─── API Keys ─────────────────────────────────────────────────────────────────

@router.get("/apikeys", response_class=HTMLResponse)
async def apikeys_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    new_key = request.session.pop("new_raw_key", None)
    return templates.TemplateResponse(
        "apikeys.html",
        {"request": request, "user": user, "keys": keys, "new_key": new_key},
    )


@router.post("/apikeys/create")
async def create_apikey(
    request: Request, name: str = Form(...), db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    _, raw_key = generate_api_key(db, name)
    request.session["new_raw_key"] = raw_key
    return RedirectResponse("/apikeys", status_code=302)


@router.post("/apikeys/{key_id}/delete")
async def delete_apikey(request: Request, key_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if key:
        db.delete(key)
        db.commit()
    return RedirectResponse("/apikeys", status_code=302)


@router.post("/apikeys/{key_id}/toggle")
async def toggle_apikey(request: Request, key_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=302)
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if key:
        key.is_active = not key.is_active
        db.commit()
    return RedirectResponse("/apikeys", status_code=302)


# ─── Users (admin only) ────────────────────────────────────────────────────────

@router.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/", status_code=302)
    users = db.query(User).all()
    return templates.TemplateResponse(
        "users.html", {"request": request, "user": user, "users": users}
    )


@router.post("/users/add")
async def add_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    is_admin: bool = Form(False),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/", status_code=302)
    new_user = User(
        username=username,
        password_hash=get_password_hash(password),
        is_admin=is_admin,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/users", status_code=302)


@router.post("/users/{user_id}/delete")
async def delete_user(request: Request, user_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse("/", status_code=302)
    if user.id == user_id:
        return RedirectResponse("/users", status_code=302)  # can't self-delete
    u = db.query(User).filter(User.id == user_id).first()
    if u:
        db.delete(u)
        db.commit()
    return RedirectResponse("/users", status_code=302)
