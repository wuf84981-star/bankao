# ============================================================
# S7 首刀离线单测：出题与判分（F-27/28 · D29/D30 甲案）
# 核心断言：校验墙逐题判决（坏题不连坐）；生成链假电厂两轮（生成→自检）；
# 防泄题闸（回执里没有答案字段、没有答案内容、没有解析原文）；
# 库存优先=零 LLM 调用；新鲜度=近 7 天做过的问题被踢出库存；
# 判分=程序裁决+归一化（全角/空白/多可接受答案）+票闸+幂等（判过的不重判）；
# 嵌套运费单独立账 usage_logs（外层循环看不见的调用最容易漏扣）。
# 台件借 test_plan：uid 同款、_ctx/_setup 原样复用。
# ============================================================
import json

import pytest
from sqlalchemy import text

from backend.db import SessionLocal
from backend.question_validator import validate_questions
from backend.questioning import classify_error, grade_one, short_review
from backend.tools import generate_questions, grade_answer, report_question_error, \
    resolve_error_pattern, unbind_error_pattern
from test_plan import _ctx, _setup


@pytest.fixture()
def uid():
    with SessionLocal() as s:
        # 先扫上一轮没还上的借用孤儿（归还行钉在测试尾，失败轮一跳过就留尸）
        s.execute(text("DELETE FROM users WHERE username = '_quiz_t4'"))
        s.commit()
        u = s.execute(text(
            "INSERT INTO users (username, password_hash, status, created_at) "
            "VALUES ('_quiz_t', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
    yield u
    with SessionLocal() as s:
        s.execute(text("DELETE FROM users WHERE id = :u"), {"u": u})   # 两表 CASCADE 级联走
        s.commit()


def _script_chat(replies):
    """假电厂脚本机：按轮次序吐回复（与 chat_once 同构：fn(msgs[, tools]) →
    (msg_dict, prompt_tokens, completion_tokens)）。返回 (calls, fn) 供断言轮数。"""
    calls = []
    def fn(msgs, tools=None):
        calls.append(msgs)
        i = len(calls) - 1
        r = replies[i] if i < len(replies) else replies[-1]
        return ({"role": "assistant", "content": r}, 10, 5)
    return calls, fn


_GOOD_SINGLE = {"qtype": "single", "stem": "2023年A产量1000，同比增10%，基期约？",
                "options": ["A. 900", "B. 909", "C. 1100", "D. 1010"],
                "answer": "B", "analysis": "基期=现期÷(1+r)=1000÷1.1≈909。", "difficulty": "mid"}
_GOOD_FILL = {"qtype": "fill", "stem": "某基数 650 增长 15% 后约为多少（取整）？",
              "options": [], "answer": "748", "analysis": "650×1.15=747.5≈748。",
              "difficulty": "easy", "kp_ref": 999}
_GOOD_MULTI = {"qtype": "multi", "stem": "下列哪些属于基期量的常见求法？",
               "options": ["A. 现期÷(1+r)", "B. 现期−增长量", "C. 现期×(1+r)", "D. 增长量÷r"],
               "answer": "ab", "analysis": "C 是现期公式。", "difficulty": "mid"}
_GOOD_SHORT = {"qtype": "short", "stem": "简述基期量与增长量的关系。",
               "options": [], "answer": "现期=基期+增长量｜基期=现期−增长量",
               "analysis": "两式互逆。", "difficulty": "easy"}


# ── 纯函数段：校验墙与判分器（零 DB）──

def test_validate_questions_per_question_verdict():
    """逐题判决：好题规范化存活、坏题一条条点名——kp_ref 不收模型写的，程序钉真值。
    二刀 2a 后 short/multi 开闸（judge 判断题仍未开），multi 答案规范化为升序字母串。"""
    bad_qtype = {"qtype": "judge", "stem": "判断对错", "answer": "对", "analysis": "略",
                 "difficulty": "mid", "options": []}
    bad_answer = {"qtype": "single", "stem": "越界答案", "options": ["A. 1", "B. 2"],
                  "answer": "E", "analysis": "…", "difficulty": "mid"}
    bad_multi = {"qtype": "multi", "stem": "伪多选", "options": ["A. 1", "B. 2", "C. 3"],
                 "answer": "A", "analysis": "…", "difficulty": "mid"}   # 单字母多选=死
    no_analysis = {"qtype": "fill", "stem": "缺解析", "options": [], "answer": "748",
                   "analysis": "", "difficulty": "easy"}
    bad_diff = dict(_GOOD_FILL, difficulty="地狱")
    valid, errors = validate_questions(
        [dict(_GOOD_SINGLE, kp_ref=12345), bad_qtype, bad_answer, no_analysis, bad_diff,
         dict(_GOOD_FILL), dict(_GOOD_MULTI), dict(_GOOD_SHORT), bad_multi], node_id=77)
    assert len(valid) == 4 and len(errors) == 5
    assert valid[0]["kp_ref"] == 77 and valid[2]["kp_ref"] == 77   # 真值覆盖闸全员钉 77
    assert valid[0]["answer"] == "B"
    assert valid[2]["qtype"] == "multi" and valid[2]["answer"] == "AB"   # 升序规范化
    assert valid[3]["qtype"] == "short" and valid[3]["options"] == []
    assert any("judge" in e for e in errors) and any("越出选项范围" in e for e in errors)
    assert any("多选答案" in e for e in errors) and any("解析为空" in e for e in errors)
    assert any("difficulty" in e for e in errors)
    v2, e2 = validate_questions("不是数组", node_id=1)
    assert v2 == [] and e2


def test_grade_one_normalization():
    """程序判分器（二元组：对错+判语）：single 认大小写与尾巴废话；fill NFKC 归一化
    +｜多答案；multi 漏选/错选区分判语（F-28③——少选和多选是两种病）。"""
    ok, note = grade_one("single", "B", " b ")
    assert ok and note == "选项字母比对"
    assert grade_one("single", "B", "B，因为基期要除以1.1")[0]
    assert not grade_one("single", "B", "")[0] and not grade_one("single", "B", "D")[0]
    assert grade_one("fill", "748｜747.5", " ７４８ ")[0]        # 全角+空格+第一可接受答案
    assert grade_one("fill", "748｜747.5", "７４７.５")[0]        # 全角命中第二备选
    assert not grade_one("fill", "748", "615")[0] and not grade_one("fill", "748", "   ")[0]
    assert grade_one("multi", "ABC", " c a b ") == (True, "选项集合全中")
    assert grade_one("multi", "ABC", "AC") == (False, "漏选：B")
    assert grade_one("multi", "ABC", "ABCD") == (False, "错选：D")
    assert grade_one("multi", "ABC", "AD") == (False, "漏选 B/C、错选 D")
    assert grade_one("multi", "ABC", "")[0] is False


def test_short_review_enum_enforcement():
    """主观题点评腿：三档枚举程序执法（D31 同款刀法）——模型越档（自造『良』或给分数）
    一律打成『对照失败』，宁可认怂不让它自造结论。"""
    calls, fn = _script_chat([json.dumps({"verdict": "部分达标", "commentary": "漏答要点乙",
                                          "pitfall": "只背公式不审题"}, ensure_ascii=False)])
    r, p, c = short_review(fn, stem="简述…", points="要点甲｜要点乙", user_answer="答了甲")
    assert r == {"verdict": "部分达标", "commentary": "漏答要点乙", "pitfall": "只背公式不审题"}
    assert (p, c) == (10, 5) and len(calls) == 1
    calls2, fn2 = _script_chat([json.dumps({"verdict": "良（85分）", "commentary": "x",
                                            "pitfall": ""})])
    r2, _, _ = short_review(fn2, stem="s", points="p", user_answer="u")
    assert r2["verdict"] == "对照失败"


# ── DB 链段：出题 ──

def test_missing_kp_node_no_burn(uid):
    """知识点没账先拒：不建点、不出题、电厂零调用、零运费——建点是 update_mastery 的确认流。"""
    calls, fn = _script_chat(["{}"])
    with SessionLocal() as s:
        _setup(s, uid)
        out = generate_questions({"kp_name": "量与估算"}, {**_ctx(s, uid), "inner_chat_fn": fn})
        assert "没有节点" in out and "update_mastery" in out
        assert calls == []
        assert s.scalar(text("SELECT count(*) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 0


def test_generate_chain_no_leak_and_freight(uid):
    """全生成链：2 进 1 出（一道被自检枪毙）；防泄题闸；运费落账；
    questions/attempts 双落库且 attempts 是 pending。"""
    gen_reply = json.dumps({"questions": [
        _GOOD_SINGLE,
        dict(_GOOD_FILL, stem="这道自检要枪毙：题面与答案互相矛盾", answer="999")]},
        ensure_ascii=False)
    check_reply = json.dumps({"check": [{"qid_index": 0, "verdict": "pass"},
                                        {"qid_index": 1, "verdict": "drop",
                                         "reason": "重算与给定答案不符"}]})
    calls, fn = _script_chat([gen_reply, check_reply])
    with SessionLocal() as s:
        ctx = {**_ctx(s, uid), "inner_chat_fn": fn}
        _setup(s, uid)
        out = json.loads(generate_questions({"kp_name": "基期量", "count": 2}, ctx))
    assert len(calls) == 2                                  # 两段式：生成+自检都走了
    assert out["到手"] == 1
    q = out["题目"][0]
    assert set(q) == {"qid", "qtype", "难度", "题面", "选项"}  # 新题与库存题同形（键名统一）
    flat = json.dumps(out, ensure_ascii=False)
    assert '"answer"' not in flat and '"analysis"' not in flat   # 字段级防泄题
    assert "基期=现期" not in flat and "999" not in flat          # 解析原文、被弃答案都不许露
    assert "自检弃题" in flat                                     # 弃题注记如实上报
    with SessionLocal() as s:
        row = s.execute(text("SELECT id, answer, kp_ref, source, status FROM questions "
                             "WHERE user_id = :u"), {"u": uid}).first()
        assert row.answer == "B" and row.source == "llm" and row.status == "active"   # 答案只活在库里
        att = s.execute(text("SELECT user_answer FROM quiz_attempts WHERE question_id = :i"),
                        {"i": row.id}).first()
        assert att and att.user_answer is None              # 问题即建 pending（计时起点）
        assert s.scalar(text("SELECT tokens FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 30                   # 两轮 (10+5) 运费全落账


def test_stock_first_zero_llm(uid):
    """补充二程序判定：库存够=一题不生成（电厂塞个会炸的假件都轮不着）。"""
    def boom(*a, **k):
        raise AssertionError("库存充足还烧电厂=判定权旁落了")
    with SessionLocal() as s:
        node = _setup(s, uid)
        for i, (qt, ans) in enumerate([("single", "B"), ("fill", "748")]):
            s.execute(text(
                "INSERT INTO questions (user_id, exam_type, source, subject, kp_ref, qtype, "
                "difficulty, stem, options, answer, analysis, status, created_at) VALUES "
                "(:u, '公务员考试', 'uploaded', '资料分析', :k, :qt, 'mid', :st, CAST(:op AS JSONB), "
                ":ans, '解析', 'active', now())"),
                {"u": uid, "k": node, "qt": qt, "st": f"库存题{i}", "ans": ans,
                 "op": json.dumps(["A. 1", "B. 2", "C. 3", "D. 4"] if qt == "single" else [])})
        s.commit()
        out = json.loads(generate_questions({"kp_name": "基期量", "count": 2},
                                            {**_ctx(s, uid), "inner_chat_fn": boom}))
    assert out["到手"] == 2 and all(q["题面"].startswith("库存题") for q in out["题目"])
    with SessionLocal() as s:
        assert s.scalar(text("SELECT count(*) FROM quiz_attempts a JOIN questions q "
                             "ON q.id = a.question_id WHERE q.user_id = :u "
                             "AND a.user_answer IS NULL"),
                        {"u": uid}) == 2                    # 领走即挂钟：pending 行补齐


def test_freshness_excludes_recent(uid):
    """近 7 天做过的题不重出（F-27 流程）：唯一库存已被判过→缺口→生成腿上岗。"""
    gen = json.dumps({"questions": [_GOOD_SINGLE]})
    check = json.dumps({"check": [{"qid_index": 0, "verdict": "pass"}]})
    calls, fn = _script_chat([gen, check])
    with SessionLocal() as s:
        node = _setup(s, uid)
        qid = s.scalar(text(
            "INSERT INTO questions (user_id, exam_type, source, subject, kp_ref, qtype, "
            "difficulty, stem, options, answer, analysis, status, created_at) VALUES "
            "(:u, '公务员考试', 'uploaded', '资料分析', :k, 'single', 'mid', '老库存', "
            "CAST(:op AS JSONB), 'A', '解析', 'active', now()) RETURNING id"),
            {"u": uid, "k": node, "op": json.dumps(["A. 1", "B. 2"])})
        s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                       "is_correct, duration_sec, created_at) VALUES (:q, :u, 'A', true, 55, "
                       "now() - interval '2 days')"), {"q": qid, "u": uid})
        s.commit()
        out = json.loads(generate_questions({"kp_name": "基期量", "count": 1},
                                            {**_ctx(s, uid), "inner_chat_fn": fn}))
    assert len(calls) == 2 and out["到手"] == 1
    assert out["题目"][0]["题面"] == _GOOD_SINGLE["stem"]         # 出的是新题不是老库存
    assert out["题目"][0]["qid"] != qid


# ── DB 链段：判分 ──

def _seed_questions(s, u, node):
    """四道库存题（single 对路/single 错路/fill 多备选/multi 漏选路），各挂 3 分钟前的 pending 行。"""
    specs = [("single", "B", "题面甲"), ("single", "C", "题面乙"),
             ("fill", "748｜747.5", "题面丙"), ("multi", "ABD", "题面丁")]
    ids = []
    for qt, ans, st in specs:
        ids.append(s.scalar(text(
            "INSERT INTO questions (user_id, exam_type, source, subject, kp_ref, qtype, "
            "difficulty, stem, options, answer, analysis, status, created_at) VALUES "
            "(:u, '公务员考试', 'uploaded', '资料分析', :k, :qt, 'mid', :st, CAST(:op AS JSONB), "
            ":ans, '这是该露出的解析', 'active', now()) RETURNING id"),
            {"u": u, "k": node, "qt": qt, "st": st, "ans": ans,
             "op": json.dumps(["A. 900", "B. 909", "C. 1100", "D. 1010"]
                              if qt in ("single", "multi") else [])}))
        s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, created_at) "
                       "VALUES (:i, :u, now() - interval '3 minutes')"),
                  {"i": ids[-1], "u": u})
    s.commit()
    return ids


def test_qtype_forces_generation_leg(uid):
    """真机案回归（2026-09-09）：用户点名多选，qtype 约束却只执法了半截——库存路
    过滤了、生成路没把参数传进命题提示词，回炉出的全是单选。修复双保险：提示词
    钉『一律 X』进命题轮 + 程序后置闸把越型题踢掉且自曝注记。"""
    gen = json.dumps({"questions": [dict(_GOOD_MULTI), dict(_GOOD_SINGLE)]},
                     ensure_ascii=False)
    check = json.dumps({"check": [{"qid_index": 0, "verdict": "pass"},
                                  {"qid_index": 1, "verdict": "pass"}]})
    calls, fn = _script_chat([gen, check])
    with SessionLocal() as s:
        node = _setup(s, uid)
        s.execute(text("INSERT INTO questions (user_id, exam_type, source, subject, kp_ref, "
                       "qtype, difficulty, stem, options, answer, analysis, status, created_at) "
                       "VALUES (:u, '公务员考试', 'uploaded', '资料分析', :k, 'single', 'mid', "
                       "'『老单选题』', CAST(:op AS JSONB), 'B', '解析', 'active', now())"),
                   {"u": uid, "k": node, "op": json.dumps(["A. 1", "B. 2"])})
        s.commit()
        out = json.loads(generate_questions({"kp_name": "基期量", "count": 3, "qtype": "multi"},
                                            {**_ctx(s, uid), "inner_chat_fn": fn}))
    assert "qtype 一律 multi" in calls[0][-1]["content"]          # 约束真进了生成腿
    assert out["到手"] == 1 and out["题目"][0]["qtype"] == "multi"
    flat = json.dumps(out, ensure_ascii=False)
    assert "越型 1 道" in flat                                    # 后闸剔题自曝不静默
    assert "老单选题" not in flat                                 # 库存路也不放单选混进来


def test_grade_program_authority(uid):
    """判分=程序裁决（五件套齐发）：single 认小写也定错、fill 吃全角+｜备选、
    multi 判语点名漏选；解析/思维误区/掌握度建议判后才放行；判过的不重判（幂等）。
    2b 后答错自动开归类腿——假电厂必须注入：宿主 .env 是真 key，裸奔=烧钱。"""
    _, fn = _script_chat([json.dumps({"category": "审题", "description": "测试占位",
                                      "match_id": None}, ensure_ascii=False)])
    with SessionLocal() as s:
        node = _setup(s, uid)
        q1, q2, q3, q4 = _seed_questions(s, uid, node)
        out = json.loads(grade_answer({"answers": [
            {"qid": q1, "answer": " b "},          # 小写+空格=对
            {"qid": q2, "answer": "A"},            # 字母对不上=错
            {"qid": q3, "answer": "７４７.５"},     # 全角命中｜备选=对
            {"qid": q4, "answer": "AB"},           # 多选漏了 D——判语必须点名
            {"qid": q1, "answer": "B"},            # 已判过→票闸幂等拒
        ]}, {**_ctx(s, uid), "inner_chat_fn": fn}))
    assert out["判分"] == 4
    d = {x["qid"]: x for x in out["详情"]}
    assert d[q1]["判定"] == "对" and d[q2]["判定"] == "错"
    assert d[q3]["判定"] == "对" and d[q4]["判定"] == "错"
    assert d[q4]["错因参考"] == "漏选：D" and d[q4]["正确答案"] == "ABD"
    assert d[q1]["思维误区"] is None and "同级微调" in d[q1]["掌握度建议"]   # 五件套逐题在场
    assert d[q2]["思维误区"] is None and "先问用户" in d[q2]["掌握度建议"]
    assert "该露出的解析" in json.dumps(out, ensure_ascii=False)
    assert out["没判成"] == [{"qid": q1, "原因": "本户账上没有这道题的未判分记录（票闸）"}]
    with SessionLocal() as s:
        rows = {r[0]: r for r in s.execute(text(
            "SELECT q.id, a.user_answer, a.is_correct, a.duration_sec FROM quiz_attempts a "
            "JOIN questions q ON q.id = a.question_id "
            "WHERE q.user_id = :u AND a.user_answer IS NOT NULL"), {"u": uid})}
        assert rows[q1][1] == " b " and rows[q1][2] is True            # 原样入库，归一化只在比对时
        assert 120 <= rows[q1][3] < 400                                 # 3 分钟前问题：用时程序计
        assert rows[q2][2] is False and rows[q4][2] is False
        assert rows[q3][2] is True


def test_grade_short_leg(uid):
    """主观题腿全链：判定只三档、is_correct 恒 NULL（没有对错的事实不硬掰布尔——
    让数据撒谎比没数据更糟）、点评落 thinking_note（首刀预建列兑现）、
    嵌套运费入账；模型越档（给分数）被程序打成对照失败。"""
    rj = json.dumps({"verdict": "基本达标", "commentary": "要点齐全，思路稳", "pitfall": ""},
                    ensure_ascii=False)
    bj = json.dumps({"verdict": "良（85分）", "commentary": "胡说", "pitfall": ""})
    calls, fn = _script_chat([rj, bj])
    with SessionLocal() as s:
        node = _setup(s, uid)
        qid = s.scalar(text(
            "INSERT INTO questions (user_id, exam_type, source, subject, kp_ref, qtype, "
            "difficulty, stem, options, answer, analysis, status, created_at) VALUES "
            "(:u, '公务员考试', 'uploaded', '资料分析', :k, 'short', 'mid', '简述基期量与增长量关系', "
            "CAST('[]' AS JSONB), '现期=基期+增长量｜基期=现期−增长量', '两式互逆', 'active', "
            "now()) RETURNING id"), {"u": uid, "k": node})
        for _ in range(2):   # 两次作答两张 pending 行（append-only 历史不覆盖）
            s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, created_at) "
                           "VALUES (:i, :u, now())"), {"i": qid, "u": uid})
        s.commit()
        out = json.loads(grade_answer({"answers": [{"qid": qid, "answer": "甲乙都答上了"}]},
                                      {**_ctx(s, uid), "inner_chat_fn": fn}))
        assert out["详情"][0]["判定"] == "基本达标" and "要点齐全" in out["详情"][0]["点评"]
        assert "参考答案要点" in out["详情"][0] and "分数" in out["rule"]   # 不给分承诺进规矩行
        row = s.execute(text("SELECT is_correct, thinking_note FROM quiz_attempts "
                             "WHERE question_id = :i AND user_answer IS NOT NULL "
                             "ORDER BY id LIMIT 1"), {"i": qid}).first()
        assert row.is_correct is None and row.thinking_note == "要点齐全，思路稳"
        out2 = json.loads(grade_answer({"answers": [{"qid": qid, "answer": "只答了甲"}]},
                                       {**_ctx(s, uid), "inner_chat_fn": fn}))
        assert out2["详情"][0]["判定"] == "对照失败"      # 模型越档=程序认怂，分数不外流
    assert len(calls) == 2
    with SessionLocal() as s:
        assert s.scalar(text("SELECT sum(tokens) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 30                  # 两轮主观点评运费 (10+5)×2 全落账


# ── 二刀 2b：错误模式沉淀（F-29 · D31 甲）──

def test_classify_error_program_enforcement():
    """归类腿程序执法（D31 甲）：category 越五档→压『知识漏洞』+watch；match_id 不在
    喂入清单→作废 None（防编造=真值覆盖闸同款）；合并却不给描述→沿用原账条文
    （剪线可以抹字不行）；新账没描述→兜底不立空文；模型吐垃圾→整体兜底。"""
    pats = [{"id": 7, "category": "审题", "description": "把基期看成现期"}]
    calls, fn = _script_chat([json.dumps({"category": "心态崩", "description": "x",
                                          "match_id": 7}, ensure_ascii=False)])
    r, p, c = classify_error(fn, stem="s", ref_answer="B", user_answer="A",
                             judge_note="选项字母比对", subject="资料分析", patterns=pats)
    assert r == {"category": "知识漏洞", "description": "x", "match_id": 7, "watch": True}
    assert (p, c) == (10, 5) and len(calls) == 1
    _, fn2 = _script_chat([json.dumps({"category": "审题", "description": "d",
                                       "match_id": 4242}, ensure_ascii=False)])
    r2, _, _ = classify_error(fn2, stem="s", ref_answer="B", user_answer="A",
                              judge_note="n", subject="", patterns=pats)
    assert r2["match_id"] is None and r2["watch"] is False       # 编造 id 作废→另立新账
    _, fn3 = _script_chat([json.dumps({"category": "公式", "description": "  ",
                                       "match_id": 7}, ensure_ascii=False)])
    r3, _, _ = classify_error(fn3, stem="s", ref_answer="B", user_answer="A",
                              judge_note="n", subject="", patterns=pats)
    assert r3["match_id"] == 7 and r3["description"] == "把基期看成现期"   # 合并兜原话
    _, fn4 = _script_chat([json.dumps({"category": "公式", "description": "",
                                       "match_id": None}, ensure_ascii=False)])
    r4, _, _ = classify_error(fn4, stem="s", ref_answer="B", user_answer="A",
                              judge_note="n", subject="", patterns=pats)
    assert "观察" in r4["description"]                            # 新账不立空条文
    _, fn5 = _script_chat(["今天模型犯病，吐的不是 JSON"])
    r5, _, _ = classify_error(fn5, stem="s", ref_answer="B", user_answer="A",
                              judge_note="n", subject="", patterns=pats)
    assert r5["category"] == "知识漏洞" and r5["watch"] and r5["match_id"] is None


def test_grade_wrong_sediments_new_patterns(uid):
    """答错自动沉淀（全链）：判对的题不开账；越五档的归类被程序压成『知识漏洞』挂
    『待观察』旗；编造 match_id 作废后另立新账；第二道错的清单里看得见第一道——
    合并的语义判确实递到了模型手上；错题证据链（attempt.error_pattern_ref）挂上；
    归类运费单独入 usage_logs（客观判分本身免费，账上 30 全是电厂的）。"""
    r_q2 = json.dumps({"category": "心态", "description": "考场紧张看串行",
                       "match_id": None}, ensure_ascii=False)
    r_q4 = json.dumps({"category": "审题", "description": "把基期看成现期",
                       "match_id": 4242}, ensure_ascii=False)
    calls, fn = _script_chat([r_q2, r_q4])
    with SessionLocal() as s:
        node = _setup(s, uid)
        q1, q2, q3, q4 = _seed_questions(s, uid, node)
        out = json.loads(grade_answer({"answers": [{"qid": q1, "answer": "B"},
                                                   {"qid": q2, "answer": "A"},
                                                   {"qid": q4, "answer": "AB"}]},
                                      {**_ctx(s, uid), "inner_chat_fn": fn}))
    assert len(calls) == 2                                        # 只有两道错的烧归类腿
    d = {x["qid"]: x for x in out["详情"]}
    assert "错误模式" not in d[q1] and "作答_id" not in d[q1]      # 判对的不入这本账
    assert "知识漏洞" in d[q2]["错误模式"] and "待观察" in d[q2]["错误模式"]
    assert "新开一账" in d[q4]["错误模式"] and "审题" in d[q4]["错误模式"]
    assert d[q2]["作答_id"] and d[q4]["作答_id"]                  # 解绑凭据在场
    assert "考场紧张看串行" in calls[1][-1]["content"]             # 同轮第一道已进清单
    with SessionLocal() as s:
        pats = {r.category: r for r in s.execute(text(
            "SELECT category, description, count, tags FROM error_patterns WHERE user_id = :u"),
            {"u": uid})}
        assert set(pats) == {"知识漏洞", "审题"}
        assert pats["知识漏洞"].count == 1 and pats["知识漏洞"].tags == ["待观察"]
        assert pats["审题"].tags is None
        refs = s.execute(text("SELECT error_pattern_ref FROM quiz_attempts a "
                              "JOIN questions q ON q.id = a.question_id "
                              "WHERE q.user_id = :u AND a.is_correct = false"),
                         {"u": uid}).all()
        assert len(refs) == 2 and all(r.error_pattern_ref for r in refs)
        assert s.scalar(text("SELECT sum(tokens) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 30                          # 两轮归类运费全落账


def test_grade_wrong_merges_existing_pattern(uid):
    """同义合并（F-29②）：第二次答错模型认领现有条目→count 归程序加、账不分裂出第二条；
    判语『老毛病复发…第 2 次』原样上报；错题证据链两题挂同一条。"""
    r1 = json.dumps({"category": "审题", "description": "把基期看成现期",
                     "match_id": None}, ensure_ascii=False)
    with SessionLocal() as s:
        node = _setup(s, uid)
        q1, q2, q3, q4 = _seed_questions(s, uid, node)
        grade_answer({"answers": [{"qid": q2, "answer": "A"}]},
                     {**_ctx(s, uid), "inner_chat_fn": _script_chat([r1])[1]})
        epid = s.scalar(text("SELECT id FROM error_patterns WHERE user_id = :u"), {"u": uid})
    r2 = json.dumps({"category": "审题", "description": "基期现期看反了",
                     "match_id": epid}, ensure_ascii=False)
    _, fn2 = _script_chat([r2])
    with SessionLocal() as s:
        out = json.loads(grade_answer({"answers": [{"qid": q4, "answer": "AB"}]},
                                      {**_ctx(s, uid), "inner_chat_fn": fn2}))
    d = out["详情"][0]
    assert "老毛病复发" in d["错误模式"] and "第 2 次" in d["错误模式"]
    with SessionLocal() as s:
        rows = s.execute(text("SELECT id, description, count FROM error_patterns "
                              "WHERE user_id = :u"), {"u": uid}).all()
        assert len(rows) == 1 and rows[0].count == 2 and rows[0].description == "基期现期看反了"
        refs = {r for r in s.execute(text("SELECT error_pattern_ref FROM quiz_attempts a "
                                          "JOIN questions q ON q.id = a.question_id "
                                          "WHERE q.user_id = :u AND a.user_answer IS NOT NULL"),
                                     {"u": uid})}
        assert refs == {(epid,)}                                   # 两题一条链，账不分裂
        assert s.scalar(text("SELECT sum(tokens) FROM usage_logs WHERE user_id = :u"),
                        {"u": uid}) == 30


def test_unbind_error_pattern(uid):
    """解绑（F-29③）票闸：只剪本户真实挂着模式的连线——重复撤的、别人的、挂空链的、
    非整数、查无此行的全进『没动成的』；解绑只撤归属：attempt.ref 归 NULL，
    模式与 count 不动（用户否认的是『这是我的毛病』，不是『这题我没错』）。"""
    with SessionLocal() as s:
        node = _setup(s, uid)
        q1, q2, q3, q4 = _seed_questions(s, uid, node)
        epid = s.scalar(text(
            "INSERT INTO error_patterns (user_id, exam_type, subject, category, description, "
            "count, last_occurred_at, resolved, created_at) VALUES "
            "(:u, '公务员考试', '资料分析', '审题', '把基期看成现期', 3, now(), false, now()) "
            "RETURNING id"), {"u": uid})
        def tie(qid, u):   # 挂链的已判分作答（绕过判分手直造，专测解绑手自己）
            return s.scalar(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                                 "is_correct, duration_sec, error_pattern_ref, created_at) "
                                 "VALUES (:q, :u, 'A', false, 60, :p, now()) RETURNING id"),
                             {"q": qid, "u": u, "p": epid})
        aid_own = tie(q2, uid)
        aid_plain = s.scalar(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                                  "is_correct, duration_sec, created_at) VALUES "
                                  "(:q, :u, 'A', false, 60, now()) RETURNING id"),
                              {"q": q4, "u": uid})                  # 判过但没挂链——无连线可剪
        other = s.execute(text("INSERT INTO users (username, password_hash, status, created_at) "
                               "VALUES ('_quiz_t3', 'x', 'normal', now()) RETURNING id")).scalar()
        oq = _seed_questions(s, other, _setup(s, other))
        aid_other = tie(oq[0], other)                               # 别人作答，也挂了这条模式
        s.commit()
        out = json.loads(unbind_error_pattern(
            {"answer_ids": [aid_own, aid_own, aid_other, aid_plain, "x", 999999]}, _ctx(s, uid)))
        assert out["已解绑"] == [aid_own]                           # 只认第一刀，重复撤落空
        assert {r["作答_id"] for r in out["没动成的"]} == {aid_own, aid_other, aid_plain,
                                                          "x", 999999}
        assert s.scalar(text("SELECT error_pattern_ref FROM quiz_attempts WHERE id = :i"),
                        {"i": aid_own}) is None
        assert s.scalar(text("SELECT error_pattern_ref FROM quiz_attempts WHERE id = :i"),
                        {"i": aid_other}) == epid                   # 别人的连线一根没动
        assert s.scalar(text("SELECT count FROM error_patterns WHERE id = :i"),
                        {"i": epid}) == 3                           # count 不回退：账按事实留
        assert "非空数组" in unbind_error_pattern({"answer_ids": "不是数组"}, _ctx(s, uid))
        s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})   # 借的用户还回去
        s.commit()


