# ============================================================
# S8 管理页回归（D54 全拆邀请码 2026-09-10 · F-04 退役后的留守件）
# 断言主线：户主闸（非旗号 403，D49 甲钥匙形状不变）；用户清单形状且无来源列；
# 注册契约不带 invite 就成功、旧客户端多带的 invite 字段被无视（pydantic extra 默认忽略）；
# 户主旗号只认 env 比对（大小写宽容）。
# 前身 test_invite.py 四例随邀请码报废删除，幸存主张迁至本文件。
# 零真网络：假发送腿照借 test_emailcode。fixture 尾清 _ad_t 户与码账。
# ============================================================
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.db import SessionLocal
from backend.main import CodeSendIn, RegisterIn, admin_user_list, register, register_send_code
from backend.models import EmailCode, User
from test_emailcode import _capture, _code_of


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        s.execute(EmailCode.__table__.delete().where(EmailCode.email.like("_ad_t%")))
        s.execute(User.__table__.delete().where(User.username.like("_ad_t%")))
        s.commit()


def _make_user(name: str, email: str | None = None, admin: bool = False) -> int:
    with SessionLocal() as s:
        u = User(username=name, email=email, password_hash="x", is_admin=admin)
        s.add(u)
        s.commit()
        return u.id


def _get_user(uid: int) -> User:
    with SessionLocal() as s:
        return s.get(User, uid)


def test_user_list_only_for_owner(cleanup):
    """户主闸+清单形状：平民 403；户主可见全员；来源列已随邀请码退役。"""
    boss = _make_user("_ad_t1_boss", email="_ad_t1_boss@x.test", admin=True)
    peon = _make_user("_ad_t1_peon", email="_ad_t1_peon@x.test")
    with pytest.raises(HTTPException) as e:
        admin_user_list(user=_get_user(peon))
    assert e.value.status_code == 403 and "户主" in e.value.detail
    items = admin_user_list(user=_get_user(boss))["items"]
    me = next(i for i in items if i["id"] == boss)
    assert me["username"] == "_ad_t1_boss" and me["is_admin"] is True
    assert "invite_code" not in me          # 拆干净：响应里不该再有来源字段


def test_register_needs_no_invite(cleanup, monkeypatch):
    """D54 注册契约：无 invite 字段建号成功；旧页面多带 invite 串也被无视不报错。"""
    sent = _capture(monkeypatch)
    register_send_code(body=CodeSendIn(email="_ad_t2_free@x.test"))
    res = register(body=RegisterIn(username="_ad_t2_free@x.test", password="abcd1234",
                                   email="_ad_t2_free@x.test", code=_code_of(sent[-1])))
    assert res["token"]
    # 旧客户端残留 invite：model_validate 走 JSON 路，extra 字段宽容忽略
    register_send_code(body=CodeSendIn(email="_ad_t2_old@x.test"))
    res2 = register(body=RegisterIn.model_validate({
        "username": "_ad_t2_old@x.test", "password": "abcd1234",
        "email": "_ad_t2_old@x.test", "code": _code_of(sent[-1]),
        "invite": "ZK-XXXX-XXXX"}))
    assert res2["token"]


def test_owner_flag_from_env(cleanup, monkeypatch):
    """户主旗号（D49 甲留守）：注册 email 对上 BANKAO_ADMIN_EMAIL 才盖，大小写宽容。"""
    sent = _capture(monkeypatch)
    monkeypatch.setenv("BANKAO_ADMIN_EMAIL", "_AD_T3_BOSS@X.TEST")   # 大写存底也要认得
    register_send_code(body=CodeSendIn(email="_ad_t3_boss@x.test"))
    register(body=RegisterIn(username="_ad_t3_boss@x.test", password="abcd1234",
                             email="_ad_t3_boss@x.test", code=_code_of(sent[-1])))
    with SessionLocal() as s:
        assert s.scalar(select(User.is_admin).where(
            User.username == "_ad_t3_boss@x.test")) is True
