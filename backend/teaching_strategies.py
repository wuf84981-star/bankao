# ============================================================
# 教学策略规则表（backend/teaching_strategies.py）—— S9 · W4 刀（2026-10-11）
# 「学情诊断结果 + 观察特征 → 策略」的确定性映射（外部方案 §3.3）：
# 把策略选择的成本从 1 次 LLM 调用降到 0，且「为什么用这招」可解释、可调试。
# 15 条 = 原文档 8 条例子的超集 + 主刀补齐 6 条（文档只给了计数没给全表）
#        + D89 费曼复述 1 条（用户拍板加招，受设置页意愿闸管）。
# 规则命中优先、**未命中返回 None**——None 才轮到模型兜底选（调用方 W5 的活），
# 本文件永不自作主张兜底：宁可交给模型，不硬塞错策略。
# W4 备料立场：无人 import，W5 教学图上岗才接线。
# ============================================================
from backend.zh_tokenizer import CUSTOM_WORDS

# ── 策略名（给程序）+ 人话对照（给日志/答辩/未来 PPT）──
SOCRATIC = "socratic"              # 苏格拉底追问
EMOTION = "emotion_support"        # 情绪调节
CASE_APPLY = "case_apply"          # 案例应用
DIRECTION = "direction_hint"       # 方向提示
ANALOGY = "analogy"                # 类比
STEP = "step_hint"                 # 步骤提示
VARIANT = "variant_practice"       # 变式练习
HANDOFF = "handoff_hint"           # 转教师话术（只提示，不落教师端）
ERROR_REVIEW = "error_review"      # 错因复盘（补）
ADVANCE = "advance_challenge"      # 进阶挑战（补）
METHOD_VERIFY = "method_verify"    # 思路验证（补）
ANSWER_REVERSE = "answer_reversed" # 答案反导（补）
CONCEPT = "concept_grounding"      # 概念铺垫（补）
CLARIFY = "clarify_question"       # 澄清反问（补）
FEYNMAN = "feynman_check"          # 费曼复述（D89，2026-10-18 用户拍板加招）

STRATEGY_CN = {
    SOCRATIC: "苏格拉底追问", EMOTION: "情绪调节", CASE_APPLY: "案例应用",
    DIRECTION: "方向提示", ANALOGY: "类比", STEP: "步骤提示",
    VARIANT: "变式练习", HANDOFF: "转教师话术", ERROR_REVIEW: "错因复盘",
    ADVANCE: "进阶挑战", METHOD_VERIFY: "思路验证", ANSWER_REVERSE: "答案反导",
    CONCEPT: "概念铺垫", CLARIFY: "澄清反问", FEYNMAN: "费曼复述",
}

# ── 程序侧词族（诊断腿给不了的特征，程序自己从字面算）──
_EMOTION_WORDS = ("烦", "气死", "崩溃", "炸了", "学不会", "看不懂", "笨",
                  "焦虑", "压力", "绝望", "难受", "想哭", "救命")
_CALC_WORDS = ("算", "公式", "计算", "求", "数值", "代入")
_ROTE_WORDS = ("背书", "记不住", "死记", "默写", "要背")
_QUESTION_MARKS = ("选项", "问：", "求：", "已知", "（ ）", "( )", "例题")
_METHOD_MARKS = ("我这样", "这样做", "我的思路", "这么列", "我算的", "这样对吗")
_ANSWER_MARKS = ("答案是什么", "给答案", "直接说答案", "答案呢")
# D89 费曼两词族：自称懂了（验一眼的主场）与主动要讲/要考（学生自己想当老师）。
# 误伤立场：撞错最多让教练多请一次「你讲我听」——有教育价值，不复杂化否判。
_DECLARED_WORDS = ("懂了", "明白了", "会了", "清楚了")
_OFFER_WORDS = ("我讲给你", "我给你讲", "我说一遍", "让我讲", "我复述",
                "我解释给", "考考我")