def test_report_question_error_full_chain(uid):
    """三a D35 甲全链：报错=立即下架（status/note/时点进案卷）+ 判分记录标失效
    （pending 行没判分结果不标）+ 喂给模式账的连线全回滚、count 归零连账带销；
    重复报/别人的题票闸拒；下架题判分手从此判不动（q.status 闸=三路出局之一）；
    回执带核查队列数。"""
    rj = json.dumps({"category": "审题", "description": "把基期看成现期",
                     "match_id": None}, ensure_ascii=False)
    _, fn = _script_chat([rj])
    with SessionLocal() as s:
        node = _setup(s, uid)
        q1, q2, q3, q4 = _seed_questions(s, uid, node)
        grade_answer({"answers": [{"qid": q2, "answer": "A"}]},
                     {**_ctx(s, uid), "inner_chat_fn": fn})
        epid = s.scalar(text("SELECT id FROM error_patterns WHERE user_id = :u"), {"u": uid})
        s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, is_correct, "
                       "duration_sec, error_pattern_ref, created_at) VALUES "
                       "(:q, :u, 'C', false, 30, :p, now())"), {"q": q2, "u": uid, "p": epid})
        pend3 = s.scalar(text("INSERT INTO quiz_attempts (question_id, user_id, created_at) "
                              "VALUES (:q, :u, now()) RETURNING id"), {"q": q2, "u": uid})
        s.execute(text("UPDATE error_patterns SET count = 2 WHERE id = :p"), {"p": epid})
        s.commit()
        out = json.loads(report_question_error(
            {"qid": q2, "note": "答案算错：1000÷1.1 是 909 不是 990"}, _ctx(s, uid)))
        assert out["已下架"] == q2 and out["失效判分记录"] == 2 and out["核查队列现有"] == 1
        assert out["错误模式回滚"]["销账"] == [epid]
        row = s.execute(text("SELECT status, report_note, reported_at FROM questions "
                             "WHERE id = :q"), {"q": q2}).first()
        assert row.status == "reporting" and "909" in row.report_note and row.reported_at
        assert s.scalar(text("SELECT count(*) FROM error_patterns WHERE id = :p"),
                        {"p": epid}) == 0                        # 幻觉题生的账随母题死
        assert s.scalar(text("SELECT invalidated_at FROM quiz_attempts WHERE id = :i"),
                        {"i": pend3}) is None                    # 未判分行不标失效
        again = json.loads(report_question_error({"qid": q2}, _ctx(s, uid)))
        assert "已经在核查队列" in again["报错没办成"]              # 不双计队列
        gj = json.loads(grade_answer({"answers": [{"qid": q2, "answer": "B"}]},
                                     {**_ctx(s, uid), "inner_chat_fn": fn}))
        assert gj["判分"] == 0 and gj["没判成"][0]["qid"] == q2   # 下架题判不动（还有 pending 也拒）
        other = s.execute(text("INSERT INTO users (username, password_hash, status, created_at) "
                               "VALUES ('_quiz_t4', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
        oq = _seed_questions(s, other, _setup(s, other))
        rej = json.loads(report_question_error({"qid": oq[0]}, _ctx(s, uid)))
        assert "本户题库没有" in rej["报错没办成"]                  # 别人的题报不动（票闸）
        s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})   # 借的用户还回去
        s.commit()


