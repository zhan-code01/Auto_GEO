# -*- coding: utf-8 -*-
"""
本地客户端设备管理 API（文档 §6.1.1 / §6.2.2）

设备是「本地发布客户端」的运行实例。客户端首次启动生成 device_id 并向服务器注册，
之后周期性心跳；服务器据此判断哪些设备在线、支持哪些平台，发布任务可派发到指定设备。

设备本身不持有第三方平台登录态——登录态保存在客户端本机（Account.session_location=local_only）。

多账号支持：同一台电脑（同一 device_id）可以被多个账号分别登记，
每个账号拥有自己的设备记录（唯一键 user_id + device_id），换账号登录互不冲突。

按用户隔离：普通用户只能管理自己的设备，admin 可见全部。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.user import get_current_user_from_token
from backend.database import get_db
from backend.database.models import ClientDevice, User
from backend.middleware.user_isolation import scoped_query
from backend.schemas import ApiResponse


router = APIRouter(prefix="/api/client/devices", tags=["本地客户端设备"])


# 心跳判活窗口：最近一次心跳在此时长内视为 online。
# 客户端默认每 30s 心跳，这里给 3 倍容差，避免偶发网络抖动误判离线。
HEARTBEAT_ONLINE_SECONDS = 90


# ==================== 请求/响应模型 ====================


class DeviceRegisterRequest(BaseModel):
    """设备注册请求"""

    device_id: str = Field(..., min_length=1, max_length=64, description="客户端生成的设备ID（全局唯一）")
    device_name: Optional[str] = Field(None, max_length=100, description="设备名称")
    os: Optional[str] = Field(None, max_length=20, description="操作系统：windows/mac/linux")
    app_version: Optional[str] = Field(None, max_length=30, description="客户端版本")
    capabilities: Optional[Dict[str, Any]] = Field(None, description="支持的平台和能力 JSON")


class DeviceHeartbeatRequest(BaseModel):
    """设备心跳请求"""

    device_id: str = Field(..., min_length=1, max_length=64)
    capabilities: Optional[Dict[str, Any]] = Field(None, description="能力更新（可选）")


class DeviceUpdateRequest(BaseModel):
    """设备信息更新请求"""

    device_name: Optional[str] = Field(None, max_length=100)
    capabilities: Optional[Dict[str, Any]] = None


# ==================== 工具函数（供 client_publish 等模块复用） ====================


def is_device_online(device: ClientDevice, *, now: Optional[datetime] = None) -> bool:
    """设备是否在线：状态为 online 且最近心跳在判活窗口内。

    被禁用（disabled）的设备永不算在线。
    """
    if device.status != "online":
        return False
    if not device.last_seen_at:
        return False
    moment = now or datetime.now()
    return (moment - device.last_seen_at) <= timedelta(seconds=HEARTBEAT_ONLINE_SECONDS)


def serialize_device(device: ClientDevice, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """序列化设备记录（含派生的 online 字段）。"""
    moment = now or datetime.now()
    return {
        "id": device.id,
        "user_id": device.user_id,
        "device_id": device.device_id,
        "device_name": device.device_name,
        "os": device.os,
        "app_version": device.app_version,
        "capabilities": device.capabilities,
        "status": device.status,
        "online": is_device_online(device, now=moment),
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
        "updated_at": device.updated_at.isoformat() if device.updated_at else None,
    }


def get_owned_device(db: Session, device_id: str, current_user: User) -> ClientDevice:
    """加载当前用户自己的设备记录（按 user_id + device_id 定位）。

    - 404: 该用户未登记过此设备（客户端应先 register 再使用）
    """
    device = (
        db.query(ClientDevice)
        .filter(
            ClientDevice.device_id == device_id,
            ClientDevice.user_id == current_user.id,
        )
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="设备未注册")
    return device


def _load_device_for_manage(db: Session, device_id: str, current_user: User) -> ClientDevice:
    """加载设备用于管理操作（改名/禁用）。

    普通用户只能操作自己的设备；admin 可按 device_id 直接定位（取第一条匹配）。
    """
    q = db.query(ClientDevice).filter(ClientDevice.device_id == device_id)
    if getattr(current_user, "role", None) != "admin":
        q = q.filter(ClientDevice.user_id == current_user.id)
    device = q.first()
    if not device:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


# ==================== 接口 ====================


@router.post("/register", response_model=ApiResponse)
async def register_device(
    request: DeviceRegisterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    注册/刷新本地客户端设备。

    幂等：同一 (user_id, device_id) 再次注册视为上线刷新，不新建。

    多账号支持：同一 device_id 可以被不同账号分别登记，每个账号各有一条设备记录，
    换账号登录同一台电脑不再冲突。
    """
    now = datetime.now()
    device = (
        db.query(ClientDevice)
        .filter(
            ClientDevice.device_id == request.device_id,
            ClientDevice.user_id == current_user.id,
        )
        .first()
    )

    if device:
        # 复用：刷新信息并上线
        device.device_name = request.device_name or device.device_name
        device.os = request.os or device.os
        device.app_version = request.app_version or device.app_version
        if request.capabilities is not None:
            device.capabilities = request.capabilities
        device.status = "online"
        device.last_seen_at = now
    else:
        device = ClientDevice(
            user_id=current_user.id,
            device_id=request.device_id,
            device_name=request.device_name,
            os=request.os,
            app_version=request.app_version,
            capabilities=request.capabilities,
            status="online",
            last_seen_at=now,
        )
        db.add(device)

    db.commit()
    db.refresh(device)
    logger.info(f"设备注册/刷新: device_id={request.device_id} user_id={current_user.id} status=online")
    return ApiResponse(data={"device": serialize_device(device, now=now)})