def extract_features(user_text: str, *, diagnosis: dict | None = None,
                     history: list[dict] | None = None, round_no: int = 1,
                     feynman_on: bool = False) -> dict:
    """从「本轮用户话 + 诊断产物 + 近几条历史 + 回环轮号」算出观察特征表。
    feynman_on=D89 用户意愿闸（设置页费曼开关，默认 False=不启用这招）——
    开关态由接线层查账注入，本函数不自查（纯函数立场）。
    diagnosis 契约（W5 诊断节点按此产出，缺键一律当假，保守不触发）：
      recent_wrong: int        近几答连续错次数
      recent_correct: int      近几答连续对次数
      off_topic: bool          完全没头绪（答非所问）
      vague_streak: bool       答对但表述含糊
      seen_before: bool|None   该知识点聊过吗（None=没查清，不触发）
      same_kp_wrong_again: bool 同知识点再次栽跟头
    history = [{role, content}] 正序近几条（判定「刚讲过同一知识点」用）。"""
    t = (user_text or "").strip()
    d = diagnosis or {}
    wrong_streak = int(d.get("recent_wrong") or 0) >= 2
    correct_streak = int(d.get("recent_correct") or 0)
    nouns = {w for w in CUSTOM_WORDS if w in t}
    last_ai = ""
    for m in (history or [])[::-1]:        # 从最新往回找教练行
        if m.get("role") == "assistant":
            last_ai = str(m.get("content") or "")
            break
    return {
        "round_ge5": round_no >= 5,                       # 回环封顶（施工图钉死）
        "wrong_streak": wrong_streak,
        "emotion": any(w in t for w in _EMOTION_WORDS),
        "calc": any(w in t for w in _CALC_WORDS),
        "off_topic": bool(d.get("off_topic")),
        "vague": bool(d.get("vague_streak")),
        "rote": any(w in t for w in _ROTE_WORDS),
        "specific_question": any(w in t for w in _QUESTION_MARKS),
        "same_kp_taught": bool(nouns) and any(w in last_ai for w in nouns),
        "same_kp_wrong_again": bool(d.get("same_kp_wrong_again")),
        "method_check": any(w in t for w in _METHOD_MARKS),
        "ask_answer": any(w in t for w in _ANSWER_MARKS),
        "declared_understand": any(w in t for w in _DECLARED_WORDS),   # D89 自称懂了
        "offer_explain": any(w in t for w in _OFFER_WORDS),            # D89 主动要讲/要考
        "feynman_on": feynman_on,                                     # 意愿闸透传（规则里比较用）
        "definition_first": d.get("seen_before") is False,
        "unclear_query": len(t) < 6 and not nouns,        # 短到没法问又不带专名
        "correct_streak": correct_streak,                 # 数值透传（规则里比较用）
    }


# 15 条规则按优先级排——pick_strategy 顺序扫，第一条命中即走。
# 排序的道理：封顶 > 情绪 > 纠错 > 新授 > 检验 > 兜底拒代答 > 澄清。
# D89 费曼插在「检验」族内（自称懂了/主动要讲，当场验一眼），且受用户意愿闸管。
RULES: list[tuple[str, object]] = [
    (HANDOFF,          lambda f: f["round_ge5"]),
    (EMOTION,          lambda f: f["wrong_streak"] and f["emotion"]),
    (SOCRATIC,         lambda f: f["wrong_streak"] and f["calc"] and not f["emotion"]),
    (DIRECTION,        lambda f: f["off_topic"]),
    (VARIANT,          lambda f: f["same_kp_taught"]),
    (ERROR_REVIEW,     lambda f: f["same_kp_wrong_again"]),
    (CASE_APPLY,       lambda f: f["correct_streak"] > 0 and f["vague"]),
    (ADVANCE,          lambda f: f["correct_streak"] >= 3 and not f["vague"]
                                  and not f["emotion"]),
    (FEYNMAN,          lambda f: f["feynman_on"]
                                  and (f["declared_understand"] or f["offer_explain"])),
    (ANALOGY,          lambda f: f["rote"]),
    (STEP,             lambda f: f["specific_question"]),
    (METHOD_VERIFY,    lambda f: f["method_check"]),
    (ANSWER_REVERSE,   lambda f: f["ask_answer"]),
    (CONCEPT,          lambda f: f["definition_first"]),
    (CLARIFY,          lambda f: f["unclear_query"]),
]


def pick_strategy(features: dict) -> str | None:
    """扫规则表返回第一条命中的策略名；全不命中 = None（模型兜底的信号）。"""
    for name, pred in RULES:
        if pred(features):
            return name
    return None