def test_report_partial_rollback_keeps_pattern(uid):
    """账不只挂这道错题时只减不销：两题共喂一条模式（合并链），报错下架其一——
    模式活着 count=1，另一题的失效判分记录不陪葬（回滚精确按连线数，不一刀切）。"""
    r1 = json.dumps({"category": "审题", "description": "把基期看成现期",
                     "match_id": None}, ensure_ascii=False)
    with SessionLocal() as s:
        node = _setup(s, uid)
        q1, q2, q3, q4 = _seed_questions(s, uid, node)
        grade_answer({"answers": [{"qid": q2, "answer": "A"}]},
                     {**_ctx(s, uid), "inner_chat_fn": _script_chat([r1])[1]})
        epid = s.scalar(text("SELECT id FROM error_patterns WHERE user_id = :u"), {"u": uid})
    r2 = json.dumps({"category": "审题", "description": "看反了",
                     "match_id": epid}, ensure_ascii=False)
    with SessionLocal() as s:
        grade_answer({"answers": [{"qid": q4, "answer": "AB"}]},
                     {**_ctx(s, uid), "inner_chat_fn": _script_chat([r2])[1]})
        s.commit()
    with SessionLocal() as s:
        out = json.loads(report_question_error({"qid": q2}, _ctx(s, uid)))
        assert out["错误模式回滚"] == {"减账": [{"pattern_id": epid, "新count": 1}],
                                    "销账": None}
        assert s.scalar(text("SELECT count FROM error_patterns WHERE id = :p"),
                        {"p": epid}) == 1
        iv = s.execute(text("SELECT a.invalidated_at, q.id FROM quiz_attempts a JOIN questions q "
                            "ON q.id = a.question_id WHERE q.user_id = :u "
                            "AND a.user_answer IS NOT NULL AND a.is_correct = false"),
                       {"u": uid}).all()
        assert {r.id: (r[0] is not None) for r in iv} == {q2: True, q4: False}


