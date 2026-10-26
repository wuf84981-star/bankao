# ============================================================
# S8 首刀离线单测：验证码腿（D52 甲 · F-01 注册链真身）
# 断言主线：码只存哈希（库里搜不到明文）；三闸各拦各的（60s 冷却/日限 10/
# 错 5 次作废/10 分钟过期）；register 查重不烧码、建号同事务盖消费章、一码一用；
# 寄失败整笔回滚不落账（日限额不被失败白吃）；退信分两话术——
# 收件人查无此号(SMTPRecipientsRefused) 400「地址错」vs 腿故障 503（真机 550 案换来的）；
# 信封真带正文（build_message 离线验，真机空身案换来的——假腿拦不住信封病）。
# 零真网络：monkeypatch backend.main.send_mail（电厂/OCR 假腿同款纪律）。
# fixture 结尾统一清 _ec_t 户与码账——try/finally 正范。
# ============================================================
import re
import smtplib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.db import SessionLocal
from backend.mail import build_message
from backend.main import CodeSendIn, RegisterIn, register, register_send_code
from backend.models import EmailCode, User


def _utcnow():
    return datetime.now(timezone.utc)


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        s.execute(EmailCode.__table__.delete().where(EmailCode.email.like("_ec_t%")))
        s.execute(User.__table__.delete().where(User.username.like("_ec_t%")))
        s.commit()


def _capture(monkeypatch):
    """假发送腿：拦报文，从正文里把 6 位码抠回来（真码只活在这张假信封里）"""
    out = []
    monkeypatch.setattr("backend.main.send_mail",
                        lambda to, subject, body: out.append(body))
    return out


def _code_of(body: str) -> str:
    return re.search(r"验证码是 (\d{6})", body).group(1)


def test_hashed_ledger_and_one_shot_redeem(cleanup, monkeypatch):
    """happy path：送码进账只留哈希 → 对码建号（email 落账+发证）→ 消费章盖上；
    没发过码就注册 → 拒（没有活码这条路根本进不来）。"""
    sent = _capture(monkeypatch)
    register_send_code(body=CodeSendIn(email="_EC_T1@X.TEST"))   # 大写进来必须归小写
    with SessionLocal() as s:
        row = s.scalars(select(EmailCode).where(EmailCode.email == "_ec_t1@x.test")).one()
        code = _code_of(sent[0])
        assert row.code_hash != code and code not in row.code_hash   # 明文不落库
        assert row.used_at is None
    out = register(body=RegisterIn(username="_ec_t1@x.test", password="abcd1234",
                                   email="_ec_t1@x.test", code=code))
    assert out["token"]
    with SessionLocal() as s:
        u = s.scalar(select(User).where(User.username == "_ec_t1@x.test"))
        assert u is not None and u.email == "_ec_t1@x.test"
        row = s.scalars(select(EmailCode).where(EmailCode.email == "_ec_t1@x.test")).one()
        assert row.used_at is not None           # 一码一用：建号即盖消费章
    with pytest.raises(HTTPException) as e:
        register(body=RegisterIn(username="_ec_t1c@x.test", password="abcd1234",
                                 email="_ec_t1c@x.test", code="000000"))
    assert e.value.status_code == 400 and "没有可用的验证码" in e.value.detail


def test_three_gates_each_blocks(cleanup, monkeypatch):
    """三闸：错 5 次作废（第 6 次拿对码也进不来）、过期拒、60s 冷却、日限 10。"""
    sent = _capture(monkeypatch)
    register_send_code(body=CodeSendIn(email="_ec_t2@x.test"))
    code = _code_of(sent[0])
    body = RegisterIn(username="_ec_t2@x.test", password="abcd1234",
                      email="_ec_t2@x.test", code="999999")
    for i in range(4):
        with pytest.raises(HTTPException) as e:
            register(body=body)
        assert f"还能再试 {5 - i - 1} 次" in e.value.detail
    with pytest.raises(HTTPException) as e:
        register(body=body)                       # 第 5 次错 → 当场作废
    assert "已作废" in e.value.detail
    with pytest.raises(HTTPException) as e:       # 对码也救不回复活码
        register(body=RegisterIn(username="_ec_t2@x.test", password="abcd1234",
                                 email="_ec_t2@x.test", code=code))
    assert "没有可用的验证码" in e.value.detail
    # 过期闸：发一条新码，把过期时刻拨到一分钟前
    register_send_code(body=CodeSendIn(email="_ec_t2e@x.test"))
    with SessionLocal() as s:
        row = s.scalars(select(EmailCode).where(EmailCode.email == "_ec_t2e@x.test")
                        .order_by(EmailCode.id.desc())).first()
        row.expires_at = _utcnow() - timedelta(minutes=1)
        s.commit()
    with pytest.raises(HTTPException) as e:
        register(body=RegisterIn(username="_ec_t2e@x.test", password="abcd1234",
                                 email="_ec_t2e@x.test", code=code))
    assert "已过期" in e.value.detail
    # 冷却闸：刚发过（60s 内）再发 → 429
    with pytest.raises(HTTPException) as e:
        register_send_code(body=CodeSendIn(email="_ec_t2@x.test"))
    assert e.value.status_code == 429 and "等一分钟" in e.value.detail
    # 日限闸：造 10 条今日账（created_at 钉在 UTC 日界后 1 秒起，不踩冷却）
    day_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as s:
        for i in range(10):
            s.add(EmailCode(email="_ec_t2d@x.test", purpose="register",
                            code_hash="x" * 64, expires_at=day_start + timedelta(days=1),
                            created_at=day_start + timedelta(seconds=10 + i)))
        s.commit()
    with pytest.raises(HTTPException) as e:
        register_send_code(body=CodeSendIn(email="_ec_t2d@x.test"))
    assert e.value.status_code == 429 and "今天" in e.value.detail


