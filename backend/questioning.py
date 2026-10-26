# ============================================================
# 出题生成腿（S7 首刀 · PRD 23.3 · F-27 流程「生成→两段式自检」）
# 工具手内嵌套的模型调用都住这里：专用命题提示词（不带工具箱——命题人
# 不需要举手，只要吐 JSON）、宽容 JSON 提取、两段式自检、归一化判分函数。
# 运费（这两轮的 token）由调用方 tools.generate_questions 记进 usage_logs——
# 嵌套调用外层循环看不见，不记账就是漏扣，配额闸（F-35）会形同虚设。
# ============================================================
import json

from backend.question_validator import validate_questions


def extract_json(text: str):
    """从模型回复里抠出 JSON：剥 markdown 围栏、从第一个 { 或 [ 试到配平为止。
    命题/复核两轮吃的都是这个——deepseek 偶尔裹一层 ```json，不能因此判死。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    for i, ch in enumerate(t):
        if ch not in "{[":
            continue
        closer = "}" if ch == "{" else "]"
        j = t.rfind(closer)
        while j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                j = t.rfind(closer, i + 1, j)
        return None
    return None


def _gen_prompt(kp_name: str, subject: str, exam_type: str, level: str,
                count: int, difficulty: str, materials: str, node_id: int,
                weak_spots: str = "", qtype: str = "", pitfall_focus: str = "") -> list[dict]:
    diff_hint = {"easy": "easy", "mid": "mid 为主", "hard": "hard", "": "按用户水平自选"}[difficulty]
    diff_part = f"（难度倾向：{diff_hint}）" if difficulty else ""
    # 真机案（2026-09-09）：用户点名要多选，qtype 没传进命题腿，命题人自由
    # 发挥全出了单选——库存过滤守约束、生成腿丢约束。指定时钉死，不许再选。
    qt_line = (f"- qtype 一律 {qtype}（用户点名要这个题型，出了别的型等于没出题）\n"
               if qtype else
               "- qtype 从 single（四选一）/multi（多选）/fill（填空）/short（简答）中选；")
    mat = f"\n参考资料（用户讲义原文，优先据此命题；为空则按该考试通用考纲常识）：\n{materials}" if materials else ""
    # F-30 的前置铺垫（二刀 2b）：错误模式注入命题——「该避的坑」反过来用，
    # 让新题专门带得上这些陷阱选项。只喂模式描述，不喂具体旧题，防的是原题照抄。
    weak = (f"\n用户的高频错误模式（命题时让干扰项精准踩中这些坑，暴露问题；"
            f"但题面与解析里不要出现这些模式本身，不许泄底）：\n{weak_spots}" if weak_spots else "")
    # 三b 强化批次（F-30① D33 甲）：点中 count≥3 老毛病时单独一轮命题，
    # 整批专治一个坑——坑要设得准，但题面解析不许说破治什么（防暗示答案）。
    focus = (f"\n【本批是强化题】每道题都必须至少埋一个能接住「{pitfall_focus}」"
             f"这类错误的诱错选项——用户正在治这个老毛病；坑要准，但题面与解析"
             f"绝不许点破治疗对象（点了等于泄答案）。" if pitfall_focus else "")
    return [
        {"role": "system", "content": "你是公考命题人，只输出一个 JSON 对象，不输出任何其他文字。"},
        {"role": "user", "content":
            f"为知识点【{kp_name}】（科目：{subject or '未标'}，考试：{exam_type}，"
            f"用户当前掌握度：{level}）出 {count} 道练习题{diff_part}。要求：\n"
            f"{qt_line}难度 difficulty 用 easy/mid/hard\n"
            "- stem 题面自带完整情境与数据（不看资料也能作答），数据要真实可验算，杜绝编造出不出的数\n"
            "- options：single 为 4 个字符串选项（每项以『A. 』『B. 』等开头）；multi 为 2~8 个同形制；"
            "fill/short 给空数组 []\n"
            "- answer：single 只填选项字母（如 B）；multi 填答案字母连写（如 ABD，顺序无关、至少两个）；"
            "fill 填标准答案，若有多个等价写法用全角｜分隔（如 615｜615.5）；"
            "short 填参考答案要点，用全角｜分隔\n"
            "- analysis：解析（解题思路+关键步骤，判分后给用户看）；pitfall_hint：可选，预期思维陷阱\n"
            f"- kp_ref 一律照抄 {node_id}\n"
            f'输出形如 {{"questions": [{{"qtype":"single","stem":"…","options":["A. …","B. …","C. …","D. …"],'
            f'"answer":"A","analysis":"…","difficulty":"mid","kp_ref":{node_id}}}]}}{mat}{weak}{focus}'},
    ]


def _check_prompt(questions: list[dict]) -> list[dict]:
    return [
        {"role": "system", "content": "你是苛刻的审题员，只输出一个 JSON 对象，不输出其他文字。"},
        {"role": "user", "content":
            "下面是拟出的题目（含给定答案）。请逐题先只看题面独立重解（心里算），再与给定答案比对：\n"
            "- 你的解与给定答案一致 → verdict=pass\n"
            "- 不一致、题目无解/多解、数据自相矛盾、题干依赖看不到的资料 → verdict=drop 并写明 reason\n"
            '只输出 {"check":[{"qid_index":0,"verdict":"pass","reason":""}]}（qid_index 是下面数组的下标）。\n'
            f"题目：{json.dumps([{k: q[k] for k in ('qtype','stem','options','answer','analysis')} for q in questions], ensure_ascii=False)}"},
    ]


def gen_and_check(chat_fn, *, kp_name: str, subject: str, exam_type: str, level: str,
                  count: int, difficulty: str, materials: str, node_id: int,
                  weak_spots: str = "", qtype: str = "", pitfall_focus: str = ""
                  ) -> tuple[list[dict], list[str], int, int]:
    """生成→校验墙→两段式自检，返回（存活题，问题清单，prompt_tokens，completion_tokens）。
    假电厂注入形状与 answer_turn.chat_fn 同构：fn(msgs) → (msg_dict, p, c)（不给 tools）。"""
    problems: list[str] = []
    ptok = ctok = 0
    msg, p, c = chat_fn(_gen_prompt(kp_name, subject, exam_type, level, count,
                                    difficulty, materials, node_id, weak_spots,
                                    qtype, pitfall_focus))
    ptok += p; ctok += c
    data = extract_json(msg.get("content") or "")
    raw = data.get("questions") if isinstance(data, dict) else data
    valid, errs = validate_questions(raw if raw is not None else [], node_id)
    problems += errs
    if not valid:
        return [], problems, ptok, ctok
    # 第二段：独立重做比对（PRD 23.3）——drop 的题当场火化，不进库
    msg, p, c = chat_fn(_check_prompt(valid))
    ptok += p; ctok += c
    data = extract_json(msg.get("content") or "")
    drop = set()
    check = data.get("check", []) if isinstance(data, dict) else []
    for row in check:
        if isinstance(row, dict) and row.get("verdict") == "drop":
            try:
                drop.add(int(row.get("qid_index")))
            except (TypeError, ValueError):
                pass
    kept = [q for i, q in enumerate(valid) if i not in drop]
    if drop:
        problems.append(f"自检弃题 {len(drop)} 道（答案与独立重解冲突或题目本身有毛病）")
    return kept, problems, ptok, ctok


def _norm_fill(s: str) -> str:
    """填空题判分归一化：NFKC 把全角数字/标点/字母折成半角，去空白、折大小写——
    「615.5」「６１５.５」「615.5 　」是同一个答案。客观题对错归程序判（F-28①），
    这道归一化就是「程序判」与「用户没打错」之间的那道桥。"""
    import unicodedata
    return "".join(unicodedata.normalize("NFKC", str(s)).split()).lower()


def grade_one(qtype: str, ref_answer: str, user_answer: str) -> tuple[bool, str]:
    """客观题程序判分（D30 甲：对错裁决权在程序），返回（对错, 判语）。
    single 比字母、fill 归一化后对多可接受答案任一、multi 集合比对且
    **漏选/错选区分**（F-28③——「少选了 B」和「多选了 D」是两种病，
    反馈措辞不能混）。short 不走这里：主观题归 short_review（F-28①）。"""
    if qtype == "single":
        ua = str(user_answer).strip().upper()
        ok = bool(ua) and ua[:1] == str(ref_answer).strip().upper()[:1]
        return ok, "选项字母比对"
    if qtype == "multi":
        ua = {c for c in str(user_answer).upper() if c.isalpha()}
        ref = {c for c in str(ref_answer).upper() if c.isalpha()}
        if not ua:
            return False, "未作答"
        if ua == ref:
            return True, "选项集合全中"
        missed, wrong = sorted(ref - ua), sorted(ua - ref)
        if missed and wrong:
            return False, f"漏选 {'/'.join(missed)}、错选 {'/'.join(wrong)}"
        if missed:
            return False, f"漏选：{'/'.join(missed)}"
        return False, f"错选：{'/'.join(wrong)}"
    ua = _norm_fill(user_answer)
    if not ua:
        return False, "未作答"
    return (any(ua == _norm_fill(part) for part in str(ref_answer).split("｜")),
            "文本比对")


SHORT_VERDICTS = ("基本达标", "部分达标", "未达标")

ERROR_CATEGORIES = ("审题", "公式", "逻辑", "习惯", "知识漏洞")   # F-29① 五类，D31 甲：代码枚举执法


def classify_error(chat_fn, *, stem: str, ref_answer: str, user_answer: str,
                   judge_note: str, subject: str, patterns: list[dict]):
    """答错之后的错因归类（F-29）：模型只做「语义判」——这错是不是现有某条老毛病的
    同义复发（match_id）、归不进五类时猜哪类；**枚举闸程序执法**（D31 同款刀法）：
    category 越出五类 → 打成『知识漏洞』+tags 挂『待观察』（PRD：归不进则新建标注待观察），
    match_id 不在喂入的真实 id 清单里 → 作废归 None（防编造，真值覆盖闸同款）。
    返回 ({category, description, match_id}, p, ct)——落账动作在调用方 tools 层。"""
    menu = [{"id": p["id"], "category": p["category"], "description": p["description"]}
            for p in patterns]
    msgs = [
        {"role": "system", "content": "你是错题归因员，只输出一个 JSON 对象，不输出其他文字。"},
        {"role": "user", "content":
            f"用户答错了一道题（科目：{subject or '未标'}）。\n"
            f"题面：{stem}\n参考答案：{ref_answer}\n用户作答：{user_answer}\n"
            f"程序判语：{judge_note}\n\n"
            f"他现有的错误模式清单：{json.dumps(menu, ensure_ascii=False)}\n"
            "请判断这次错误的归属：\n"
            "- category 只能是 审题/公式/逻辑/习惯/知识漏洞 之一（实在归不进也选最接近的）\n"
            "- 若这次错误与清单里某条是同一个毛病（措辞不同也算）→ match_id 填那条的 id；"
            "否则 match_id 填 null\n"
            "- description：一句话说到「下次怎么防」的具体程度（如『把基期看成现期』），"
            "match 现有条目时可沿用或补充其说法\n"
            '输出 {"category":"…","description":"…","match_id":null}'},
    ]
    msg, p, c = chat_fn(msgs)
    data = extract_json(msg.get("content") or "") or {}
    if not isinstance(data, dict):
        data = {}
    category = data.get("category")
    watch = category not in ERROR_CATEGORIES          # 越档 → 程序执法
    if watch:
        category = "知识漏洞"
    mid = data.get("match_id")
    real_ids = {pp["id"] for pp in patterns}
    try:
        mid = int(mid) if mid is not None else None
    except (TypeError, ValueError):
        mid = None
    if mid not in real_ids:                           # 防编造：不在清单=新毛病
        mid = None
    desc = str(data.get("description") or "").strip()[:500]
    if mid is None and not desc:
        desc = "（模型未给描述，待人工观察）"          # 新账不能立成空条文
    if mid is not None and not desc:
        # 合并回老账：模型懒得复述时沿用原话——剪线可以，抹字不行
        desc = next((pp["description"] for pp in patterns if pp["id"] == mid), "")
    return ({"category": category, "description": desc, "match_id": mid,
             "watch": watch}, p, c)


def short_review(chat_fn, *, stem: str, points: str, user_answer: str):
    """主观题要点对照+思路点评（F-28①：不打分——23.7 对用户承诺了「不提供分数」，
    连及格率式数字也不给）。语义比对确实编不成代码，是判分腿唯一让给模型的口子；
    作为交换，**枚举闸程序执法**（D31 同款刀法）：verdict 不在这三档就当场打成
    『对照失败』——宁可认怂，不让模型自造结论。返回 (dict, prompt_tokens, completion_tokens)。"""
    msgs = [
        {"role": "system", "content": "你是主观题阅卷老师，只输出一个 JSON 对象；不打分、"
                                      "不出现任何分数，其他文字一律不输出。"},
        {"role": "user", "content":
            f"题面：{stem}\n参考答案要点（｜分隔）：{points}\n用户作答：{user_answer}\n"
            "请对照要点作答：verdict 只能是 基本达标/部分达标/未达标 之一；"
            "commentary=思路点评（答到了哪些要点、漏了哪些、思路偏在哪）；"
            "pitfall=最可能的思维误区一句话（没有则空串）。\n"
            '输出 {"verdict":"…","commentary":"…","pitfall":"…"}'},
    ]
    msg, p, c = chat_fn(msgs)
    data = extract_json(msg.get("content") or "")
    v = data.get("verdict") if isinstance(data, dict) else None
    if v not in SHORT_VERDICTS:
        v = "对照失败"
    return ({"verdict": v,
             "commentary": str((data or {}).get("commentary") or "")[:2000],
             "pitfall": str((data or {}).get("pitfall") or "").strip()[:500]}, p, c)