def test_gen_prompt_injects_error_patterns(uid):
    """瘸点注入命题（F-30 前奏）：生成腿的命题 prompt 带上 top 未结案错误模式——
    让新题的干扰项精准踩坑；没账时该段整个消失（零成本）。"""
    gen = json.dumps({"questions": [_GOOD_SINGLE]})
    check = json.dumps({"check": [{"qid_index": 0, "verdict": "pass"}]})
    with SessionLocal() as s:
        node = _setup(s, uid)
        s.execute(text("INSERT INTO error_patterns (user_id, exam_type, subject, category, "
                       "description, count, last_occurred_at, resolved, created_at) VALUES "
                       "(:u, '公务员考试', '资料分析', '审题', '把基期看成现期', 7, now(), "
                       "false, now())"), {"u": uid})
        s.commit()
    calls, fn = _script_chat([gen, check])
    with SessionLocal() as s:
        generate_questions({"kp_name": "基期量", "count": 2},
                           {**_ctx(s, uid), "inner_chat_fn": fn})
    assert "高频错误模式" in calls[0][-1]["content"] and "把基期看成现期" in calls[0][-1]["content"]
    assert "高频错误模式" not in calls[1][-1]["content"]           # 坑注进命题轮，不污染自检轮
    with SessionLocal() as s:
        s.execute(text("DELETE FROM error_patterns WHERE user_id = :u"), {"u": uid})
        s.execute(text("DELETE FROM questions WHERE user_id = :u"), {"u": uid})   # attempts 级联走
        s.commit()
        calls2, fn2 = _script_chat([gen, check])
        generate_questions({"kp_name": "基期量", "count": 1},
                           {**_ctx(s, uid), "inner_chat_fn": fn2})
    assert "高频错误模式" not in calls2[0][-1]["content"]           # 无账=无段，prompt 原样


