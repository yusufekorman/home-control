import json
import ipaddress
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
import httpx
from urllib.parse import urlparse
from pydantic import BaseModel

from database import get_db
from models import (
    Device, DeviceAction, DeviceLog, ApiKey,
    DeviceCreate, DeviceUpdate, DeviceRead,
    DeviceActionCreate, DeviceActionRead,
    DeviceLogRead, ApiKeyRead, ApiKeyCreate, ApiKeyCreated,
)
from auth import validate_api_key, generate_api_key

router = APIRouter(tags=["REST API"])
ping_router = APIRouter(tags=["Device Ping"])


class DevicePingPayload(BaseModel):
    device: str
    ip: str


def _build_base_url_from_ip(current_base_url: str, ip: str) -> str:
    parsed = urlparse(current_base_url or "")
    scheme = parsed.scheme or "http"
    host = ip
    if parsed.port:
        host = f"{ip}:{parsed.port}"
    return f"{scheme}://{host}"


# ─── API Key dependency ────────────────────────────────────────────────────────

def get_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ApiKey:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header missing",
        )
    key = validate_api_key(db, x_api_key)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )
    return key


@ping_router.post("/ping", summary="Device ping with bearer security code")
def device_ping(
    payload: DevicePingPayload,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    db: Session = Depends(get_db),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization Bearer token missing",
        )

    token = authorization[len("Bearer "):].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization token is empty",
        )

    try:
        normalized_ip = str(ipaddress.ip_address(payload.ip.strip()))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid IP address",
        )

    device = None
    if payload.device.isdigit():
        device = db.query(Device).filter(Device.id == int(payload.device)).first()
    if not device:
        device = db.query(Device).filter(Device.name == payload.device).first()

    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    previous_token = device.auth_header_value
    device.auth_header_value = token
    device.ip_address = normalized_ip
    device.base_url = _build_base_url_from_ip(device.base_url, normalized_ip)
    device.is_active = True

    db.add(
        DeviceLog(
            device_id=device.id,
            action_name="device_ping",
            status_code=200,
            response_body=(
                f"IP updated to {normalized_ip}; token_rotated={previous_token != token}"
            ),
            triggered_by="ping",
        )
    )
    db.commit()
    db.refresh(device)

    return {
        "success": True,
        "device_id": device.id,
        "device_name": device.name,
        "ip_address": device.ip_address,
        "base_url": device.base_url,
        "updated": True,
    }


# ─── API Keys ─────────────────────────────────────────────────────────────────

@router.get("/apikeys", response_model=List[ApiKeyRead], summary="List API keys")
def list_api_keys(db: Session = Depends(get_db), _: ApiKey = Depends(get_api_key)):
    return db.query(ApiKey).all()


@router.post("/apikeys", response_model=ApiKeyCreated, status_code=201, summary="Create API key")
def create_api_key(
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    key_obj, raw = generate_api_key(db, payload.name)
    result = ApiKeyCreated.model_validate(key_obj)
    result.raw_key = raw
    return result


@router.delete("/apikeys/{key_id}", status_code=204, summary="Delete API key")
def delete_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not key:
        raise HTTPException(404, "API key not found")
    db.delete(key)
    db.commit()


# ─── Devices ──────────────────────────────────────────────────────────────────

@router.get("/devices", response_model=List[DeviceRead], summary="List all devices")
def list_devices(db: Session = Depends(get_db), _: ApiKey = Depends(get_api_key)):
    return db.query(Device).order_by(Device.name).all()


@router.post("/devices", response_model=DeviceRead, status_code=201, summary="Create device")
def create_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    device = Device(**payload.model_dump())
    device.base_url = device.base_url.rstrip("/")
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.get("/devices/{device_id}", response_model=DeviceRead, summary="Get device")
def get_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    return device


@router.put("/devices/{device_id}", response_model=DeviceRead, summary="Update device")
def update_device(
    device_id: int,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    for k, v in payload.model_dump().items():
        setattr(device, k, v)
    device.base_url = device.base_url.rstrip("/")
    db.commit()
    db.refresh(device)
    return device


@router.delete("/devices/{device_id}", status_code=204, summary="Delete device")
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    db.delete(device)
    db.commit()


# ─── Device Actions ────────────────────────────────────────────────────────────

@router.get("/devices/{device_id}/actions", response_model=List[DeviceActionRead])
def list_actions(
    device_id: int,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    return device.actions


@router.post("/devices/{device_id}/actions", response_model=DeviceActionRead, status_code=201)
def create_action(
    device_id: int,
    payload: DeviceActionCreate,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    action = DeviceAction(device_id=device_id, **payload.model_dump())
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@router.delete("/devices/{device_id}/actions/{action_id}", status_code=204)
def delete_action(
    device_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    action = db.query(DeviceAction).filter(
        DeviceAction.id == action_id, DeviceAction.device_id == device_id
    ).first()
    if not action:
        raise HTTPException(404, "Action not found")
    db.delete(action)
    db.commit()


# ─── Trigger action ───────────────────────────────────────────────────────────

@router.post("/devices/{device_id}/actions/{action_id}/trigger", summary="Trigger device action")
async def trigger_action(
    device_id: int,
    action_id: int,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_api_key),
):
    device = db.query(Device).filter(Device.id == device_id).first()
    if not device:
        raise HTTPException(404, "Device not found")
    action = db.query(DeviceAction).filter(
        DeviceAction.id == action_id, DeviceAction.device_id == device_id
    ).first()
    if not action:
        raise HTTPException(404, "Action not found")
    if not device.is_active:
        raise HTTPException(400, "Device is inactive")

    url = device.base_url + action.path
    headers = {}
    if device.auth_header_name and device.auth_header_value:
        headers[device.auth_header_name] = device.auth_header_value
    if action.extra_headers:
        try:
            headers.update(json.loads(action.extra_headers))
        except Exception:
            pass

    log = DeviceLog(device_id=device_id, action_name=action.name, triggered_by="api")
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
        db.add(log)
        db.commit()
        return {"success": True, "status_code": resp.status_code, "response": resp.text[:2000]}
    except Exception as e:
        log.error = str(e)
        db.add(log)
        db.commit()
        raise HTTPException(502, f"Device request failed: {e}")


# ─── Logs ─────────────────────────────────────────────────────────────────────

@router.get("/devices/{device_id}/logs", response_model=List[DeviceLogRead])
def get_device_logs(
    device_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    return (
        db.query(DeviceLog)
        .filter(DeviceLog.device_id == device_id)
        .order_by(DeviceLog.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/logs", response_model=List[DeviceLogRead], summary="Get all logs")
def get_all_logs(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: ApiKey = Depends(get_api_key),
):
    return (
        db.query(DeviceLog)
        .order_by(DeviceLog.created_at.desc())
        .limit(limit)
        .all()
    )
