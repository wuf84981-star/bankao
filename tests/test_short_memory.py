# ============================================================
# S9·W6 短期记忆离线回归（backend/short_memory.py）
# 断言主线：降级语义（client 灭/坏窗/缓存腿失手=逐字等于旧 PG 直读路）、
# 命中不查库、未命中回填形状（近20正序/封顶/挂TTL）、写路只添不删、
# try_lock 是礼貌闸（摸不到一律放行）、summary_of 坏数据当没摘要。
# Redis 全假件（FakeRedis 内存字典）——不碰真箱；PG 造数仿 test_gaps，_sm 尾清。
# ============================================================
import json

import pytest
from sqlalchemy import select
from sqlalchemy import text as sa_text

from backend import short_memory as sm
from backend.db import SessionLocal
from backend.jobs import SUMMARY_MIN_MSGS, summarize_conv
from backend.models import Conversation, Message, User
from test_admin import _make_user


class FakeRedis:
    """redis-py 五指最小替身：lrange/delete/rpush/ltrim/expire/exists/set。"""
    def __init__(self):
        self.lists = {}
        self.ttls = {}
        self.kvs = {}

    def lrange(self, key, a, b):
        return list(self.lists.get(key, []))

    def delete(self, key):
        self.lists.pop(key, None)

    def rpush(self, key, *vals):
        self.lists.setdefault(key, []).extend(vals)
        return len(self.lists[key])

    def ltrim(self, key, a, b):
        lst = self.lists.get(key, [])
        self.lists[key] = lst[a:] if b == -1 else lst[a:b + 1]

    def expire(self, key, secs):
        self.ttls[key] = secs

    def exists(self, key):
        return 1 if key in self.lists else 0

    def set(self, key, val, nx=False, ex=None):
        if nx and key in self.kvs:
            return None
        self.kvs[key] = val
        return True


@pytest.fixture()
def fake(monkeypatch):
    """掉包 get_client：恒给假箱（默认在场，测灭路各自另装）。"""
    r = FakeRedis()
    monkeypatch.setattr(sm, "get_client", lambda: r)
    return r


@pytest.fixture()
def reset_state(monkeypatch):
    """模块级静默旗复位，测完还原——不污染同进程其他用例。"""
    monkeypatch.setattr(sm, "_client", None)
    monkeypatch.setattr(sm, "_dead", False)
    yield


def _boom(*a, **k):
    raise AssertionError("命中路径不该碰 PG")


def _uid(name):
    return _make_user(name, email=f"{name}@x.test")


def _seed_conv(uid, n):
    """造会话线灌 n 条消息（内容 m0..m{n-1} 编号可验序），回 conv id。"""
    with SessionLocal() as s:
        conv = Conversation(user_id=uid, channel="web", title="_sm 线")
        s.add(conv)
        s.flush()
        for i in range(n):
            s.add(Message(conversation_id=conv.id,
                          role="user" if i % 2 == 0 else "assistant",
                          content=f"m{i}", token_count=1))
        s.commit()
        return conv.id


@pytest.fixture()
def cleanup():
    yield
    with SessionLocal() as s:
        s.execute(User.__table__.delete().where(User.username.like("_sm%")))
        s.commit()


# ── get_client：失败永久静默（2 例）──

def test_client_failure_stays_silent(monkeypatch, reset_state):
    monkeypatch.setenv("REDIS_URL", "bogus://x")   # from_url 当场 ValueError，不试网络
    assert sm.get_client() is None
    assert sm._dead is True
    assert sm.get_client() is None                 # 第二次不再尝试（防重试风暴）


def test_client_lazy_build_with_ping(monkeypatch, reset_state):
    """首用才建连：ping 不通=降级不是炸——答题腿照走 PG。"""
    class NoPing:
        def ping(self):
            raise ConnectionError("箱没了")
    monkeypatch.setattr("redis.Redis.from_url", lambda *a, **k: NoPing())
    assert sm.get_client() is None
    assert sm._dead is True


# ── window_get：三进路（4 例）──

def test_window_hit_skips_pg(fake):
    fake.lists["mem:conv:5"] = [json.dumps({"role": "user", "content": "早"}),
                                json.dumps({"role": "assistant", "content": "好"})]
    assert sm.window_get(_boom, 5) == [{"role": "user", "content": "早"},
                                       {"role": "assistant", "content": "好"}]


