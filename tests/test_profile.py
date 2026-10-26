# ============================================================
# S8 · D61 甲 设置页人设接真腿离线单测（命名/人设/提醒一页四账，2026-09-11 拍板）
# 断言主线：
#   ①端点读写往返+字段级语义（None=没改、空串=清账）+脏值拦在落账前；
#   ②_system_for 注入分段：strict/buddy/custom 各有段、senior 与无行零注入
#     （无行=行为与旧版逐字相同——「默认不扰动」形状例）；
#   ③两路一本账：页面写的与聊天工具写的是同一列（agent_settings 单表真源）。
# 铁律：全程假件与直调，不碰任何真网络。端点直传 SimpleNamespace 绕 Depends 家法沿用。
# ============================================================
import pytest
from fastapi import HTTPException
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import ProfileIn, get_profile, set_profile
from backend.orchestrator import _system_for


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_pf_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 级联带走 settings 行
        s.commit()


def _who(u):
    return type("U", (), {"id": u})()   # 绕 Depends 的假用户（SimpleNamespace 同族先例）


# ── 账的形状：无行=全默认 ──

def test_get_no_row_all_defaults(uid):
    """从没开过设置页的户：persona 读侧兜 senior、其余 None——前端据此显示默认态。"""
    d = get_profile(_who(uid))
    assert d["name"] is None and d["persona"] == "senior"
    assert d["custom_prompt"] is None and d["remind_time"] is None


def test_post_roundtrip_inserts_row(uid):
    """第一次保存走 INSERT（upsert 家法）：四本账存得进、读得出。"""
    set_profile(ProfileIn(name="小考", persona="strict",
                          custom_prompt=None, remind_time="20:15"), _who(uid))
    d = get_profile(_who(uid))
    assert d["name"] == "小考" and d["persona"] == "strict" and d["remind_time"] == "20:15"


def test_post_partial_and_clear(uid):
    """字段级语义：没给的列不动（persona 保持 strict）；空串=清账写回 NULL。"""
    set_profile(ProfileIn(name="小考", persona="strict"), _who(uid))
    set_profile(ProfileIn(name="", remind_time="07:30"), _who(uid))   # name 清空、加提醒
    d = get_profile(_who(uid))
    assert d["name"] is None                 # 空串=清
    assert d["persona"] == "strict"          # 没提=不动
    assert d["remind_time"] == "07:30"


# ── 校验拦在落账前 ──

def test_post_rejects_dirty_values(uid):
    cases = [
        (ProfileIn(persona="mood"), "四种"),          # 野人设
        (ProfileIn(name="超长的名字超过八个字了"), "8 个字"),   # 名超长
        (ProfileIn(custom_prompt="哈" * 501), "500"),  # 描述超长
        (ProfileIn(remind_time="25:00"), "HH:MM"),     # 怪时点
        (ProfileIn(), "没有要保存"),                    # 空请求
    ]
    for body, frag in cases:
        with pytest.raises(HTTPException) as e:
            set_profile(body, _who(uid))
        assert e.value.status_code == 422 and frag in e.value.detail
    # 全被拦=库里连行都没留
    assert get_profile(_who(uid))["persona"] == "senior"


# ── 注入段：人设只改腔调，senior/无行零扰动 ──

def _sys(u):
    with SessionLocal() as s:
        return _system_for(u, s)


def test_system_inject_strict_buddy(uid):
    base = _sys(uid)
    assert "【人设" not in base          # 默认（无行/senior 同义）零注入——旧版行为逐字保持
    set_profile(ProfileIn(persona="strict"), _who(uid))
    s1 = _sys(uid)
    assert "严师型" in s1 and "只改说话的软硬" in s1
    set_profile(ProfileIn(persona="buddy"), _who(uid))
    assert "搭子" in _sys(uid)


def test_system_inject_custom_with_bottom_line(uid):
    """custom 注入用户原文，但底线句同段随行：代写/辱骂/翻账都封死（F-07 注记兑现）。"""
    set_profile(ProfileIn(persona="custom", custom_prompt="像老战友一样直话短说"), _who(uid))
    got = _sys(uid)
    assert "像老战友一样直话短说" in got
    assert "不代写申论" in got and "账赢" in got
    # custom 但没写描述=没有可注入的腔调，回落零扰动
    set_profile(ProfileIn(persona="custom", custom_prompt=""), _who(uid))
    assert "【人设" not in _sys(uid)


# ── 两路一本账：页面与聊天写同列 ──

def test_page_and_chat_share_one_ledger(uid):
    """页面存的名字/时点，落的就是聊天工具 set_agent_name/set_remind_time 的账列——
    下一轮 _system_for 读同一本账，两路无第二份。"""
    set_profile(ProfileIn(name="阿章", remind_time="21:00"), _who(uid))
    with SessionLocal() as s:
        row = s.execute(text(
            "SELECT agent_name, remind_time FROM agent_settings WHERE user_id = :u"),
            {"u": uid}).first()
    assert (row[0], row[1]) == ("阿章", "21:00")
    assert "阿章" in _sys(uid)            # 自称设定段即刻反映
