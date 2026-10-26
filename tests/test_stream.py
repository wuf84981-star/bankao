# ============================================================
# D67 甲 离线单测：流式腿用户行先落账（2026-09-12 断线案的家法钉）
# 案底：旧形状下用户行+教练行挤在流尾同一个 commit——流中途被刷新掐死
# （或电厂半路炸）时收尾永不到站，问答整对从账上蒸发。
# 新家法：闸全过、流一开，用户行先进账；教练行照旧流尾原子落（BR-11 不动）。
# 铁律：电厂全假件注入——monkeypatch backend.main.chat_stream，零真网络零烧钱。
# 直调 route 函数传 SimpleNamespace 绕 Depends 的先例：test_conv。
# D82 甲（2026-10-18）续例：事务轨票闸——票面以嘴为准，两轨共闸同函数。
# ============================================================
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend import main
from backend.db import SessionLocal
from backend.main import ChatIn, chat_stream_api
from backend.models import Conversation, Message, PointsLedger, UsageLog


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_stream_t', 'x', 'normal', now()) RETURNING id")).scalar()
        # D64 口粮：验落账秩序不验钱包，先开池再开口
        s.execute(text("INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                       "VALUES (:u, current_date, 'bonus', 999999, now())"), {"u": u})
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走一切
        s.commit()


def _user(uid):
    return SimpleNamespace(id=uid, username="_stream_t")


def _rows(uid):
    """本测试户全部消息（按落库序）——join 会话找主人，测试户可能开新线不知 id"""
    with SessionLocal() as s:
        return list(s.query(Message.role, Message.content)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .filter(Conversation.user_id == uid)
                    .order_by(Message.id).all())


def _drain(resp) -> list[str]:
    """把 StreamingResponse 榨干收齐 SSE 帧——body_iterator 已被 Starlette
    包成线程池异步生成器（同步 generator 不直吐字符串），只能 async 收账"""
    import asyncio

    async def _collect():
        return [f if isinstance(f, str) else f.decode() async for f in resp.body_iterator]

    return asyncio.run(_collect())


def test_stream_user_row_lands_before_first_token(uid, monkeypatch):
    """正常轮：电厂还在吐第一个字时用户行已在账上；流尾双行合龙、各只一条零双胎"""
    def fake_stream(messages, *, tools=None, model=None):
        # 进门 commit 的现场审计：第一个字没出口之前，话必须已经记账
        assert _rows(uid) == [("user", "钉我进账")], "用户行没抢在首字前落账"
        yield ("delta", "好")
        yield ("message", {"role": "assistant", "content": "好"}, 7, 3)

    monkeypatch.setattr(main, "chat_stream", fake_stream)
    frames = _drain(chat_stream_api(ChatIn(message="钉我进账"), _user(uid)))
    assert _rows(uid) == [("user", "钉我进账"), ("assistant", "好")]
    assert any('"delta": "好"' in f for f in frames)      # 字照旧流式转发
    assert any('"done"' in f for f in frames)             # 尾帧结算照常
    with SessionLocal() as s:   # 流尾一笔记账没被双写：10 tokens→1分×flash1倍
        assert s.query(UsageLog).filter(UsageLog.user_id == uid).count() == 1
        spends = [p.amount for p in s.query(PointsLedger).filter(
            PointsLedger.user_id == uid, PointsLedger.kind == "consume").all()]
        assert spends == [-1]


def test_stream_user_row_survives_powerplant_death(uid, monkeypatch):
    """电厂半路炸：教练行不落的旧规矩不变，但用户行必须活下来（断案的核心钉）"""
    def fake_stream(messages, *, tools=None, model=None):
        yield ("delta", "半")
        raise RuntimeError("电厂炸了")

    monkeypatch.setattr(main, "chat_stream", fake_stream)
    frames = _drain(chat_stream_api(ChatIn(message="这句会断"), _user(uid)))
    assert _rows(uid) == [("user", "这句会断")]   # 问在账上——刷新再狠也不蒸发
    assert any('"error"' in f for f in frames)   # 前端收到明码 error 帧，不是断流
    with SessionLocal() as s:   # BR-11：故障轮零记账零扣分——半句白看也不扣钱
        assert s.query(UsageLog).filter(UsageLog.user_id == uid).count() == 0
        assert s.query(PointsLedger).filter(
            PointsLedger.user_id == uid, PointsLedger.kind == "consume").count() == 0


def test_stream_refused_chat_lands_nothing(uid):
    """拒聊零成本：积分闸拦下的句，用户行一个字都不许落（先落账排在闸之后）"""
    with SessionLocal() as s:
        s.execute(text("UPDATE points_ledger SET amount = -5 WHERE user_id = :u"), {"u": uid})
        s.commit()
    with pytest.raises(HTTPException) as ei:
        chat_stream_api(ChatIn(message="没口粮还想说"), _user(uid))
    assert ei.value.status_code == 429
    assert _rows(uid) == []


def test_stream_citations_mouth_gated(uid, monkeypatch):
    """D82 甲（10-18 党史轮真机复发案销账）：检索给 2 块、正文只标 [2]——
    done 帧与落库行都只留那张；事务轨票面从此与教学轨同一判据（tools.cited_by_reply）。"""
    def fake_search(session, query, user_id, top_k=2):
        return {"results": [{"id": 111, "material_id": 9, "title": "讲义A",
                             "seq": 1, "content": "七七事变的事", "score": 0.8},
                            {"id": 222, "material_id": 9, "title": "讲义A",
                             "seq": 2, "content": "七大的事", "score": 0.7}],
                "degraded": None, "top_vec": 0.8}   # 高分免进缺口账，例子不脏旁账
    monkeypatch.setattr("backend.search.search", fake_search)

    calls = {"n": 0}
    def fake_stream(messages, *, tools=None, model=None):
        calls["n"] += 1
        if calls["n"] == 1:   # 第一轮：举手查资料（静默轮，不吐字）
            yield ("message", {"role": "assistant", "content": "",
                               "tool_calls": [{"id": "c1", "function": {
                                   "name": "search_materials",
                                   # 真电厂形状：arguments 是 JSON 字符串不是 dict
                                   "arguments": '{"query": "建党什么时候"}'}}]},
                   40, 5)
        else:                  # 收口轮：嘴只认第 2 块
            yield ("message", {"role": "assistant",
                               "content": "建党是 1921 年[2]"}, 30, 4)

    monkeypatch.setattr(main, "chat_stream", fake_stream)
    frames = _drain(chat_stream_api(ChatIn(message="建党什么时候"), _user(uid)))
    payload = json.loads([f for f in frames if '"done"' in f][0][len("data: "):])
    assert [c["chunk_id"] for c in payload["done"]["citations"]] == [222]
    with SessionLocal() as s:
        row = s.query(Message).join(
            Conversation, Message.conversation_id == Conversation.id
        ).filter(Conversation.user_id == uid,
                 Message.role == "assistant").one()
        # 落库行同过滤后账（ref 不在票上、位次即票号——与喂模型那本一致）
        assert row.citations == [{"chunk_id": 222, "material_id": 9,
                                  "title": "讲义A", "seq": 2}]
