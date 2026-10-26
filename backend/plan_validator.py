# ============================================================
# 计划硬校验器（plan_validator.py · S5 第一刀 · PRD 23.4 可编码规格）
# D13 拍板：独立纯函数模块——不 import DB，地面真值（节点集/掌握度/
# 每日可用时长/辅考预留）全部由工具层查好后当参数喂进来。
# 好处：单测直接喂坏 JSON 验每一条规则，零数据库依赖、零模型依赖。
# PRD 23.4 原则原句：计划引擎是全产品仅有的"必须确定性"环节，
# 凡能用代码判定的绝不留给模型自由发挥——本模块就是那堵墙的执法队。
# 返回：人话错误列表（带日期带数字），原样回给模型携因重排（F-22 ≤3 次）。
# ============================================================
from datetime import date, datetime, timedelta

KINDS = ("new", "exercise", "review", "mock", "sprint")
SPRINT_KINDS = {"sprint", "mock", "review"}          # V4：冲刺段内只许这些
CAP_RATIO = 1.2                                       # V2 容忍系数（PRD 原数）
V5_SHARE = 0.6                                        # V5 落地口径：当日头号科目占比线（勘行已记 PRD）
V5_RUN = 2                                            # V5 落地口径：连续天数
SPRINT_MIN, SPRINT_MAX = 14, 35                       # BR-05 冲刺段时长


def parse_shape(days):
    """形状关（V1~V6 之前的地板）：把模型吐的 days 解析成
    [(date, [{kp_ref,subject,task,est,kind}])]；不合格不回解析结果，回错误列表。
    返回 (parsed, errors)——errors 非空时 parsed 为 None。"""
    if not isinstance(days, list) or not days:
        return None, ["days 必须是非空数组，逐日列出计划"]
    parsed, errs, seen = [], [], set()
    for di, day in enumerate(days):
        if not isinstance(day, dict):
            errs.append(f"days[{di}] 不是对象"); continue
        try:
            d = datetime.strptime(str(day.get("date", "")), "%Y-%m-%d").date()
        except ValueError:
            errs.append(f"days[{di}].date 不是 YYYY-MM-DD：『{day.get('date')}』"); continue
        if d in seen:
            errs.append(f"日期重复：{d}"); continue
        seen.add(d)
        items = day.get("items")
        if not isinstance(items, list) or not items:
            errs.append(f"{d} 的 items 缺失或为空——每天至少一条任务"); continue
        pi_items, ok = [], True
        for ii, it in enumerate(items):
            if not isinstance(it, dict):
                errs.append(f"{d}.items[{ii}] 不是对象"); ok = False; break
            kind = it.get("kind")
            if kind not in KINDS:
                errs.append(f"{d}.items[{ii}] kind=『{kind}』不认，只许 {'/'.join(KINDS)}")
                ok = False; break
            task = str(it.get("task", "")).strip()
            if not task:
                errs.append(f"{d}.items[{ii}] task 不能为空（禁『复习数学』式空任务）")
                ok = False; break
            try:
                est = int(it.get("est_minutes"))
            except (TypeError, ValueError):
                errs.append(f"{d}.items[{ii}] est_minutes 需是整数分钟，收到『{it.get('est_minutes')}』")
                ok = False; break
            if est <= 0 or est > 16 * 60:
                errs.append(f"{d}.items[{ii}] est_minutes={est} 出界（0<est≤960）")
                ok = False; break
            kp = it.get("kp_ref")
            if kp is not None:
                try:
                    kp = int(kp)
                except (TypeError, ValueError):
                    errs.append(f"{d}.items[{ii}] kp_ref 需是整数节点 id 或省略"); ok = False; break
            pi_items.append({"date": d, "kp_ref": kp, "subject": str(it.get("subject", "")).strip()[:64],
                             "task": task[:500], "est": est, "kind": kind})
        if ok:
            parsed.append((d, pi_items))
    if errs:
        return None, errs
    return sorted(parsed, key=lambda x: x[0]), None


