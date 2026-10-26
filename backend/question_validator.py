# ============================================================
# 出题校验墙（S7 首刀 · PRD 23.3/补充二 · F-27 · D30 甲案「判定权全归程序」）
# 纯函数，零 DB 零网络——和 plan_validator 同一个道理：地面真值由调用方
# 查好喂进来，坏题在这里当场死，进不了题库也见不着用户。
# 每题独立判决（与计划的「整版全过才落库」不同粒度）：题库是一题一命的
# 消耗品，坏一题丢一题、好题照收——errors 只作回执附报，不连坐。
# ============================================================

QTYPES = ("single", "fill", "multi", "short")   # 二刀 2a 开闸：多选（F-28③漏错选区分）、
                                                 # 简答（F-28①要点对照不打分，判分腿归模型点评）
DIFFICULTIES = ("easy", "mid", "hard")
_LETTERS = "ABCDEFGH"


def validate_questions(raw, node_id: int) -> tuple[list[dict], list[str]]:
    """逐题验形状与真值，返回（合格题的规范化 dict 列表，不合格原因清单）。
    三条铁闸：
    ①枚举闸：qtype/difficulty 不认就死；
    ②一致性闸：single 答案单字母落在选项范围内；multi 答案字母去重后 ≥2
      且全在范围（答案"ABC"式串，顺序无关）——「答案选 E 但只有四个选项」
      这种模型幻觉题当场阵亡；
    ③真值覆盖闸：kp_ref 不收模型写的值，统一钉成本轮解析出的真实节点 id——
      模型编的知识点 id 连进 errors 的资格都没有（V3 防编造的出题版）。"""
    if not isinstance(raw, list):
        return [], ["questions 不是数组——要求 {\"questions\": [...]} 形"]
    valid, errors = [], []
    for i, q in enumerate(raw, start=1):
        tag = f"第{i}题"
        if not isinstance(q, dict):
            errors.append(f"{tag} 不是 JSON 对象")
            continue
        qtype = q.get("qtype")
        stem = str(q.get("stem") or "").strip()
        answer = str(q.get("answer") or "").strip()
        analysis = str(q.get("analysis") or "").strip()
        options = q.get("options") or []
        difficulty = q.get("difficulty") or "mid"
        if qtype not in QTYPES:
            errors.append(f"{tag} qtype=『{qtype}』不认，只许 {'/'.join(QTYPES)}")
            continue
        if not stem:
            errors.append(f"{tag} 题干为空")
            continue
        if not answer:
            errors.append(f"{tag} 答案为空（无答案的题不配进库）")
            continue
        if not analysis:
            errors.append(f"{tag} 解析为空（F-27①：解析必填）")
            continue
        if difficulty not in DIFFICULTIES:
            errors.append(f"{tag} difficulty=『{difficulty}』只认 {'/'.join(DIFFICULTIES)}")
            continue
        if qtype in ("single", "multi"):
            if not isinstance(options, list) or not 2 <= len(options) <= len(_LETTERS):
                errors.append(f"{tag} 单选题选项数须在 2~{_LETTERS} 个")
                continue
            options = [str(o).strip() for o in options if str(o).strip()]
            if len(options) < 2:
                errors.append(f"{tag} 选项清洗后不足 2 个")
                continue
            allowed = _LETTERS[:len(options)]
            letters = "".join(sorted({c for c in answer.upper() if c.isalpha()}))
            if qtype == "single":
                if answer.upper() not in allowed:
                    errors.append(f"{tag} 答案『{answer[:10]}』越出选项范围（{len(options)} 选项只许 "
                                  f"{allowed}）")
                    continue
            elif len(letters) < 2 or any(c not in allowed for c in letters):
                # multi 一致性闸：答案须是范围内 ≥2 个不同字母——写 "A" 的多选是伪多选
                errors.append(f"{tag} 多选答案『{answer[:10]}』须为 {allowed} 中 ≥2 个字母"
                              f"（如 ABD，顺序无关）")
                continue
            answer = letters if qtype == "multi" else answer.upper()
        else:  # fill/short：无选项，答案即文本（fill 多可接受答案用｜分隔；short 存参考答案要点）
            options = []
        valid.append({
            "qtype": qtype, "stem": stem[:2000], "options": options,
            "answer": answer[:500], "analysis": analysis[:2000],
            "difficulty": difficulty, "kp_ref": node_id,        # 真值覆盖闸：钉死成本轮节点
            "pitfall_hint": str(q.get("pitfall_hint") or "").strip()[:500] or None,
        })
    return valid, errors
