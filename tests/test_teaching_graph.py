# ============================================================
# S9·W5 教学状态图离线回归（teaching_graph.py 六节点 + build_graph 回环）
# 断言主线：安全闸拦下与每轮清零、检索腿出处同形与缺口账、诊断腿宽容解析、
# generate 流事件转 custom、策略话术注入（转教师/无料如实说）、verify 轮数
# 机关（跨轮续存+懂清+拦下不烧轮）、检查点三钉（DSN 剥前缀/失败永久静默）、
# 末态 JSON 可序列化。
# 全假件注入（chat_once/chat_stream/search/record_gap/get_stream_writer）——
# 零真网络零真烧钱；回环用 InMemorySaver 验（PostgresSaver 归真机验收）。
# ============================================================
import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend import db as dbmod
from backend import teaching_graph as tg
from backend.teaching_graph import build_graph, checkpoint_dsn, make_nodes
from backend.teaching_strategies import HANDOFF, SOCRATIC, STRATEGY_CN


def _st(**over):
    """基线教学态（一条干净的教学问句），测试按节点逐个开旗。"""
    base = {"user_text": "基期量怎么算", "user_id": 1, "channel": "web",
            "system": "你是备考教练", "model": "deepseek-flash",
            "history": [{"role": "user", "content": "你好"}]}
    base.update(over)
    return base


def _boom(*a, **k):
    raise AssertionError("不该被调用的腿被调用了")


def _install_search(monkeypatch, results=(), top_vec=None):
    seen = {}
    def fake(session, query, user_id, top_k=5):
        seen.update(query=query, user_id=user_id, top_k=top_k)
        return {"results": list(results), "degraded": None, "top_vec": top_vec}
    monkeypatch.setattr(tg, "search", fake)
    return seen


def _spy_gaps(monkeypatch):
    rows = []
    monkeypatch.setattr(tg, "record_gap",
                        lambda uid, q, tv, ch="web": rows.append((uid, q, tv, ch)))
    return rows


def _stream(reply="我们一步步来", p=100, c=50):
    """替换 chat_stream：两 delta + 收尾 message（与电厂事件形状一字不差）。"""
    box = {}
    def fn(msgs, tools=None, model=None):
        box["msgs"] = msgs; box["tools"] = tools; box["model"] = model
        yield ("delta", reply[:2])
        yield ("delta", reply[2:])
        yield ("message", {"role": "assistant", "content": reply}, p, c)
    return fn, box


@pytest.fixture()
def frames(monkeypatch):
    """接住 get_stream_writer——节点直调测试里 writer 的替身收集器。"""
    got = []
    monkeypatch.setattr(tg, "get_stream_writer", lambda: got.append)
    return got


@pytest.fixture()
def wired(monkeypatch):
    """整图假腿接线：检索恒有料（达标分不进缺口账）、诊断恒「未懂」（可翻旗）、
    生成恒两帧。返回旗盒供测改判词。"""
    flag = {"understood": False}
    _install_search(monkeypatch, top_vec=0.9, results=[
        {"id": 11, "material_id": 3, "title": "讲义A", "seq": 2,
         "content": "基期量=现期量÷(1+增长率)"}])
    _spy_gaps(monkeypatch)
    def diag(msgs, tools=None, model=None):
        return ({"role": "assistant",
                 "content": json.dumps({"understood": flag["understood"]})}, 10, 4)
    monkeypatch.setattr(tg, "chat_once", diag)
    fn, _ = _stream()
    monkeypatch.setattr(tg, "chat_stream", fn)
    return flag


def _run(g, st, cfg):
    final, deltas = None, []
    for kind, payload in g.stream(st, config=cfg, stream_mode=["custom", "values"]):
        if kind == "custom":
            deltas.append(payload["delta"])
        else:
            final = payload
    return final, deltas


# ── 检查点钉①：DSN 剥方言前缀（2 例）──

def test_dsn_strips_dialect(monkeypatch):
    monkeypatch.setattr(dbmod, "DATABASE_URL",
                        "postgresql+psycopg://z:p@db:5432/bankao")
    assert checkpoint_dsn() == "postgresql://z:p@db:5432/bankao"


def test_dsn_plain_untouched(monkeypatch):
    monkeypatch.setattr(dbmod, "DATABASE_URL", "postgresql://z:p@db:5432/bankao")
    assert checkpoint_dsn() == "postgresql://z:p@db:5432/bankao"


# ── 节点一 safety：闸与每轮清零（4 例）──

def test_safety_block_sets_fixed_reply():
    out = make_nodes()["safety"](_st(user_text="活着好累，不想活了"))
    assert out["stop_reason"] == "safety" and "12355" in out["reply"]


def test_safety_clean_pass_resets_flags():
    out = make_nodes()["safety"](_st(stop_reason="safety", handoff=True))
    assert out["stop_reason"] is None and out["handoff"] is False


def test_safety_zeroes_prev_round_bill():
    """上轮账单不清零，本轮终值就是滚存数——三本账没法对。"""
    out = make_nodes()["safety"](_st(ptok=120, ctok=53))
    assert out["ptok"] == -120 and out["ctok"] == -53