def test_grade_ticket_gate(uid):
    """票闸：别人的题判不动、没账的 qid 判不动——本户一行都不许变。"""
    _, fn = _script_chat([json.dumps({"category": "审题", "description": "占位",
                                      "match_id": None}, ensure_ascii=False)])
    with SessionLocal() as s:
        node = _setup(s, uid)
        own_ids = _seed_questions(s, uid, node)
        other = s.execute(text("INSERT INTO users (username, password_hash, status, created_at) "
                               "VALUES ('_quiz_t2', 'x', 'normal', now()) RETURNING id")).scalar()
        s.commit()
        other_ids = _seed_questions(s, other, _setup(s, other))
        out = json.loads(grade_answer({"answers": [
            {"qid": other_ids[0], "answer": "B"}, {"qid": 999999, "answer": "A"}]},
            {**_ctx(s, uid), "inner_chat_fn": fn}))
        assert out["判分"] == 0 and {g["qid"] for g in out["没判成"]} == {other_ids[0], 999999}
        for u in (uid, other):   # 两户都还是四张空白的考卷——越权失败要失败得干净
            assert s.scalar(text("SELECT count(*) FROM quiz_attempts WHERE user_id = :u "
                                 "AND user_answer IS NOT NULL"), {"u": u}) == 0
        s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})   # 借的用户还回去
        s.commit()
    assert own_ids   # 本户四题还挂着 pending 没被动过（上面的 0 已证，此行为防呆）


