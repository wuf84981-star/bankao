# ============================================================
# S8 四刀离线单测：埋点账（D55 甲 · 2026-09-10 拍：analytics_events 单表+四路接线）
# 断言主线：三道门（注册/登录/找回）与开口腿（网页+QQ）各见事件行、渠道进 props；
# _track 家规两条钉死——记账腿炸不外包（只看不拦）、dict/list 属性被丢（隐私口径）；
# stats 端点户主闸 403 + 回执形状。零真网络：注册/找回借假发送腿，开口借假 answer_turn
# ——电厂一分离，测试绝不出门。fixture 清 _tk_t 户及其事件/绑定/码账（try/finally 正范）。
# ============================================================
import pytest
from fastapi import HTTPException
from sqlalchemy import select

import backend.analytics as analytics
import backend.main as m
import backend.qq as qq
from backend.db import SessionLocal
from backend.main import (ChatIn, CodeSendIn, LoginIn, RegisterIn, ResetConfirmIn,
                          ResetSendIn, admin_stats, chat, login,
                          register, register_send_code, reset_confirm, reset_send_code)
from backend.qq import handle_qq_event
from backend.models import AnalyticsEvent, EmailCode, QQBinding, User

from test_emailcode import _capture, _code_of


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        ids = [r[0] for r in s.execute(
            select(User.id).where(User.username.like("_tk_t%"))).all()]
        if ids:
            s.execute(AnalyticsEvent.__table__.delete().where(
                AnalyticsEvent.user_id.in_(ids)))
            s.execute(QQBinding.__table__.delete().where(QQBinding.user_id.in_(ids)))
        s.execute(EmailCode.__table__.delete().where(EmailCode.email.like("_tk_t%")))
        s.execute(User.__table__.delete().where(User.username.like("_tk_t%")))
        s.commit()


def _events(username: str) -> list[AnalyticsEvent]:
    """按户主名回捞事件账（带 props 与 event 名，形状断言用）"""
    with SessionLocal() as s:
        uid = s.scalar(select(User.id).where(User.username == username))
        return s.scalars(select(AnalyticsEvent)
                         .where(AnalyticsEvent.user_id == uid)
                         .order_by(AnalyticsEvent.id)).all()


def test_three_gates_all_ledgered(cleanup, monkeypatch):
    """三道门各记一笔：注册→sign_up_completed、登录→login_completed、
    找回→password_reset_completed；网页门事件都带 channel=web 小票。"""
    sent = _capture(monkeypatch)
    email = "_tk_t1@x.test"
    register_send_code(body=CodeSendIn(email=email))
    register(body=RegisterIn(username=email, password="passw0rd1", email=email,
                             code=_code_of(sent[0])))
    login(body=LoginIn(username=email, password="passw0rd1"))
    reset_send_code(body=ResetSendIn(email=email))
    reset_confirm(body=ResetConfirmIn(email=email, code=_code_of(sent[1]),
                                      new_password="passw0rd2"))
    names = [(e.event, (e.props or {}).get("channel")) for e in _events(email)]
    assert ("sign_up_completed", "web") in names
    assert ("login_completed", "web") in names
    assert ("password_reset_completed", None) in names   # 找回不分渠道，无 channel 键


def test_web_chat_leg_wired(cleanup, monkeypatch):
    """开口即活（周活跃主料）：/api/chat 成功回执 → chat_message_sent 入账。
    假 answer_turn 顶掉真大脑——测试绝不出门找电厂。"""
    sent = _capture(monkeypatch)
    email = "_tk_t2@x.test"
    register_send_code(body=CodeSendIn(email=email))
    out = register(body=RegisterIn(username=email, password="passw0rd1", email=email,
                                   code=_code_of(sent[0])))
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.username == email))

    def fake_turn(session, uid, message, conv_id=None, **kw):
        return {"reply": "测试回复", "remaining": 900, "notice": "",
                "points_spent": 3, "balance": 997,   # D64 回执新两键，假件跟形状
                "used_tools": [], "citations": [], "conv_id": 1}
    monkeypatch.setattr(m, "answer_turn", fake_turn)
    r = chat(body=ChatIn(message="你好"), user=user)
    assert r["reply"] == "测试回复"
    evs = [(e.event, (e.props or {}).get("channel")) for e in _events(email)]
    assert ("chat_message_sent", "web") in evs


