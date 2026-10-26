# ============================================================
# S6 三刀离线单测：QQ 通道（F-34 · D23/D26/D27 甲案纸面半程）
# 核心断言：绑定码闭环（6位/10分钟/错3作废/一号一主）、QQ 会话与网页分家
# 但大脑与配额同源（answer_turn 共闸）、未绑零 token 只回指引、
# 提醒推送腿三态（NULL=没绑 / fail=窗内待重试 / ok=嘴也到过）——重试只推不再发。
# 电厂全程用假 chat_fn 注入（零真 key）；OneBot 推送 monkeypatch 成假件（零真网络）。
# 台件借 test_remind：uid 同款形状、_tick/_reminders 原样复用。
# ============================================================
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import text

import backend.qq as qqmod
from backend.db import SessionLocal
from backend.jobs import run_reminder_tick
from backend.orchestrator import DAILY_QUOTA, answer_turn
from backend.qq import GUIDE, gen_bind_code, handle_qq_event
from backend.tools import set_remind_time
from test_plan import TODAY, _activated, _ctx, _setup
from test_remind import _reminders, _tick


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_qq_t', 'x', 'normal', now()) RETURNING id")).scalar()
        # D64 口粮：QQ 腿与网页腿同闸（余额≤0 谁都别开口）——本册验分线，先开池
        s.execute(text("INSERT INTO points_ledger (user_id, day, kind, amount, created_at) "
                       "VALUES (:u, current_date, 'bonus', 999999, now())"), {"u": u})
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # qq_bindings 级联走
        s.commit()


def _chat(msgs, tools=None):
    """假电厂：开口就收口（无 tool_calls），记 15 token 流水"""
    return ({"role": "assistant", "content": "收到，已记在你名下。"}, 10, 5)


def _bind(s, u, qq):
    """发码→QQ 递码的快捷全流程，返回码"""
    code = gen_bind_code(s, u)
    assert "绑定成功" in handle_qq_event(s, qq, code)
    return code


def _bindrow(s, u):
    return s.execute(text(
        "SELECT status, bind_code, qq_number, fail_count, bound_at "
        "FROM qq_bindings WHERE user_id = :u"), {"u": u}).first()


def test_bind_code_flow(uid):
    """发码形状（6位数字/pending 落账）→ 递码绑成（清码/写 QQ 号/盖 bound_at）"""
    with SessionLocal() as s:
        code = gen_bind_code(s, uid)
        assert len(code) == 6 and code.isdigit()
        row = _bindrow(s, uid)
        assert row.status == "pending" and row.bind_code == code
        assert row.qq_number is None                      # 发码不预占 QQ 号
        # 重发=重置：fail 归零、旧码作废换新码
        code2 = gen_bind_code(s, uid)
        assert code2 != code and _bindrow(s, uid).status == "pending"
        assert "绑定成功" in handle_qq_event(s, "10001", code2)
        row = _bindrow(s, uid)
        assert row.status == "bound" and row.qq_number == "10001"
        assert row.bind_code is None and row.bound_at is not None   # 一次性：绑成即清码


def test_wrong_code_three_times_voids(uid):
    """错 3 次作废（F-34①的秤）；作废后网页重发满血复活"""
    with SessionLocal() as s:
        code = gen_bind_code(s, uid)
        bad = "999999" if code != "999999" else "888888"
        for i in (1, 2):
            assert "没认出" in handle_qq_event(s, "20002", bad)
            assert _bindrow(s, uid).fail_count == i
        assert "作废" in handle_qq_event(s, "20002", bad)
        assert _bindrow(s, uid).status == "invalid"
        gen_bind_code(s, uid)                             # 网页重发
        assert _bindrow(s, uid).status == "pending"


def test_expired_code_voids(uid):
    """10 分钟时限（F-34①）：过期码哪怕数字对也拒，行翻 invalid"""
    with SessionLocal() as s:
        code = gen_bind_code(s, uid)
        s.execute(text("UPDATE qq_bindings SET code_expires_at = :p WHERE user_id = :u"),
                  {"p": datetime.now(timezone.utc) - timedelta(minutes=1), "u": uid})
        s.commit()
        assert "过期" in handle_qq_event(s, "20003", code)
        assert _bindrow(s, uid).status == "invalid"


def test_one_qq_one_master(uid):
    """一号一主（F-34②）：已绑给他人的 QQ，休想被别户的码拐走"""
    with SessionLocal() as s:
        other = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_qq_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        try:
            _bind(s, other, "30004")                      # QQ 先认了别的主
            code = gen_bind_code(s, uid)                  # 本户拿着活码来抢
            assert "已经绑定" in handle_qq_event(s, "30004", code)
            r = _bindrow(s, uid)
            assert r.status == "pending"                  # 抢不动：本户行纹丝未动
            # 正路：原账号网页重发=旧绑定即失效，QQ 才换新主
            gen_bind_code(s, other)
            assert "绑定成功" in handle_qq_event(s, "30004", code)
            assert _bindrow(s, uid).status == "bound"
        finally:
            s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})
            s.commit()


