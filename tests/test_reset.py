# ============================================================
# S8 三刀离线单测：找回密码腿（D48 甲 · 2026-09-10 拍：重发验证码式）
# 断言主线：查无此户 400 且零留账（不发信不烧钱）；成功链=换密后旧密 401 新密 200、
# 码盖消费章一码一用；purpose 各算各账（register 的码过不了 reset 的闸、
# register 的冷却不拦 reset 的发码）；错满 5 次作废；老壳（email 列空、username=邮箱串）
# 双条件找得到——户主三折案换来的教训：只查 email 会把老户锁在门外。
# 零真网络：借 test_emailcode 的假发送腿 _capture（全套纪律同款）。
# fixture 结尾统一清 _rs_t 户与码账——try/finally 正范。
# ============================================================
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from backend.auth import hash_password
from backend.db import SessionLocal
from backend.main import (LoginIn, ResetConfirmIn, ResetSendIn, _code_hash, login,
                          reset_confirm, reset_send_code)
from backend.models import EmailCode, User

# 与 test_emailcode 同款台件：假信封 + 从正文抠码（找回信正文含「验证码是 6 位」）
from test_emailcode import _capture, _code_of


def _utcnow():
    return datetime.now(timezone.utc)


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        s.execute(EmailCode.__table__.delete().where(EmailCode.email.like("_rs_t%")))
        s.execute(User.__table__.delete().where(User.username.like("_rs_t%")))
        s.commit()


def _mk_user(username: str, email: str | None, password: str):
    """直接进账造一户（不走注册链——本册测找回，注册是上一册的事）"""
    with SessionLocal() as s:
        s.add(User(username=username, password_hash=hash_password(password),
                   email=email, status="normal"))
        s.commit()


def test_reset_no_such_account(cleanup, monkeypatch):
    """查无此户：400 人话、零留账（假腿都没响——不发信不烧钱）。"""
    sent = _capture(monkeypatch)
    with pytest.raises(HTTPException) as e:
        reset_send_code(body=ResetSendIn(email="_rs_t1@x.test"))
    assert e.value.status_code == 400 and "查无此户" in e.value.detail
    assert sent == []
    with SessionLocal() as s:
        assert not s.scalars(select(EmailCode).where(
            EmailCode.email == "_rs_t1@x.test")).first()


def test_reset_full_chain(cleanup, monkeypatch):
    """happy path：送重置码 → 对码改密 → 旧密登不进（401）、新密登得进（发证）、
    码盖消费章 → 同一码再用 → 拒（一码一用）。"""
    sent = _capture(monkeypatch)
    _mk_user("_rs_t2@x.test", "_rs_t2@x.test", "oldpass1")
    reset_send_code(body=ResetSendIn(email="_rs_t2@x.test"))
    code = _code_of(sent[0])
    assert "如果不是你本人" in sent[0]          # 重置信专属话术在正文里
    reset_confirm(body=ResetConfirmIn(email="_rs_t2@x.test", code=code,
                                      new_password="newpass2"))
    with pytest.raises(HTTPException) as e:      # 旧密码作废
        login(body=LoginIn(username="_rs_t2@x.test", password="oldpass1"))
    assert e.value.status_code == 401
    out = login(body=LoginIn(username="_rs_t2@x.test", password="newpass2"))
    assert out["token"]                          # 新密码进门
    with SessionLocal() as s:
        row = s.scalars(select(EmailCode).where(EmailCode.email == "_rs_t2@x.test")
                        .order_by(EmailCode.id.desc())).first()
        assert row.used_at is not None           # 改密即盖消费章
    with pytest.raises(HTTPException) as e:      # 同码再用 → 没有活码
        reset_confirm(body=ResetConfirmIn(email="_rs_t2@x.test", code=code,
                                          new_password="newpass3"))
    assert e.value.status_code == 400 and "没有可用的验证码" in e.value.detail


def test_purpose_ledgers_independent(cleanup, monkeypatch):
    """两本账各算各的：register 码刚入账（60s 冷却窗口内），reset 发码照样放行——
    冷却/日限按 purpose 分账不误伤；跨账拿注册码来改密=错码，reset 闸只认自己账上的。"""
    sent = _capture(monkeypatch)
    _mk_user("_rs_t3@x.test", "_rs_t3@x.test", "oldpass1")
    # register 活码手工进账（送码端点对已注册户会 409 走不通——本例测的是两本账解耦，
    # 不是注册端点，直接写账最干净）
    with SessionLocal() as s:
        s.add(EmailCode(email="_rs_t3@x.test", purpose="register",
                        code_hash=_code_hash("_rs_t3@x.test", "654321"),
                        expires_at=_utcnow() + timedelta(minutes=10)))
        s.commit()
    reset_send_code(body=ResetSendIn(email="_rs_t3@x.test"))   # 不受 register 冷却拦
    assert "如果不是你本人" in sent[0]
    with pytest.raises(HTTPException) as e:                    # 注册码过不了改密闸
        reset_confirm(body=ResetConfirmIn(email="_rs_t3@x.test", code="654321",
                                          new_password="newpass2"))
    assert e.value.status_code == 400 and "验证码不对" in e.value.detail
    assert login(body=LoginIn(username="_rs_t3@x.test", password="oldpass1"))["token"]  # 密码纹丝未动


def test_wrong_code_five_times_burns(cleanup, monkeypatch):
    """防猜：错 5 次整条作废，之后拿对码也进不来（与注册腿同闸同纪——共核的兑现）。"""
    sent = _capture(monkeypatch)
    _mk_user("_rs_t4@x.test", "_rs_t4@x.test", "oldpass1")
    reset_send_code(body=ResetSendIn(email="_rs_t4@x.test"))
    code = _code_of(sent[0])
    bad = ResetConfirmIn(email="_rs_t4@x.test", code="999999", new_password="newpass2")
    for i in range(4):
        with pytest.raises(HTTPException) as e:
            reset_confirm(body=bad)
        assert f"还能再试 {5 - i - 1} 次" in e.value.detail
    with pytest.raises(HTTPException) as e:
        reset_confirm(body=bad)                    # 第 5 次错 → 当场作废
    assert "已作废" in e.value.detail
    with pytest.raises(HTTPException) as e:        # 对码也救不回复活码
        reset_confirm(body=ResetConfirmIn(email="_rs_t4@x.test", code=code,
                                          new_password="newpass2"))
    assert "没有可用的验证码" in e.value.detail


def test_old_shell_found_by_username(cleanup, monkeypatch):
    """老壳（email 列空、username=邮箱串，S1 惯例户）：双条件查得到、收得了码、改得进密
    ——只查 email 列会把整代老户锁在门外（户主三折案教训钉进测试）。"""
    sent = _capture(monkeypatch)
    _mk_user("_rs_t5@x.test", None, "oldpass1")
    reset_send_code(body=ResetSendIn(email="_rs_t5@x.test"))
    code = _code_of(sent[0])
    reset_confirm(body=ResetConfirmIn(email="_rs_t5@x.test", code=code,
                                      new_password="newpass2"))
    assert login(body=LoginIn(username="_rs_t5@x.test", password="newpass2"))["token"]


def test_weak_new_password_rejected_offline(cleanup):
    """新密码强度与注册一本账：模型层就拒（ValidationError），根本到不了库。"""
    with pytest.raises(ValidationError) as e:
        ResetConfirmIn(email="_rs_t6@x.test", code="123456", new_password="short")
    assert "≥8位" in str(e.value)
    with pytest.raises(ValidationError):
        ResetConfirmIn(email="_rs_t6@x.test", code="123456", new_password="12345678")
