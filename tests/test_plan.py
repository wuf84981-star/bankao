# ============================================================
# S5 第一刀离线单测：计划硬校验器（V1~V6）+ 生成→草案→激活往返
# 核心断言=确定性墙：坏计划一行不落库；好计划先 draft，用户点头才 active；
# 同考试至多一个 active（部分唯一闸）；计划账进组装器第五本。
# 校验器段是纯函数直喂坏 JSON——零 DB 零模型（D13 独立模块的红利）。
# ============================================================
import json
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.main import _system_for
from backend.plan_validator import parse_shape, validate_plan
from backend.tools import save_exam_profile, update_mastery, generate_plan, activate_plan, \
    report_check_in, adjust_plan_item, edit_plan_item

TODAY = date.today()
EXAM = TODAY + timedelta(days=40)          # 距考 40 天：前 25 学习段+后 15 冲刺段
NODE = 123                                  # 纯函数段的假节点 id


def _good_days(exam_date=EXAM, node_id=NODE, est=60):
    """全过样例：今天→考前一日逐日无缺；科目隔天轮换（V5）；
    最后 15 天全是 mock（V4）；est 60 分（V2 内）"""
    days, d, i = [], TODAY, 0
    while d < exam_date:
        sprint = (exam_date - d).days <= 15
        days.append({"date": str(d), "items": [{
            "kp_ref": node_id, "subject": "资料分析" if i % 2 else "言语理解",
            "task": "真题一套并复盘" if sprint else "刷20题并复盘",
            "est_minutes": est, "kind": "mock" if sprint else "exercise"}]})
        d += timedelta(days=1)
        i += 1
    return days


def _vp(days, **over):
    """parse+validate 一把梭，over 覆盖地面真值参数"""
    parsed, errs = parse_shape(days)
    assert errs is None, errs
    kw = dict(exam_date=EXAM, weekday_min=120, weekend_min=240, reserved_daily=0,
              node_ids={NODE}, levels={NODE: "一般掌握"}, today=TODAY)
    kw.update(over)
    return validate_plan(parsed, **kw)


# ── 纯函数段：六条规则各自要拦得住 ──

def test_v_shape_rejects_garbage():
    parsed, errs = parse_shape("不是数组")
    assert parsed is None and errs
    _, errs = parse_shape([{"date": "2026-99-99", "items": []}])
    assert any("YYYY-MM-DD" in e for e in errs)


def test_v_all_green_sample_passes():
    assert _vp(_good_days()) == []


def test_v1_gap_and_edge_rejected():
    days = _good_days()
    del days[len(days) // 2]                       # 中间抠一天
    assert any(e.startswith("V1") for e in _vp(days))


def test_v2_over_and_undeclared_rejected():
    assert any(e.startswith("V2") for e in _vp(_good_days(est=300)))          # 超 120×1.2
    errs = _vp(_good_days(), weekday_min=None, weekend_min=None)
    assert any("还没声明" in e for e in errs)                                  # 未声明拒生成


def test_v3_fabricated_node_rejected():
    assert any(e.startswith("V3") for e in _vp(_good_days(), node_ids=set()))


def test_v4_missing_or_short_sprint_rejected():
    days = _good_days()
    for day in days:                              # 全拆掉冲刺标记
        day["items"][0]["kind"] = "exercise"
    assert any("没排冲刺段" in e for e in _vp(days))
    late = _good_days(exam_date=EXAM)
    for day in late:                              # 冲刺只剩考前 5 天
        sprint = (EXAM - date.fromisoformat(day["date"])).days <= 5
        day["items"][0]["kind"] = "mock" if sprint else "exercise"
    assert any("不在 14~35" in e for e in _vp(late))


def test_v5_same_subject_run_rejected():
    days = _good_days()
    for day in days:                              # 天天同一科目高负载
        day["items"][0]["subject"] = "资料分析"
    assert any(e.startswith("V5") for e in _vp(days))


def test_v6_review_unlearned_rejected():
    days = _good_days()
    days[10]["items"][0] = {"kp_ref": NODE, "subject": "言语理解",
                            "task": "复盘错题", "est_minutes": 60, "kind": "review"}   # 科目沿用当日原值，别撞 V5
    assert any(e.startswith("V6") for e in _vp(days, levels={NODE: "未接触"}))
    assert _vp(days, levels={NODE: "一般掌握"}) == []     # 学过了就放行


# ── DB 段：落库只发生在"全过"之后，生效只发生在"点头"之后 ──

@pytest.fixture()
def uid():
    with SessionLocal() as s:
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_plan_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})
        s.commit()


def _ctx(s, u):
    return {"user_id": u, "session": s, "citations": []}


