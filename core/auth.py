import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
import bcrypt
from core.config import settings

logger = logging.getLogger(__name__)

SECRET_KEY = settings.get_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
CHAPTER_COST = 1.0

security = HTTPBearer(auto_error=False)


def _bcrypt_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_bytes(plain), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: int, username: str, role: str = "user", expires_delta: timedelta = None) -> str:
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="未登录，请先登录")
        token = auth_header.split(" ", 1)[1]
    else:
        token = credentials.credentials

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token无效或已过期")

    user_id = int(payload.get("sub", 0))
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="Token无效")

    from core.database import SessionLocal
    from models.db_models import User
    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被禁用")
        return {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "balance": user.balance,
            "email": user.email,
            "nickname": user.nickname,
        }


async def get_current_user_optional(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials is None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            payload = decode_token(token)
            if payload:
                try:
                    return await get_current_user(request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
                except HTTPException:
                    pass
        return None
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


def require_role(*roles):
    async def checker(current_user: dict = Depends(get_current_user)):
        if current_user["role"] not in roles and current_user["role"] != "admin":
            raise HTTPException(status_code=403, detail=f"需要{','.join(roles)}角色权限")
        return current_user
    return checker


def deduct_balance(user_id: int, amount: float, consumption_type: str = "generate_chapter", project_id: str = None, description: str = "") -> bool:
    from core.database import SessionLocal
    from models.db_models import User, ConsumptionRecord

    with SessionLocal() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        if user.balance < amount:
            return False

        user.balance -= amount
        user.total_consumed += amount
        record = ConsumptionRecord(
            user_id=user_id,
            project_id=project_id,
            amount=amount,
            consumption_type=consumption_type,
            description=description,
        )
        db.add(record)
        db.commit()
        return True