# ── DB 链段：三b 薄弱加权（F-30① D33 甲）──

def _seed_pattern_with_tie(s, u, node, cnt, desc="把基期看成现期"):
    """种一条 count=cnt 的未结案模式 + 一道挂在它名下、出自本 kp 的错题（10 天前
    判的：既构成 EXISTS 证据链，又不被 7 天新鲜度规则踢出库存）。返回 (epid, qid)。"""
    epid = s.scalar(text("INSERT INTO error_patterns (user_id, exam_type, subject, "
                         "category, description, count, last_occurred_at, resolved, "
                         "created_at) VALUES (:u, '公务员考试', '资料分析', '审题', :d, "
                         ":c, now(), false, now()) RETURNING id"),
                         {"u": u, "d": desc, "c": cnt})
    qid = s.scalar(text("INSERT INTO questions (user_id, exam_type, source, subject, "
                        "kp_ref, qtype, difficulty, stem, options, answer, analysis, "
                        "pitfall_hint, status, created_at) VALUES "
                        "(:u, '公务员考试', 'uploaded', '资料分析', :k, 'single', 'mid', "
                        "'带坑的老库存', CAST(:op AS JSONB), 'B', '解析', :d, 'active', "
                        "now()) RETURNING id"),
                        {"u": u, "k": node, "op": json.dumps(["A. 900", "B. 909"]), "d": desc})
    s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                   "is_correct, duration_sec, error_pattern_ref, created_at) VALUES "
                   "(:q, :u, 'A', false, 40, :e, now() - interval '10 days')"),
                   {"q": qid, "u": u, "e": epid})
    s.commit()
    return epid, qid