def _setup(s, u):
    """真值三件套：主考档案（含每日时长）+ 一个已学过的知识点节点
    （幂等：节点撞 uq_knowledge_nodes_root 就回收现成的——二刀测试要套两遍 setup）"""
    save_exam_profile({"exam_type": "公务员考试", "exam_date": str(EXAM),
                       "weekday_minutes": 120, "weekend_minutes": 240}, _ctx(s, u))
    s.commit()
    node = s.scalar(text("SELECT id FROM knowledge_nodes WHERE user_id = :u AND name = '基期量'"),
                    {"u": u})
    if not node:   # 裸 SQL 不吃 ORM default：sort 必手写（S4 教训第三次上班）
        node = s.scalar(text(
            "INSERT INTO knowledge_nodes (user_id, exam_type, subject, name, source, sort, "
            "created_at) VALUES (:u, '公务员考试', '资料分析', '基期量', 'user_edit', 0, "
            "now()) RETURNING id"), {"u": u})
    s.execute(text(
        "INSERT INTO knowledge_mastery (user_id, exam_type, subject, kp_ref, level, confidence) "
        "VALUES (:u, '公务员考试', '资料分析', :k, '一般掌握', 70) "
        "ON CONFLICT DO NOTHING"), {"u": u, "k": node})   # 幂等套两遍不炸 UNIQUE 三键
    s.commit()
    return node


def test_generate_draft_then_activate_roundtrip(uid):
    """完整往返：草案入库未生效→用户点头激活→重生成旧版归档 version+1"""
    with SessionLocal() as s:
        node = _setup(s, uid)
        days = json.loads(json.dumps(_good_days()).replace(str(NODE), str(node)))
        r = json.loads(generate_plan({"days": days}, _ctx(s, uid)))
        pid = r["plan_id"]
        assert r["状态"].startswith("草案") and r["距考试"] == 40
        assert s.scalar(text("SELECT status FROM plans WHERE id = :p"), {"p": pid}) == "draft"
        assert s.scalar(text("SELECT count(*) FROM plan_items WHERE plan_id = :p"),
                        {"p": pid}) == len(days)                      # 逐日全落
        a = activate_plan({"plan_id": pid}, _ctx(s, uid))
        assert "已生效" in a and "今日（" in a
        r2 = json.loads(generate_plan({"days": days}, _ctx(s, uid)))
        assert r2["状态"] == "草案 v2（未生效）"
        assert s.scalar(text("SELECT status FROM plans WHERE id = :p"), {"p": pid}) == "archived"
        activate_plan({"plan_id": r2["plan_id"]}, _ctx(s, uid))
        assert s.scalar(text("SELECT count(*) FROM plans WHERE user_id = :u AND status = 'active'"),
                        {"u": uid}) == 1
        assert s.scalar(text("SELECT count(*) FROM plan_change_logs WHERE user_id = :u"),
                        {"u": uid}) == 2                              # 两次激活都留痕


def test_rejected_plan_leaves_no_rows(uid):
    """校验不过=一行不落（快速失败不留行，S3 入仓同款纪律）：
    V3 拦编造 kp_ref；未声明时长 V2 拦在门口"""
    with SessionLocal() as s:
        _setup(s, uid)
        r = generate_plan({"days": _good_days(node_id=999999)}, _ctx(s, uid))
        assert "校验未通过" in r and "V3" in r
        assert s.scalar(text("SELECT count(*) FROM plans WHERE user_id = :u"), {"u": uid}) == 0
        s.execute(text("UPDATE exam_profiles SET weekday_minutes=NULL, weekend_minutes=NULL "
                       "WHERE user_id = :u"), {"u": uid})
        s.commit()
        r2 = generate_plan({"days": json.loads(json.dumps(_good_days()))}, _ctx(s, uid))
        assert "还没声明" in r2


def test_active_single_plank_gate(uid):
    """部分唯一闸真炸：同考试硬插俩 active 必须 IntegrityError（户口制闸形）"""
    with SessionLocal() as s:
        _setup(s, uid)
        s.execute(text("INSERT INTO plans (user_id, exam_type, start_date, sprint_start_date, "
                       "status, version, created_at) VALUES (:u, '公务员考试', :a, :b, "
                       "'active', 1, now())"), {"u": uid, "a": TODAY, "b": EXAM - timedelta(days=15)})
        s.commit()
        with pytest.raises(Exception):
            s.execute(text("INSERT INTO plans (user_id, exam_type, start_date, "
                           "sprint_start_date, status, version, created_at) VALUES "
                           "(:u, '公务员考试', :a, :b, 'active', 2, now())"),
                      {"u": uid, "a": TODAY, "b": EXAM - timedelta(days=15)})
        s.rollback()