def test_window_miss_reads_pg_and_backfills(fake, cleanup):
    """22 条库→只还近 20 正序（m2 起——m0/m1 滚出窗）；回填见窗、挂 TTL。"""
    cid = _seed_conv(_uid("_sm_w1"), 22)
    with SessionLocal() as s:
        out = sm.window_get(s, cid)
    assert [d["content"] for d in out] == [f"m{i}" for i in range(2, 22)]
    key = f"mem:conv:{cid}"
    assert len(fake.lists[key]) == 20              # LTRIM 封顶生效
    assert fake.ttls[key] == sm.WINDOW_TTL


def test_window_broken_json_refalls(fake, cleanup):
    fake.lists["mem:conv:9"] = ["{坏窗"]           # 半截 JSON=整窗作废
    cid = _seed_conv(_uid("_sm_w2"), 3)
    with SessionLocal() as s:
        out = sm.window_get(s, cid)
    assert [d["content"] for d in out] == ["m0", "m1", "m2"]


def test_client_dead_equals_old_path(cleanup):
    """降级语义钉：client 全灭时 window_get 的结果=旧代码原样查 PG。"""
    def select_msg(cid):
        return (select(Message).where(Message.conversation_id == cid)
                .order_by(Message.id.desc()).limit(sm.WINDOW_N))
    cid = _seed_conv(_uid("_sm_w3"), 4)
    with SessionLocal() as s:
        hist = list(s.scalars(select_msg(cid)).all())[::-1]
        expect = [{"role": m.role, "content": m.content} for m in hist]
    from unittest.mock import patch
    with patch.object(sm, "get_client", return_value=None):
        with SessionLocal() as s:
            assert sm.window_get(s, cid) == expect


# ── note_message：只添不删、无窗跳过（2 例）──

def test_note_appends_and_caps(fake):
    key = "mem:conv:7"
    fake.lists[key] = [json.dumps({"role": "user", "content": f"x{i}"},
                                  ensure_ascii=False)
                       for i in range(sm.WINDOW_N)]   # 满窗
    sm.note_message(7, "assistant", "新句")
    assert fake.lists[key][-1] == json.dumps(
        {"role": "assistant", "content": "新句"}, ensure_ascii=False)
    assert len(fake.lists[key]) == sm.WINDOW_N         # 最老的被 LTRIM 挤出去
    assert fake.lists[key][0] == json.dumps({"role": "user", "content": "x1"},
                                            ensure_ascii=False)


def test_note_skips_when_no_window(fake):
    sm.note_message(8, "user", "首句")
    assert "mem:conv:8" not in fake.lists              # 不写半窗孤儿


# ── try_lock：礼貌闸（2 例）──

def test_lock_nx_semantics(fake):
    assert sm.try_lock("compress:3") is True
    assert sm.try_lock("compress:3") is False          # 被占=这轮不重复工
    assert sm.try_lock("compress:4") is True           # 别的会话不串闸


def test_lock_passes_when_cache_unreachable(monkeypatch):
    """Redis 摸不到一律放行——幂等靠 until_id 乐观条件，不靠锁。"""
    monkeypatch.setattr(sm, "get_client", lambda: None)
    assert sm.try_lock("compress:9") is True
    bad = FakeRedis()
    bad.set = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("断线"))
    monkeypatch.setattr(sm, "get_client", lambda: bad)
    assert sm.try_lock("compress:9") is True


# ── summary_of：坏数据当没摘要（1 例）──

def test_summary_of_shapes():
    from types import SimpleNamespace as NS
    assert sm.summary_of(NS(context_summary=None)) is None
    ok = json.dumps({"until_id": 42, "text": "前面聊过基期量", "model": "q", "at": "t"})
    assert sm.summary_of(NS(context_summary=ok)) == "前面聊过基期量"
    assert sm.summary_of(NS(context_summary="{坏")) is None
    assert sm.summary_of(NS(context_summary=json.dumps({"until_id": 1}))) is None