def test_weak_boost_targeted_generation(uid):
    """三b 主案：点中的 kp 被 count≥3 未结案模式牵着 → 本轮 ceil(40%) 是强化题：
    库存里程序盖过章的先顶上，缺口单开「强化批」独立生成轮（prompt 钉治疗令、
    入库题由程序盖章 pitfall_hint——功劳账在程序不在命题人自报）；回执按真实数
    带【强化批】声明且 rule 第一句前置——F-30② 不暗箱。"""
    genA = json.dumps({"questions": [_GOOD_SINGLE]})
    check = json.dumps({"check": [{"qid_index": 0, "verdict": "pass"}]})
    genB = json.dumps({"questions": [dict(_GOOD_SINGLE, stem="普通批补差题")]})
    calls, fn = _script_chat([genA, check, genB, check])
    with SessionLocal() as s:
        node = _setup(s, uid)
        epid, q_boost = _seed_pattern_with_tie(s, uid, node, 3)
        for st in ("普通库存一", "普通库存二"):   # 两枚无坑库存填 picked
            s.execute(text("INSERT INTO questions (user_id, exam_type, source, subject, "
                           "kp_ref, qtype, difficulty, stem, options, answer, analysis, "
                           "status, created_at) VALUES (:u, '公务员考试', 'uploaded', "
                           "'资料分析', :k, 'single', 'mid', :st, CAST(:op AS JSONB), "
                           "'B', '解析', 'active', now())"),
                           {"u": uid, "k": node, "st": st,
                            "op": json.dumps(["A. 900", "B. 909"])})
        s.commit()
        out = json.loads(generate_questions({"kp_name": "基期量", "count": 5},
                                            {**_ctx(s, uid), "inner_chat_fn": fn}))
    assert out["到手"] == 5 and len(out["题目"]) == 5
    assert out["题目"][0]["qid"] == q_boost          # 带章库存优先顶上强化额度
    assert len(calls) == 4                            # 强化批先（2 轮）+普通批（2 轮）
    assert "本批是强化题" in calls[0][-1]["content"]
    assert "把基期看成现期" in calls[0][-1]["content"]
    assert "本批是强化题" not in calls[2][-1]["content"]   # 普通批不下治疗令
    assert "2 道" in out["强化批"] and "把基期看成现期" in out["强化批"]
    assert out["rule"].startswith("回复第一句必须原样念出")
    with SessionLocal() as s:
        # 强化批的题带着程序盖章进了库——治没治过看账不看嘴
        assert s.scalar(text("SELECT count(*) FROM questions WHERE user_id = :u "
                             "AND source = 'llm' AND pitfall_hint = '把基期看成现期'"),
                       {"u": uid}) == 1


def test_weak_boost_below_threshold_no_trigger(uid):
    """对照组：模式 count=2 没过 ≥3 的强化线——即使挂着链也不触发：回执没有
    【强化批】、生成腿照旧单批、prompt 没有治疗令。"""
    gen = json.dumps({"questions": [dict(_GOOD_SINGLE, stem="缺口补出题")]})
    check = json.dumps({"check": [{"qid_index": 0, "verdict": "pass"}]})
    calls, fn = _script_chat([gen, check])
    with SessionLocal() as s:
        node = _setup(s, uid)
        _seed_pattern_with_tie(s, uid, node, 2)
        s.commit()
        out = json.loads(generate_questions({"kp_name": "基期量", "count": 2},
                                            {**_ctx(s, uid), "inner_chat_fn": fn}))
    assert "强化批" not in out
    assert len(calls) == 2 and "本批是强化题" not in calls[0][-1]["content"]


# ── DB 链段：三c 已克服（F-30③ D34 甲）──