def test_safety_first_round_no_prev_bill():
    out = make_nodes()["safety"](_st())
    assert out["ptok"] == 0 and out["ctok"] == 0


# ── 节点三 retrieve：出处同形与缺口账两写点（5 例）──

def test_retrieve_citations_and_ref_numbering(monkeypatch):
    seen = _install_search(monkeypatch, top_vec=0.9, results=[
        {"id": 11, "material_id": 3, "title": "讲义A", "seq": 2, "content": "一"},
        {"id": 12, "material_id": 3, "title": "讲义A", "seq": 5, "content": "二"}])
    gaps = _spy_gaps(monkeypatch)
    out = make_nodes(session=object())["retrieve"](_st())
    # 乙案钉（D82 乙，2026-10-18 评测裁决）：教学轨 top_k=3——甲案试 2 时
    # g23 答案块（排第 3）进不了桌、命中率跌一分，回 3 零掉分；票面归票闸管
    assert seen["top_k"] == 3
    assert [m["ref"] for m in out["knowledge"]] == [1, 2]
    # 出处账与 tools.search_materials 同形契约 + D79 甲案票面带 ref 编号：
    assert out["citations"][0] == {"chunk_id": 11, "material_id": 3,
                                   "title": "讲义A", "seq": 2, "ref": 1}
    assert gaps == []   # 达标分不落账


def test_retrieve_blocked_skips_all(monkeypatch):
    """安全拦下的句子不进检索更不进缺口账——「不想活了」不许成为知识缺口。"""
    monkeypatch.setattr(tg, "search", _boom)
    monkeypatch.setattr(tg, "record_gap", _boom)
    assert make_nodes()["retrieve"](_st(stop_reason="safety")) == {}


def test_retrieve_zero_hit_writes_gap(monkeypatch):
    _install_search(monkeypatch)
    gaps = _spy_gaps(monkeypatch)
    make_nodes(session=object())["retrieve"](_st())
    assert gaps == [(1, "基期量怎么算", None, "web")]


def test_retrieve_weak_hit_writes_gap(monkeypatch):
    _install_search(monkeypatch, top_vec=0.45, results=[
        {"id": 11, "material_id": 3, "title": "讲义A", "seq": 2, "content": "一"}])
    gaps = _spy_gaps(monkeypatch)
    make_nodes(session=object())["retrieve"](_st())
    assert gaps == [(1, "基期量怎么算", 0.45, "web")]


def test_retrieve_channel_carried(monkeypatch):
    _install_search(monkeypatch)
    gaps = _spy_gaps(monkeypatch)
    make_nodes(session=object())["retrieve"](_st(channel="qq"))
    assert gaps[0][3] == "qq"


# ── 节点四 diagnose：宽容解析（3 例）──

def test_diagnose_parses_fenced_json(monkeypatch):
    box = {}
    def fn(msgs, tools=None, model=None):
        box.update(msgs=msgs, tools=tools, model=model)
        return ({"role": "assistant",
                 "content": "```json\n{\"off_topic\": true, \"understood\": null}\n```"},
                40, 8)
    monkeypatch.setattr(tg, "chat_once", fn)
    out = make_nodes()["diagnose"](_st())
    assert out["diagnosis"] == {"off_topic": True, "understood": None}
    assert out["ptok"] == 40 and out["ctok"] == 8
    assert box["tools"] is None and box["model"] == "deepseek-flash"
    assert "基期量怎么算" in box["msgs"][1]["content"]


def test_diagnose_garbage_tolerated(monkeypatch):
    monkeypatch.setattr(tg, "chat_once",
                        lambda *a, **k: ({"role": "assistant", "content": "嗯我想想"}, 1, 1))
    assert make_nodes()["diagnose"](_st())["diagnosis"] == {}


def test_diagnose_blocked_skips_model(monkeypatch):
    monkeypatch.setattr(tg, "chat_once", _boom)
    assert make_nodes()["diagnose"](_st(stop_reason="safety")) == {}


# ── 节点五 generate：流转换与话术注入（4 例）──

def test_generate_streams_deltas_and_bills(monkeypatch, frames):
    fn, box = _stream(reply="基期量，先看现期量")
    monkeypatch.setattr(tg, "chat_stream", fn)
    out = make_nodes()["generate"](_st(
        knowledge=[{"ref": 1, "title": "讲义A", "seq": 2, "content": "公式在此"}]))
    assert out["reply"] == "基期量，先看现期量"
    assert out["ptok"] == 100 and out["ctok"] == 50
    assert "".join(f["delta"] for f in frames) == out["reply"]   # 一字不少往外递
    sys = box["msgs"][0]["content"]
    assert "五条铁律" in sys and "公式在此" in sys and "[1]" in sys
    # 甲案钉（2026-10-11 用户拍板治「54 秒长嘴」）：话长上限 + 禁伪调用标签
    assert "不超过三句" in sys and "伪调用" in sys
    assert box["msgs"][-1]["content"] == "基期量怎么算"