def test_plan_ledger_injected_and_isolated(uid):
    """第五本账：激活后今日任务进注入；无计划户拿到『没有生效计划』口径；两户不串"""
    with SessionLocal() as s:
        out = _system_for(uid, s)
        assert "【计划账·数据库真账】没有生效中的学习计划" in out
        node = _setup(s, uid)
        days = json.loads(json.dumps(_good_days()).replace(str(NODE), str(node)))
        pid = json.loads(generate_plan({"days": days}, _ctx(s, uid)))["plan_id"]
        activate_plan({"plan_id": pid}, _ctx(s, uid))
        out2 = _system_for(uid, s)
        assert "计划 v1 生效中" in out2 and "刷20题并复盘" in out2 and "距考试 40 天" in out2
        assert "刷20题并复盘" not in _system_for(uid + 10 ** 9, s)   # 幽灵户也不许看见别人账


# ── 第二刀：打卡消化 + 商量顺延（F-23/F-24，D16~D18 甲案执行体） ──

def _activated(s, u):
    """造到「计划生效」这步，返回 (plan_id, 今日首条 item id)"""
    node = _setup(s, u)
    days = json.loads(json.dumps(_good_days()).replace(str(NODE), str(node)))
    pid = json.loads(generate_plan({"days": days}, _ctx(s, u)))["plan_id"]
    activate_plan({"plan_id": pid}, _ctx(s, u))
    item = s.scalar(text("SELECT id FROM plan_items WHERE plan_id = :p AND date = :d "
                         "ORDER BY id LIMIT 1"), {"p": pid, "d": TODAY})
    return pid, item


def test_check_in_done_and_mastery_hint(uid):
    """用户亲口汇报→置 done+凭据+完成时刻；回执附涉及节点现档（只建议不自动升档）"""
    with SessionLocal() as s:
        pid, item = _activated(s, uid)
        r = report_check_in({"status": "done", "item_ids": [item],
                             "note": "用户口述：刷完20题错了3道"}, _ctx(s, uid))
        assert "打卡成功" in r and "共 1 条" in r
        assert "基期量（现档 一般掌握）" in r and "建议" in r   # D18 甲：档位素材+须点头
        row = s.execute(text("SELECT status, done_note, completed_at FROM plan_items "
                             "WHERE id = :i"), {"i": item}).first()
        assert row.status == "done" and "错" in row.done_note and row.completed_at
        assert s.scalar(text("SELECT count(*) FROM knowledge_mastery WHERE user_id = :u"),
                        {"u": uid}) == 1                          # 打卡绝不偷写掌握度（D18 甲）
        r2 = report_check_in({"status": "done", "item_ids": [item]}, _ctx(s, uid))
        assert "不在本户生效计划" in r2                            # 再打同条：已非 pending 走票闸口径


def test_check_in_gates(uid):
    """三道门：status 乱认/无生效计划/编造 id 全拒，且拒了不动账"""
    with SessionLocal() as s:
        r = report_check_in({"status": "missed"}, _ctx(s, uid))
        assert "只认 done" in r
        _setup(s, uid)                                             # 只有草案未激活
        assert "没有生效中的计划" in report_check_in({"status": "done"}, _ctx(s, uid))
        pid, item = _activated(s, uid)
        r3 = report_check_in({"status": "done", "item_ids": [item + 99999]}, _ctx(s, uid))
        assert "票闸" in r3
        assert s.scalar(text("SELECT count(*) FROM plan_items WHERE plan_id = :p "
                             "AND status != 'pending'"), {"p": pid}) == 0


def test_adjust_item_postpone(uid):
    """顺延往返：pending 条改日+留痕带快照；done 条/过去日期拒；版本不动"""
    with SessionLocal() as s:
        pid, item = _activated(s, uid)
        tomorrow = TODAY + timedelta(days=1)
        r = adjust_plan_item({"item_id": item, "new_date": str(tomorrow),
                              "reason": "今晚加班"}, _ctx(s, uid))
        assert "挪到" in r and "留痕" in r
        assert s.scalar(text("SELECT date FROM plan_items WHERE id = :i"),
                        {"i": item}) == tomorrow
        assert s.scalar(text("SELECT version FROM plans WHERE id = :p"), {"p": pid}) == 1
        snap = s.scalar(text("SELECT snapshot FROM plan_change_logs WHERE plan_id = :p "
                             "ORDER BY id DESC LIMIT 1"), {"p": pid})
        assert snap["adjust_item"] == item and snap["to"] == str(tomorrow)
        report_check_in({"date": str(tomorrow), "status": "done",
                         "item_ids": [item]}, _ctx(s, uid))       # 先变成历史
        assert "历史事实" in adjust_plan_item({"item_id": item, "new_date": str(tomorrow),
                                               "reason": "挪done条"}, _ctx(s, uid))
        assert "过去" in adjust_plan_item({"item_id": item, "new_date": "2020-01-01",
                                           "reason": "穿越"}, _ctx(s, uid))
        nxt = s.scalar(text("SELECT id FROM plan_items WHERE plan_id = :p AND date = :t "
                            "AND status = 'pending' ORDER BY id LIMIT 1"),
                       {"p": pid, "t": tomorrow})   # 明天原排的那条仍 pending，拿它验 reason 关
        assert "reason" in adjust_plan_item({"item_id": nxt, "new_date": str(tomorrow)},
                                            _ctx(s, uid))