def validate_plan(parsed, *, exam_date, weekday_min, weekend_min,
                  reserved_daily, node_ids, levels, today=None):
    """V1~V6 全规则审判（parsed 为 parse_shape 的产物）。返回人话错误列表，空表=全过。
    参数：exam_date 主考日；weekday/weekend_min 声明的每日可用分钟（None=未声明）；
    reserved_daily 其他考试每日预留净值（BR-23，辅考 weekly/7，单考 0）；
    node_ids 该用户该考试的真实节点 id 集合（V3）；levels {节点id: 掌握档}（V6）。"""
    today = today or date.today()
    errors = []
    day_dates = [d for d, _ in parsed]

    # V1 日期全覆盖：今天 ≤ 每日 ≤ 考试前日，一天不缺不多
    if day_dates:
        want = set()
        d = max(today, day_dates[0])
        while d < exam_date:
            want.add(d); d += timedelta(days=1)
        have = set(day_dates)
        if min(have) < today:
            errors.append(f"V1 排了过去的日期（最早 {min(have)}，今天 {today}）——从今日起排")
        if max(have) != exam_date - timedelta(days=1):
            errors.append(f"V1 末日必须恰好是考试前日 {exam_date - timedelta(days=1)}，实际 {max(have)}")
        missing = sorted(want - have)
        if missing:
            head = "、".join(str(x) for x in missing[:5])
            errors.append(f"V1 日期有缺口（共 {len(missing)} 天缺）：{head}{'…' if len(missing) > 5 else ''}——逐日补全")

    # V2 每日总量 ≤（声明可用 − 辅考预留）×1.2；未声明直接拒（先问用户再排）
    if weekday_min is None and weekend_min is None:
        errors.append("V2 用户还没声明每日可用时长（工作日/周末各几小时）——"
                      "先问出来并写进 save_exam_profile，再来生成计划")
    else:
        over = []
        for d, items in parsed:
            budget = (weekend_min if d.weekday() >= 5 else weekday_min) or 0
            cap = max(0, (budget - reserved_daily)) * CAP_RATIO
            total = sum(it["est"] for it in items)
            if total > cap:
                over.append(f"{d}：排了 {total} 分钟，上限约 {int(cap)}")
        if over:
            errors.append("V2 超出每日可用时长（含 1.2 容忍）——压缩或重排：" + "；".join(over[:5]))

    # V3 知识点防编造：给了 kp_ref 就必须真实存在于该用户该考试的节点表
    fake = sorted({it["kp_ref"] for _, items in parsed for it in items
                   if it["kp_ref"] is not None and it["kp_ref"] not in node_ids})
    if fake:
        errors.append(f"V3 这些 kp_ref 不在用户知识点账上（禁止编造）：{fake}——"
                      "只用 query_mastery/进度账里存在的节点 id，或省略 kp_ref")

    # V4 冲刺段：有且紧邻考试日，时长 14~35 天，段内只许 sprint/mock/review
    sprint_days = [d for d, items in parsed
                   if any(it["kind"] in ("sprint", "mock") for it in items)]
    if not sprint_days:
        errors.append("V4 没排冲刺段——考前 14~35 天必须是冲刺（sprint/mock/review 任务）")
    else:
        ss = min(sprint_days)
        span = (exam_date - ss).days
        if not SPRINT_MIN <= span <= SPRINT_MAX:
            errors.append(f"V4 冲刺段长 {span} 天，不在 14~35 天区间（BR-05）——调整冲刺起点 {ss}")
        bad = [f"{d}" for d, items in parsed if d >= ss
               for it in items if it["kind"] not in SPRINT_KINDS]
        if bad:
            errors.append(f"V4 冲刺段（{ss} 起）内混入学新任务：{'、'.join(sorted(set(bad))[:5])}——段内只许 sprint/mock/review")

    # V5 节奏：连续两天「当日占比最高科目」相同且占比≥60% → 拒
    tops = []
    for d, items in parsed:
        total = sum(it["est"] for it in items)
        by_subj = {}
        for it in items:
            by_subj[it["subject"] or "未标科目"] = by_subj.get(it["subject"] or "未标科目", 0) + it["est"]
        subj, mins = max(by_subj.items(), key=lambda kv: kv[1])
        tops.append((d, subj, mins / total if total else 0))
    for i in range(len(tops) - V5_RUN + 1):
        win = tops[i:i + V5_RUN]
        if len({s for _, s, _ in win}) == 1 and all(r >= V5_SHARE for _, _, r in win):
            errors.append(f"V5 {win[0][1]} 连续 {V5_RUN} 天高负载（{win[0][0]} 起，各占日量≥60%）——换换科目节奏")
            break

    # V6 不复习没学过的：kind=review 的条目，其节点掌握度不得为未接触（含无进度行）
    inv = [f"{d}/{it['kp_ref']}" for d, items in parsed for it in items
           if it["kind"] == "review" and it["kp_ref"] is not None
           and levels.get(it["kp_ref"], "未接触") == "未接触"]
    if inv:
        errors.append("V6 对未接触的知识点排了复习：" + "、".join(inv[:5])
                      + "——review 只排进度账里学过的；没学过的用 new/exercise")

    return errors