def test_generate_blocked_emits_one_delta_no_model(monkeypatch, frames):
    """拦下的固定话术也走 delta 帧——协议不发明新帧型，整段当一帧发。"""
    monkeypatch.setattr(tg, "chat_stream", _boom)
    out = make_nodes()["generate"](
        _st(stop_reason="safety", reply="生命最要紧，拨打 12355"))
    assert frames == [{"delta": "生命最要紧，拨打 12355"}]
    assert out == {}


def test_generate_handoff_prompt_after_five_rounds(monkeypatch, frames):
    fn, box = _stream()
    monkeypatch.setattr(tg, "chat_stream", fn)
    out = make_nodes()["generate"](_st(round_no=5))
    assert out["strategy"] == HANDOFF
    assert STRATEGY_CN[HANDOFF] in box["msgs"][0]["content"]   # 转教师话术钉进提示词


def test_generate_no_material_honesty_note(monkeypatch, frames):
    fn, box = _stream()
    monkeypatch.setattr(tg, "chat_stream", fn)
    make_nodes()["generate"](_st(knowledge=[]))
    assert "暂时没找到" in box["msgs"][0]["content"]   # 不许编出处


# ── 节点六 verify：轮数机关（4 例）──

def test_verify_not_understood_bumps_round():
    out = make_nodes()["verify"](_st(strategy=SOCRATIC, diagnosis={"understood": False}))
    assert out == {"understood": False, "round_no": 1}


def test_verify_understood_resets_round():
    """负值冲账：add 通道里 -3 就是清零——懂一轮，回环从头数。"""
    out = make_nodes()["verify"](_st(round_no=3, diagnosis={"understood": True}))
    assert out == {"understood": True, "round_no": -3}


def test_verify_handoff_flags():
    out = make_nodes()["verify"](_st(strategy=HANDOFF))
    assert out == {"handoff": True, "understood": False}   # 不再叠轮数


def test_verify_blocked_not_a_round():
    out = make_nodes()["verify"](_st(stop_reason="safety", diagnosis={"understood": False}))
    assert out == {"understood": None}


# ── 整图：回环跨轮（检查点=续存机关，4 例）──

def test_graph_round_trip_carry_and_reset(wired):
    """连问三样事：轮数跨轮续存、每轮账单清零、懂一轮归零——回环本体。"""
    g = build_graph(InMemorySaver(), session=object())
    cfg = {"configurable": {"thread_id": "conv:77"}}
    f1, d1 = _run(g, _st(), cfg)
    assert f1["round_no"] == 1
    assert f1["ptok"] == 110 and f1["ctok"] == 54        # 10(诊断)+100(生成)
    assert "".join(d1) == f1["reply"]
    f2, _ = _run(g, _st(), cfg)
    assert f2["round_no"] == 2       # 检查点续来——上轮的「未懂」这轮记得
    assert f2["ptok"] == 110         # 不是 220：每轮清零，账单=本轮数
    wired["understood"] = True
    f3, _ = _run(g, _st(), cfg)
    assert f3["round_no"] == 0 and f3["understood"] is True


def test_graph_five_rounds_then_handoff(wired):
    """施工图验收项复刻：连问六轮未懂→转教师话术（第五轮未懂落账后触发）。"""
    g = build_graph(InMemorySaver(), session=object())
    cfg = {"configurable": {"thread_id": "conv:79"}}
    for _ in range(5):
        f, _ = _run(g, _st(), cfg)
    assert f["round_no"] == 5 and f["handoff"] is False
    f2, _ = _run(g, _st(), cfg)
    assert f2["strategy"] == HANDOFF and f2["handoff"] is True


def test_graph_no_checkpointer_degrades(wired):
    """钉③的降级面：无检查点图照跑，只是每条消息轮数都从零起——教学不断。"""
    g = build_graph(None, session=object())
    for _ in range(6):
        f, _ = _run(g, _st(), {"configurable": {"thread_id": "x"}})
    assert f["round_no"] == 1          # 永远第一轮：续不上，但能跑
    assert f["strategy"] is not HANDOFF


def test_graph_final_state_json_serializable(wired):
    """检查点存盘资格：末态必须全 JSON 可序列化（活对象塞不进线程状态）。"""
    g = build_graph(InMemorySaver(), session=object())
    f, _ = _run(g, _st(), {"configurable": {"thread_id": "conv:78"}})
    json.dumps(dict(f), ensure_ascii=False)


# ── 检查点钉③：建池失败永久静默（1 例）──

def test_get_saver_failure_stays_silent(monkeypatch):
    """DSN 炸了=降级不重试（防重试风暴）；恢复原状不污染其他用例。"""
    monkeypatch.setattr(tg, "_saver", None)
    monkeypatch.setattr(tg, "_saver_dead", False)
    def boom():
        raise RuntimeError("DSN 炸了")
    monkeypatch.setattr(tg, "checkpoint_dsn", boom)
    assert tg.get_saver() is None
    assert tg._saver_dead is True
    assert tg.get_saver() is None   # 第二次不再尝试