def test_owed_yesterday_injected(uid):
    """昨日欠账进第五本账（漏卡次日提醒的原料）；无欠账不添话"""
    with SessionLocal() as s:
        pid, item = _activated(s, uid)
        out0 = _system_for(uid, s)
        assert "昨日（" not in out0                                 # 今天刚排，昨日无账
        s.execute(text("UPDATE plan_items SET date = :y WHERE id = :i"),
                  {"y": TODAY - timedelta(days=1), "i": item})
        s.commit()
        out = _system_for(uid, s)
        assert "昨日（" in out and "1 条没打卡" in out and "不自动判失败" in out


# ── 第三刀：手动改单条（F-25 · D19/D20 甲案）＋ kind 落库补账 ──

def test_kind_persisted_and_edit_roundtrip(uid):
    """D20 补账：generate 落库要见 kind；edit 改内容即时生效+留痕+done/V3 双闸"""
    with SessionLocal() as s:
        pid, item = _activated(s, uid)
        assert s.scalar(text("SELECT kind FROM plan_items WHERE id = :i"),
                        {"i": item}) == "exercise"     # 首刀欠账已还（_good_days 首条）
        r = edit_plan_item({"item_id": item, "task": "刷30题+口算专项",
                            "est_minutes": 50, "reason": "周四那条换成口算"}, _ctx(s, uid))
        assert "已即时更新 2 个字段" in r and "留痕" in r
        row = s.execute(text("SELECT task_desc, est_minutes FROM plan_items WHERE id = :i"),
                        {"i": item}).first()
        assert row.task_desc == "刷30题+口算专项" and row.est_minutes == 50
        snap = s.scalar(text("SELECT snapshot FROM plan_change_logs WHERE plan_id = :p "
                             "ORDER BY id DESC LIMIT 1"), {"p": pid})
        assert snap["from"]["est_minutes"] == 60 and snap["to"]["est_minutes"] == 50
        assert "V3 复查" in edit_plan_item({"item_id": item, "kp_ref": 999999}, _ctx(s, uid))
        report_check_in({"status": "done", "item_ids": [item]}, _ctx(s, uid))
        assert "历史事实不改内容" in edit_plan_item({"item_id": item, "task": "改历史"},
                                                    _ctx(s, uid))


def test_edit_overload_warning_force_roundtrip(uid):
    """AC②代码强制：超载改法首调不落库只回警告；force=true 才放行且快照记 warned"""
    with SessionLocal() as s:
        pid, item = _activated(s, uid)
        r = edit_plan_item({"item_id": item, "est_minutes": 400}, _ctx(s, uid))
        assert "需用户确认后才能改" in r and "超" in r
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE id = :i"),
                        {"i": item}) == 60              # 警告关=一行不落
        r2 = edit_plan_item({"item_id": item, "est_minutes": 400,
                             "force": True}, _ctx(s, uid))
        assert "警告后用户坚持" in r2
        assert s.scalar(text("SELECT est_minutes FROM plan_items WHERE id = :i"),
                        {"i": item}) == 400
        snap = s.scalar(text("SELECT snapshot FROM plan_change_logs WHERE plan_id = :p "
                             "ORDER BY id DESC LIMIT 1"), {"p": pid})
        assert snap["warned"] is True


def test_edit_sprint_squeeze_warning(uid):
    """冲刺段被挤占=第二种警告：段内 mock 条改 exercise 首调拒、force 放行"""
    with SessionLocal() as s:
        _pid, _item = _activated(s, uid)
        last = s.scalar(text("SELECT id FROM plan_items WHERE user_id = :u AND date = :d"),
                        {"u": uid, "d": EXAM - timedelta(days=1)})
        assert s.scalar(text("SELECT kind FROM plan_items WHERE id = :i"),
                        {"i": last}) == "mock"
        r = edit_plan_item({"item_id": last, "kind": "exercise"}, _ctx(s, uid))
        assert "冲刺段" in r and "挤占" in r
        assert "已即时更新" in edit_plan_item({"item_id": last, "kind": "exercise",
                                               "force": True}, _ctx(s, uid))