def _seed_streak(s, u, node, n_true, desc="把基期看成现期"):
    """种一局「治过病」的账：一条未结案模式 + 旧题（-30 天一道挂链错题给它）、
    近段 n_true 道全对、中间故意埋一道**已作废**的错题（-9 天：剔除后既不计分
    也不断连击——两向都测到）、最后一道待判新题。返回 (epid, q_old, q_test)。"""
    epid = s.scalar(text("INSERT INTO error_patterns (user_id, exam_type, subject, "
                         "category, description, count, last_occurred_at, resolved, "
                         "created_at) VALUES (:u, '公务员考试', '资料分析', '审题', :d, "
                         "5, now(), false, now()) RETURNING id"), {"u": u, "d": desc})

    def _q(stem):
        return s.scalar(text("INSERT INTO questions (user_id, exam_type, source, "
                             "subject, kp_ref, qtype, difficulty, stem, options, answer, "
                             "analysis, status, created_at) VALUES "
                             "(:u, '公务员考试', 'uploaded', '资料分析', :k, 'single', "
                             "'mid', :st, CAST(:op AS JSONB), 'B', '解析', 'active', "
                             "now()) RETURNING id"),
                             {"u": u, "k": node, "st": stem,
                              "op": json.dumps(["A. 900", "B. 909"])})
    q_old, q_test = _q("旧题"), _q("待判新题")
    s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                   "is_correct, duration_sec, error_pattern_ref, created_at) VALUES "
                   "(:q, :u, 'A', false, 40, :e, now() - interval '30 days')"),
                   {"q": q_old, "u": u, "e": epid})
    offs = [2, 4, 6, 8, 10, 12, 14, 16, 18][:n_true]
    for d in offs:
        s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                       "is_correct, duration_sec, created_at) VALUES (:q, :u, 'B', true, "
                       "30, now() - interval '1 day' * :d)"), {"q": q_old, "u": u, "d": d})
    s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, user_answer, "
                   "is_correct, duration_sec, invalidated_at, created_at) VALUES "
                   "(:q, :u, 'A', false, 30, now(), now() - interval '9 days')"),
                   {"q": q_old, "u": u})
    s.execute(text("INSERT INTO quiz_attempts (question_id, user_id, created_at) VALUES "
                   "(:q, :u, now() - interval '3 minutes')"), {"q": q_test, "u": u})
    s.commit()
    return epid, q_old, q_test


def test_grade_proposes_after_ten_streak(uid):
    """提议腿：判完这题凑满 10 连对（作废错题被剔除——不断连击也不计分）→ 回执
    带【已克服提议】点名模式 id；提议只动嘴不动刀，账照旧挂着。"""
    _, fn = _script_chat([])   # 全对不触发归类腿——电厂一次都不该被叫
    with SessionLocal() as s:
        node = _setup(s, uid)
        epid, q_old, q_test = _seed_streak(s, uid, node, 9)
        out = json.loads(grade_answer({"answers": [{"qid": q_test, "answer": "B"}]},
                                      {**_ctx(s, uid), "inner_chat_fn": fn}))
        prop = out["已克服提议"]
        assert len(prop) == 1 and prop[0]["模式_id"] == epid and prop[0]["连续全对"] == 10
        assert "把基期看成现期" in prop[0]["坑"]
        assert out["rule"].startswith("若回执带【已克服提议】")
        assert not s.scalar(text("SELECT resolved FROM error_patterns WHERE id = :e"),
                            {"e": epid})                       # 没点头就没落刀
        s.execute(text("DELETE FROM error_patterns WHERE user_id = :u"), {"u": uid})
        s.execute(text("DELETE FROM questions WHERE user_id = :u"), {"u": uid})
        s.commit()


def test_grade_no_propose_below_ten(uid):
    """对照：连击只到 9（8 历史 + 本轮 1）→ 不提议——PRD 的 10 是门槛不是装饰。"""
    _, fn = _script_chat([])
    with SessionLocal() as s:
        node = _setup(s, uid)
        _seed_streak(s, uid, node, 8)
        out = json.loads(grade_answer({"answers": [{"qid": _pending_qid(s, uid),
                                                    "answer": "B"}]},
                                      {**_ctx(s, uid), "inner_chat_fn": fn}))
        assert "已克服提议" not in out


def _pending_qid(s, u):
    """本户唯一没判过的题（_seed_streak 造出来的 待判新题）。"""
    return s.scalar(text("SELECT a.question_id FROM quiz_attempts a WHERE a.user_id = :u "
                         "AND a.user_answer IS NULL"), {"u": u})


def test_resolve_error_pattern_full_chain(uid):
    """第 24 手全链：编号/别人的账/非整数全挡在票闸外；点头落刀翻 resolved；
    重销挡「已经结过」；结案后该模式退出加权触发（再出题回执不再带强化批）。"""
    boom_calls, fn = _script_chat([json.dumps({"questions": [_GOOD_SINGLE]}),
                                   json.dumps({"check": [{"qid_index": 0,
                                                          "verdict": "pass"}]})])
    with SessionLocal() as s:
        ctx = {**_ctx(s, uid)}
        assert "须是整数" in resolve_error_pattern({"pattern_id": "x"}, ctx)
        out = json.loads(resolve_error_pattern({"pattern_id": 999999}, ctx))
        assert "票闸" in out["销账没办成"]
        node = _setup(s, uid)
        epid, q_boost = _seed_pattern_with_tie(s, uid, node, 3)
        other = s.execute(text("INSERT INTO users (username, password_hash, status, "
                               "created_at) VALUES ('_quiz_t4', 'x', 'normal', now()) "
                               "RETURNING id")).scalar()
        s.commit()
        epid_other = s.scalar(text("INSERT INTO error_patterns (user_id, exam_type, "
                                   "category, description, count, last_occurred_at, "
                                   "resolved, created_at) VALUES (:o, '公务员考试', "
                                   "'审题', '别人的毛病', 4, now(), false, now()) "
                                   "RETURNING id"), {"o": other})
        s.commit()
        assert "票闸" in json.loads(resolve_error_pattern({"pattern_id": epid_other},
                                                          ctx))["销账没办成"]
        # 销账前先证它真的在加权（库存带章题优先顶额度→need=0，零电厂轮）
        out1 = json.loads(generate_questions({"kp_name": "基期量", "count": 1},
                                             {**ctx, "inner_chat_fn": fn}))
        assert "1 道" in out1["强化批"] and len(boom_calls) == 0
        done = json.loads(resolve_error_pattern({"pattern_id": epid}, ctx))
        assert done["已结案"] == epid and "把基期看成现期" in done["坑"]
        assert s.scalar(text("SELECT resolved FROM error_patterns WHERE id = :e"),
                        {"e": epid})
        assert "结过" in json.loads(resolve_error_pattern({"pattern_id": epid},
                                                          ctx))["销账没办成"]
        # 结案=退出加权：带章题因刚领走过 7 天新鲜度闸、库存见底→缺口走普通批
        # （电厂上岗但 prompt 无治疗令）；若 hits 没清干净，picked 顶格时 calls 仍为 2 看不穿，
        # 所以这里靠「强化批字段消失」断言——声明的触发条件是账，不是嘴。
        out2 = json.loads(generate_questions({"kp_name": "基期量", "count": 1},
                                             {**ctx, "inner_chat_fn": fn}))
        assert "强化批" not in out2 and len(boom_calls) == 2      # hits 空→target 0→need 1→普通批一轮
        s.execute(text("DELETE FROM users WHERE id = :o"), {"o": other})   # 借的用户还回去
        s.commit()   # 归还必须落账——不 commit 会话一关就回滚，孤儿年年留（今天悬案病根）