@router.post("/heartbeat", response_model=ApiResponse)
async def heartbeat_device(
    request: DeviceHeartbeatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """
    设备心跳。刷新当前用户该设备记录的 last_seen_at 并置 online；可选更新 capabilities。

    只作用于当前用户自己的设备记录（user_id + device_id），不存在则 404 引导客户端先注册。
    """
    device = (
        db.query(ClientDevice)
        .filter(
            ClientDevice.device_id == request.device_id,
            ClientDevice.user_id == current_user.id,
        )
        .first()
    )
    if not device:
        raise HTTPException(status_code=404, detail="设备未注册，请先调用 register")

    now = datetime.now()
    device.last_seen_at = now
    device.status = "online"
    if request.capabilities is not None:
        device.capabilities = request.capabilities
    db.commit()
    db.refresh(device)
    return ApiResponse(data={"device": serialize_device(device, now=now), "server_time": now.isoformat()})


@router.get("", response_model=ApiResponse)
async def list_devices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """列出当前用户的设备（admin 可见全部）。"""
    now = datetime.now()
    devices = scoped_query(db, ClientDevice, current_user).order_by(ClientDevice.created_at.desc()).all()
    return ApiResponse(data={"items": [serialize_device(d, now=now) for d in devices]})


@router.put("/{device_id}", response_model=ApiResponse)
async def update_device(
    device_id: str,
    request: DeviceUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """更新设备名称/能力。"""
    device = _load_device_for_manage(db, device_id, current_user)

    if request.device_name is not None:
        device.device_name = request.device_name
    if request.capabilities is not None:
        device.capabilities = request.capabilities
    db.commit()
    db.refresh(device)
    return ApiResponse(data={"device": serialize_device(device)})


@router.post("/{device_id}/disable", response_model=ApiResponse)
async def disable_device(
    device_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token),
):
    """禁用设备（不再派发任务）。"""
    device = _load_device_for_manage(db, device_id, current_user)

    device.status = "disabled"
    db.commit()
    db.refresh(device)
    logger.info(f"设备已禁用: device_id={device_id} user_id={current_user.id}")
    return ApiResponse(data={"device": serialize_device(device)})