def test_with_summary_two_forms():
    from types import SimpleNamespace as NS
    assert sm.with_summary("你是教练", NS(context_summary=None)) == "你是教练"
    raw = json.dumps({"until_id": 1, "text": "旧事一桩"}, ensure_ascii=False)
    out = sm.with_summary("你是教练", NS(context_summary=raw))
    assert out.startswith("你是教练") and "【前情摘要" in out and "旧事一桩" in out


# ── 压缩闹钟：summarize_conv（4 例）──

def test_summarize_short_conv_skipped(cleanup):
    """没到 24 条不起算——电厂一次不烧（chat_fn=_boom 站岗）。"""
    cid = _seed_conv(_uid("_sm_s1"), SUMMARY_MIN_MSGS - 1)
    with SessionLocal() as s:
        assert summarize_conv(s, cid, chat_fn=_boom) is False


def test_summarize_first_write_then_idempotent(cleanup):
    """26 条→倒数第 21 行前滚摘要（头 6 条 m0..m5 进料）；写回四要素；再跑无新旧行= False。"""
    cid = _seed_conv(_uid("_sm_s2"), 26)
    seen = {}
    def fake(msgs, model=None):
        seen["body"] = msgs[1]["content"]
        seen["model"] = model
        return ({"role": "assistant", "content": "学生连问 22 条基期量"}, 30, 8)
    with SessionLocal() as s:
        assert summarize_conv(s, cid, chat_fn=fake) is True
        assert "m0" in seen["body"] and "m25" not in seen["body"]  # 只滚旧 6 行（26-20）
        assert "前情摘要" not in seen["body"]                       # 首压没有旧摘要
    with SessionLocal() as s:
        d = json.loads(s.get(Conversation, cid).context_summary)
        assert d["text"] == "学生连问 22 条基期量" and d["until_id"] > 0
        assert set(d) == {"until_id", "text", "model", "at"}
        assert summarize_conv(s, cid, chat_fn=_boom) is False      # 幂等：不重烧
    # 增量：补 6 条新消息→旧摘要进提示词滚着压，until_id 前进
    with SessionLocal() as s:
        for i in range(26, 32):
            s.add(Message(conversation_id=cid, role="user",
                          content=f"m{i}", token_count=1))
        s.commit()
    def fake2(msgs, model=None):
        seen["body2"] = msgs[1]["content"]
        return ({"role": "assistant", "content": "摘要v2"}, 1, 1)
    with SessionLocal() as s:
        assert summarize_conv(s, cid, chat_fn=fake2) is True
        assert "学生连问 22 条基期量" in seen["body2"]              # 旧摘要续传
        assert "m6" in seen["body2"] and "m11" in seen["body2"]     # 只来新行 m6..m11
        assert "m12" not in seen["body2"]
        assert json.loads(s.get(Conversation, cid).context_summary)["text"] == "摘要v2"


def test_summarize_optimistic_lock_loses(cleanup):
    """fake chat 背后抢先提交=另一实例赢了——本把写回 WHERE 原串不中，False 认输。"""
    cid = _seed_conv(_uid("_sm_s3"), 26)
    def thief(msgs, model=None):
        with SessionLocal() as s2:
            s2.execute(sa_text("UPDATE conversations SET context_summary=:v "
                               "WHERE id=:c"),
                       {"v": json.dumps({"until_id": 1, "text": "别人的摘要",
                                         "model": "q", "at": "t"}, ensure_ascii=False),
                        "c": cid})
            s2.commit()
        return ({"role": "assistant", "content": "我的摘要"}, 1, 1)
    with SessionLocal() as s:
        assert summarize_conv(s, cid, chat_fn=thief) is False
    with SessionLocal() as s:
        assert (json.loads(s.get(Conversation, cid).context_summary)
                ["text"] == "别人的摘要")


def test_summarize_llm_error_stays_quiet(cleanup):
    """电厂炸=留声 False，不落半个摘要——闹钟腿永远不许吓到答题腿。"""
    cid = _seed_conv(_uid("_sm_s4"), 26)
    def boom(msgs, model=None):
        raise ConnectionError("电厂关门")
    with SessionLocal() as s:
        assert summarize_conv(s, cid, chat_fn=boom) is False
    with SessionLocal() as s:
        assert s.get(Conversation, cid).context_summary is None
