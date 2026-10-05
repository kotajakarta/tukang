from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, status
from app.services.user_service import user_service

router = APIRouter(prefix="/users", tags=["User & SSH Key Management"])

class UserCreateRequest(BaseModel):
    username: str
    shell: str = "/bin/bash"
    is_sudo: bool = False

class KeyAddRequest(BaseModel):
    key: str

@router.get("/{server_id}")
async def list_users(server_id: str):
    return await user_service.list_users(server_id)

@router.post("/{server_id}")
async def create_user(server_id: str, body: UserCreateRequest):
    success, msg = await user_service.create_user(server_id, body.username, body.shell, body.is_sudo)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.delete("/{server_id}/{username}")
async def delete_user(server_id: str, username: str, remove_home: bool = True):
    success, msg = await user_service.delete_user(server_id, username, remove_home)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.get("/{server_id}/{username}/keys")
async def get_keys(server_id: str, username: str):
    keys = await user_service.get_authorized_keys(server_id, username)
    return {"username": username, "keys": keys}

@router.post("/{server_id}/{username}/keys")
async def add_key(server_id: str, username: str, body: KeyAddRequest):
    success, msg = await user_service.add_authorized_key(server_id, username, body.key)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}