def test_qq_leg_wired(cleanup, monkeypatch):
    """QQ 腿同账不同票：handle_qq_event 成功回话 → chat_message_sent 且 channel=qq。
    err 回执（配额爆/会话缺）不记账——没发生的开口不上账。"""
    sent = _capture(monkeypatch)
    email = "_tk_t3@x.test"
    register_send_code(body=CodeSendIn(email=email))
    register(body=RegisterIn(username=email, password="passw0rd1", email=email,
                             code=_code_of(sent[0])))
    with SessionLocal() as s:
        uid = s.scalar(select(User.id).where(User.username == email))
        s.add(QQBinding(user_id=uid, qq_number="_tkq3", status="bound"))
        s.commit()

    monkeypatch.setattr(qq, "answer_turn",
                        lambda session, uid, text, **kw: {"reply": "QQ测试回复"})
    with SessionLocal() as s:
        assert handle_qq_event(s, "_tkq3", "你好") == "QQ测试回复"
    evs = [(e.event, (e.props or {}).get("channel")) for e in _events(email)]
    assert ("chat_message_sent", "qq") in evs

    monkeypatch.setattr(qq, "answer_turn",
                        lambda session, uid, text, **kw: {"err": "quota", "msg": "额度用尽"})
    with SessionLocal() as s:
        assert handle_qq_event(s, "_tkq3", "你好") == "额度用尽"
    evs = [(e.event, (e.props or {}).get("channel")) for e in _events(email)]
    assert evs.count(("chat_message_sent", "qq")) == 1   # 只有第一次真开口在账上


def test_track_swallows_crash(cleanup, monkeypatch, capsys):
    """家规一（只看不拦）：记账腿整个炸掉，_track 只自曝不抛——
    主流程（进门/改密/发消息）绝不因一笔账崩。"""
    def boom(*a, **kw):
        raise RuntimeError("假账房罢工")
    monkeypatch.setattr(analytics, "SessionLocal", boom)
    _ = analytics._track(999999, "smoke_test", channel="test")   # 不抛=过
    assert "记账失败" in capsys.readouterr().out


def test_dict_props_dropped(cleanup, monkeypatch, capsys):
    """家规二（隐私口径在函数层执法）：dict/list 属性（消息正文的形状）当场丢弃+留声，
    标量照常入账——「想误传进来」在形状上就进不来。"""
    sent = _capture(monkeypatch)
    email = "_tk_t4@x.test"
    register_send_code(body=CodeSendIn(email=email))
    register(body=RegisterIn(username=email, password="passw0rd1", email=email,
                             code=_code_of(sent[0])))
    with SessionLocal() as s:
        uid = s.scalar(select(User.id).where(User.username == email))
    analytics._track(uid, "shape_test", body={"正文": "机密"},
                     history=["一", "二"], flag=True, n=42)
    out = capsys.readouterr().out
    assert "丢弃" in out and "shape_test" in out
    with SessionLocal() as s:
        row = s.scalars(select(AnalyticsEvent).where(
            AnalyticsEvent.event == "shape_test",
            AnalyticsEvent.user_id == uid)).one()
    assert row.props == {"flag": True, "n": 42}   # 只剩标量，正文形状无影无踪


def test_stats_gate_and_shape(cleanup):
    """stats 端点双相：平民 403（户主闸）；户主回三相形状（events 列表+周活跃+总户数），
    且 events 里查不到 props 明细——页上只给数不给事。"""
    plain = User(username="x", is_admin=False)
    with pytest.raises(HTTPException) as e:
        admin_stats(user=plain)
    assert e.value.status_code == 403
    out = admin_stats(user=User(username="boss", is_admin=True))
    assert set(out) == {"events", "weekly_active", "total_users"}
    assert all(set(ev) == {"event", "count", "last_at"} for ev in out["events"])