def test_guide_zero_token(uid):
    """未绑的普通话：只回指引、零 token 零会话——生面孔烧不动电厂的电"""
    with SessionLocal() as s:
        assert handle_qq_event(s, "40005", "今天有什么安排") == GUIDE
        assert s.scalar(text("SELECT count(*) FROM conversations WHERE user_id = :u"),
                        {"u": uid}) == 0
        assert s.scalar(text("SELECT count(*) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 0


def test_qq_split_web_same_brain_and_quota(uid):
    """分家与同源（D23 甲核心）：QQ/网页各一条会话、互不串道；
    共一颗心脏（answer_turn 落两句+流水）、共一份配额闸。"""
    with SessionLocal() as s:
        _bind(s, uid, "50006")
        out = handle_qq_event(s, "50006", "帮我看看今天", chat_fn=_chat)
        assert "收到" in out
        convs = s.execute(text(
            "SELECT channel, title FROM conversations WHERE user_id = :u"),
            {"u": uid}).all()
        assert [(c.channel, c.title) for c in convs] == [("qq", "QQ 对话")]
        assert s.scalar(text(
            "SELECT sum(tokens) FROM usage_logs WHERE user_id = :u"), {"u": uid}) == 15
        # 网页腿另开一摊，捞不到 QQ 的字
        answer_turn(s, uid, "网页这边说句", chat_fn=_chat)
        web_txts = [r[0] for r in s.execute(text(
            "SELECT m.content FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND c.channel = 'web'"),
            {"u": uid}).all()]
        assert "帮我看看今天" not in web_txts and "网页这边说句" in web_txts
        # 配额共闸：账塞满后 QQ 腿与网页腿同拒（PRD 636 多端共一份）
        s.execute(text("INSERT INTO usage_logs (user_id, day, tokens, created_at) "
                       "VALUES (:u, :d, :t, now())"),
                  {"u": uid, "d": TODAY, "t": DAILY_QUOTA})
        s.commit()
        assert "预算用完" in handle_qq_event(s, "50006", "还在吗", chat_fn=_chat)
        assert s.scalar(text(
            "SELECT count(*) FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND c.channel = 'qq'"),
            {"u": uid}) == 2                              # 拒的不记账（半句不落库）


def test_push_leg_three_states(uid, monkeypatch):
    """推送腿三态（D26 甲）：没绑 NULL；绑了推败 fail→窗内只重试推不再发消息→ok"""
    calls = []
    monkeypatch.setattr(qqmod, "push_via_onebot", lambda qq, txt: calls.append(qq) or False)
    with SessionLocal() as s:
        _setup(s, uid)
        _activated(s, uid)
        set_remind_time({"time": "20:00"}, _ctx(s, uid))
    assert _tick(uid, 20, 0) == 1                         # 未绑户：不推
    with SessionLocal() as s:
        assert s.scalar(text(
            "SELECT push_state FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND m.remind_on = :d"),
            {"u": uid, "d": TODAY}) is None
        s.execute(text("DELETE FROM messages WHERE remind_on IS NOT NULL "
                       "AND conversation_id IN (SELECT id FROM conversations "
                       "WHERE user_id = :u)"), {"u": uid})   # 摘戳只摘本户，重演绑定版
        _bind(s, uid, "60007")
        s.commit()
    assert _tick(uid, 20, 0) == 1                         # 绑定户：推了（假件装死）
    with SessionLocal() as s:
        assert s.scalar(text(
            "SELECT push_state FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND m.remind_on = :d"),
            {"u": uid, "d": TODAY}) == "fail"
        assert calls == ["60007"]
    monkeypatch.setattr(qqmod, "push_via_onebot", lambda qq, txt: calls.append(qq) or True)
    assert run_reminder_tick(datetime.combine(TODAY, time(20, 10)), only={uid}) == 0   # 只补推，不发
    assert calls == ["60007", "60007"]
    with SessionLocal() as s:
        assert s.scalar(text(
            "SELECT push_state FROM messages m JOIN conversations c "
            "ON m.conversation_id = c.id WHERE c.user_id = :u AND m.remind_on = :d"),
            {"u": uid, "d": TODAY}) == "ok"
        assert len(_reminders(s, uid)) == 1               # 重试绝不再发第二条


def test_binding_endpoint_carries_bot_number(uid, monkeypatch):
    """D65 指路契约：binding 三态恒带 bot_number——env 有号带回、没配回 None
    （前端据此让指路段隐身，页面永不编造账上没有的号）。号只记 compose 一处，
    测试用假号钉形状，不把真号抄进第二份文件。"""
    from types import SimpleNamespace
    from backend.main import qq_binding
    monkeypatch.setenv("BOT_QQ", "99999999")
    d = qq_binding(SimpleNamespace(id=uid))
    assert d["status"] == "none" and d["bot_number"] == "99999999"
    with SessionLocal() as s:
        code = gen_bind_code(s, uid)
        assert "绑定成功" in handle_qq_event(s, "70008", code)      # 绑成
    monkeypatch.delenv("BOT_QQ", raising=False)
    d = qq_binding(SimpleNamespace(id=uid))
    assert d["status"] == "bound" and d["qq_number"] == "70008"
    assert d["bot_number"] is None                                  # 没号=None 不编造


def test_to_plain_strips_markdown_for_qq():
    """通道整形（S6 真机：QQ 私聊不渲染 MD，星号糊脸）：语法符号剥光、信息不丢、幂等。"""
    md = ("## 今日计划\n- **资料分析** 30 分钟\n1. 复盘`增长率`公式\n"
          "> 详见[错题本](http://x.cn/a)\n| 项 | 时长 |\n| --- | --- |\n| 言语 | 20 分 |\n"
          "```\ncode()\n```\n**完成**就*回我*。")
    out = qqmod.to_plain(md)
    for sym in ("##", "*", "`", "> ", "|", "---", "```", "[", "]("):
        assert sym not in out, f"语法符号残留：{sym}"
    # 信息一字不丢（只脱衣服不丢肉）
    assert "今日计划" in out and "资料分析" in out and "·" in out
    assert "错题本：http://x.cn/a" in out and "增长率" in out
    assert "完成就回我" in out and "code()" in out
    # 幂等：纯文本进=原样出（提醒模板走这道闸零伤害）
    plain = "今天没排任务——是休息日就养足精神。"
    assert qqmod.to_plain(plain) == plain
