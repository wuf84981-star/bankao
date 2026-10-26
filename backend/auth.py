# ============================================================
# 门卫工具房（auth.py）： hashes 密码、签发通行证、查验通行证
# 形状照 PRD 硬规（13/17 章）：bcrypt(cost≥12) + JWT 7 天。
# ============================================================
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.db import SessionLocal
from backend.models import User

JWT_SECRET = os.environ.get("BANKAO_JWT_SECRET", "dev_only_secret_change_me")  # 上云前换真密钥并挪进 .env
JWT_DAYS = 7   # PRD：JWT 7 天有效

bearer_scheme = HTTPBearer(auto_error=False)   # 专读请求头 Authorization: Bearer <token>


def hash_password(plain: str) -> str:
    """密码→哈希：加盐单向，库里永不明文——拖库也还原不回去"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验密：原文重新走一遍哈希与库存比对——没有"解密"这回事，只有"对暗号" """
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: int) -> str:
    """签发通行证：payload 装 user_id+到期时间，密钥签名——服务器不记登录态，
    票自己证明自己没伪造（这就是 JWT 的"无状态"）"""
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(days=JWT_DAYS)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    """查通行证依赖：没票/假票/过期/户已注销，一律 401 挡在门外。
    接口只要写 `user: User = Depends(get_current_user)` 就自动上岗验票。"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="通行证无效或已过期")
    with SessionLocal() as session:
        user = session.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="账号不存在")   # 注销了但旧票还在
    return user