def test_send_failure_and_dup_gates(cleanup, monkeypatch):
    """寄失败回滚零留账（限额不被白吃）；已注册邮箱 409——老户 email 空、
    username=邮箱串的也得守得住；username 撞车 409 时码分毫不损。"""
    monkeypatch.setattr("backend.main.send_mail",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模拟 SMTP 挂了")))
    with pytest.raises(HTTPException) as e:
        register_send_code(body=CodeSendIn(email="_ec_t3f@x.test"))
    assert e.value.status_code == 503
    with SessionLocal() as s:
        assert not s.scalars(select(EmailCode).where(
            EmailCode.email == "_ec_t3f@x.test")).first()
    # 收件人查无此号（真机活体 550 标本）：分话术 400「地址错」，同样回滚零留账
    monkeypatch.setattr("backend.main.send_mail",
                        lambda *a, **k: (_ for _ in ()).throw(
                            smtplib.SMTPRecipientsRefused({"gone@x.test": (550, b"no such user")})))
    with pytest.raises(HTTPException) as e:
        register_send_code(body=CodeSendIn(email="_ec_t3r@x.test"))
    assert e.value.status_code == 400 and "似乎不存在" in e.value.detail
    with SessionLocal() as s:
        assert not s.scalars(select(EmailCode).where(
            EmailCode.email == "_ec_t3r@x.test")).first()
    monkeypatch.undo()
    sent = _capture(monkeypatch)
    # 老式户口：email 列空、username 就是邮箱串——送码也得 409
    with SessionLocal() as s:
        s.add(User(username="_ec_t3o@x.test", password_hash="x", status="normal"))
        s.commit()
    with pytest.raises(HTTPException) as e:
        register_send_code(body=CodeSendIn(email="_ec_t3o@x.test"))
    assert e.value.status_code == 409
    # username 撞车 → 409，但码不烧：used_at 空、fail_count 0
    register_send_code(body=CodeSendIn(email="_ec_t3n@x.test"))
    code = _code_of(sent[-1])
    with SessionLocal() as s:
        s.add(User(username="taken_name", password_hash="x", status="normal"))
        s.commit()
    with pytest.raises(HTTPException) as e:
        register(body=RegisterIn(username="taken_name", password="abcd1234",
                                 email="_ec_t3n@x.test", code=code))
    assert e.value.status_code == 409
    with SessionLocal() as s:
        row = s.scalars(select(EmailCode).where(EmailCode.email == "_ec_t3n@x.test")).one()
        assert row.used_at is None and row.fail_count == 0
    with SessionLocal() as s:
        s.execute(User.__table__.delete().where(User.username == "taken_name"))
        s.commit()


def test_envelope_actually_carries_body():
    """真机 19:39 案：信收到了但正文空白——EmailMessage 赋 .body 字段不上信封，
    走网的是 payload。假发送腿拦不住这种病（它把整个寄信动作都换了），
    所以信封本身要单独离线验：set_content 后 get_content 拿回的就是原正文，
    类型声明是 text/plain。"""
    body = "你的注册验证码是 123456，10 分钟内有效。"
    msg = build_message("sender@qq.com", "rcpt@qq.com", "伴考注册验证码", body)
    # set_content 会按 MIME 文本行惯例在末尾补一个换行——解回来一字不差（多个行尾符）
    assert msg.get_content() == body + "\n"
    assert msg.get_content_type() == "text/plain"
