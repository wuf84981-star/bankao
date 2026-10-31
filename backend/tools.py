# ============================================================
# 工具箱（tools.py）：伴考的"手"（S2 第三刀 · S3 引用刀扩编）
# 注册表形状：加一件工具只动两处——TOOLS 添一条说明书（给模型看），
# HANDLERS 添一个真函数（后端执行）。循环归编排层（main.py），本箱只管
# "有哪几件、各怎么执行"——PRD 12.6 十二件工具将来全部挂这一面墙。
# 处理器统一签名 (args, ctx)：args 是模型写的（不可信输入），ctx 是后端注入的
# （user_id/session/记账本）——"操作者 id 从票里来"老墙第一次撞上 function-call：
# 模型永远不能在自己的 arguments 里报"user_id=谁"，越权门从焊死。
# ============================================================
import json
import math
import re
from datetime import datetime, date, timezone

from sqlalchemy import text

from backend import mcp_client
from backend.plan_validator import KINDS, parse_shape, validate_plan

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEAK_BOOST_RATIO = 0.4   # F-30①：薄弱强化默认占 40% 题量（PRD「可调」现落常量，配置界面归后话）


def get_current_time(_args: dict, _ctx: dict | None = None) -> str:
    """BR-21：一切日期/星期/时刻问题查真历法，模型禁止心算。服务器本地时区。
    S4 首刀转正：ctx 带 session 时连考试档案一起报（每场在考考试的剩余天数+主辅
    标注，PRD 622）——倒计时从此是查数不是心算。ctx 缺席（旧调用形/单测裸跑）
    保持道具原样，不炸。"""
    now = datetime.now()
    out = f"当前时间：{now:%Y-%m-%d}（{WEEKDAYS[now.weekday()]}）{now:%H:%M:%S}"
    session = (_ctx or {}).get("session")
    if session is None:
        return out
    rows = session.execute(text(
        "SELECT exam_type, exam_date, is_primary FROM exam_profiles "
        "WHERE user_id = :u AND status = 'in-progress' ORDER BY exam_date"
    ), {"u": _ctx["user_id"]}).all()
    if not rows:
        return out + "\n考试档案：用户还没有登记任何考试（可用 save_exam_profile 登记）。"
    today = now.date()
    for r in rows:
        days = (r.exam_date - today).days
        tag = "主考" if r.is_primary else "辅考"
        if days > 0:
            line = f"{r.exam_type}（{tag}）{r.exam_date:%Y-%m-%d}，还剩 {days} 天"
        elif days == 0:
            line = f"{r.exam_type}（{tag}）今天开考"
        else:
            line = f"{r.exam_type}（{tag}）{r.exam_date:%Y-%m-%d} 已结束 {-days} 天"
        out += f"\n{line}"
    return out


def _minutes_or_none(v):
    """每日可用时长（分钟）参数洗伤：坏值/越界一律当没传（None→更新时保旧值）。"""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= 16 * 60 else None


def save_exam_profile(args: dict, ctx: dict) -> str:
    """登记/更新考试档案（PRD 658 · BR-21 的数据源）：同 exam_type 再存=更新
    （防模型复述同话时立双胎行）。首场考试自动主考——这个判断收在后端，
    不劳模型操心；之后只有用户明说"以此为主考"才传 is_primary=true，
    晋级前先降旧主（让位在写入端做，DB 部分唯一索引 uq_exam_profiles_primary
    是代码有 bug 时的兜底闸）。user_id 从 ctx 票里来，模型碰不到（S3 引用刀同款）。"""
    session, uid = ctx["session"], ctx["user_id"]
    exam_type = str(args.get("exam_type", "")).strip()[:32]
    date_s = str(args.get("exam_date", "")).strip()
    if not exam_type or not date_s:
        return "缺 exam_type 或 exam_date（YYYY-MM-DD），请补全后重新调用。"
    try:
        exam_date = datetime.strptime(date_s, "%Y-%m-%d").date()
    except ValueError:
        return f"exam_date 无法解析：『{date_s}』——请给 YYYY-MM-DD 格式的具体日期。"
    if exam_date < date.today():
        return f"{exam_type} 的日期 {date_s} 已过去——确认下是不是年份说岔了？"
    is_primary = bool(args.get("is_primary", False))
    existing = session.execute(text(
        "SELECT id, is_primary FROM exam_profiles WHERE user_id = :u AND exam_type = :t"),
        {"u": uid, "t": exam_type}).first()
    if not session.scalar(text(
            "SELECT count(*) FROM exam_profiles WHERE user_id = :u"), {"u": uid}):
        is_primary = True   # 库里没考试：首场自动主考，模型没传也升
    elif existing and "is_primary" not in args:
        is_primary = existing.is_primary   # 更新时没明说主辅：保留原角色（改日期≠挪主考）
    if is_primary:
        session.execute(text(
            "UPDATE exam_profiles SET is_primary = false "
            "WHERE user_id = :u AND is_primary AND id IS DISTINCT FROM :keep"),
            {"u": uid, "keep": existing.id if existing else None})   # 更新自己时别把自己降了
    if existing:
        session.execute(text(
            "UPDATE exam_profiles SET exam_date = :d, target_desc = :g, is_primary = :p, "
            "weekly_reserved_minutes = :w, "
            "weekday_minutes = COALESCE(:wdm, weekday_minutes), "
            "weekend_minutes = COALESCE(:wem, weekend_minutes) WHERE id = :id"),
            {"d": exam_date, "g": args.get("target_desc"), "p": is_primary,
             "w": int(args.get("weekly_reserved_minutes") or 0), "id": existing.id,
             "wdm": _minutes_or_none(args.get("weekday_minutes")),
             "wem": _minutes_or_none(args.get("weekend_minutes"))})
        act = "更新"
    else:
        session.execute(text(
            "INSERT INTO exam_profiles (user_id, exam_type, exam_date, target_desc, "
            "is_primary, weekly_reserved_minutes, weekday_minutes, weekend_minutes, "
            "status, created_at) "
            "VALUES (:u, :t, :d, :g, :p, :w, :wdm, :wem, 'in-progress', now())"),
            {"u": uid, "t": exam_type, "d": exam_date, "g": args.get("target_desc"),
             "p": is_primary, "w": int(args.get("weekly_reserved_minutes") or 0),
             "wdm": _minutes_or_none(args.get("weekday_minutes")),
             "wem": _minutes_or_none(args.get("weekend_minutes"))})
        act = "登记"
    session.commit()
    days = (exam_date - date.today()).days
    tag = "主考" if is_primary else "辅考"
    return (f"已{act}：{exam_type} {exam_date:%Y-%m-%d}（{tag}，还剩 {days} 天）。"
            "请向用户复述确认，不要自行推算日期。")


# D80 起家（2026-10-12 用户拍甲）、D82 升格两轨共闸（2026-10-18 再拍甲）：
# 票面以嘴为准——检索放行（分数裁判）≠ 模型认账（内容裁判），正文标过的
# 才配进票面，账永不替嘴撒谎（10-18 党史轮真机复发案：摆 5 票正文只用 3）。
# 函数与票据记账本同住一家：ref 读法两轨兼容——票自带 ref 用 ref
# （教学轨 retrieve 编号），没带用位次（本箱喂模型时的 enumerate 位次即票号）。
_REF_MARK = re.compile(r"\[ref\s*(\d+)\]|\[(\d+)\]")


def cited_by_reply(citations: list, reply: str) -> list:
    """只留正文标注过的票（[ref N]/[N] 双写法容忍漏写 ref）。"""
    used = {int(a or b) for a, b in _REF_MARK.findall(reply)}
    return [c for i, c in enumerate(citations, start=1)
            if (c.get("ref") or i) in used]


def search_materials(args: dict, ctx: dict) -> str:
    """检索用户资料库（PRD 619：强制 user_id 过滤——票里来，不在 args 里）。
    捞回的块喂模型带 ref 编号；出处同步记进 ctx["citations"]（引用落库靠这份账，
    不靠回读模型正文）。零命中给 632 行要求的实话提示；降级人话原样转达。"""
    from backend.search import search   # 延迟导入：工具箱不拖着 DB 层下水
    from backend.gaps import GAP_WEAK, record_gap   # S9·W3 缺口账（旁路，永不拖垮答题）

    query = str(args.get("query", "")).strip()
    if not query:
        return "检索词为空：请在 query 里给出完整问句后重新调用。"
    # D82 甲（2026-10-18 用户拍板）：不再自带 top_k=5 抄第二份——随 search 的
    # TOP_K 常量单源（现为 2），评测证 answers 全在 top3，摆牌从源头就少。
    r = search(ctx["session"], query, ctx["user_id"])
    if not r["results"]:
        # S9·W3：讲义查无——旁路记一笔 zero（record_gap 自吞异常，炸不了这里）
        record_gap(ctx["user_id"], query, None, ctx.get("channel", "web"))
        # D59 乙 2026-09-11（用户改口径）：讲义没有时的两条兜底路（联网、通用常识）
        # 同挂这一个开关——关着就只报实话，开着才准联网、才准常识兜底。
        if web_allowed(ctx["session"], ctx["user_id"]):
            out = {"found": 0,
                   "note": "用户资料库里没有找到相关内容。请基于通用知识回答，"
                           "并明确告知用户『资料中未找到相关内容』（PRD 632 防幻觉）。"
                           "用户已开启联网搜索：可再调 web_search 查实时资料，"
                           "届时开头注明『来自网络』并附链接。"}
        else:
            out = {"found": 0,
                   "note": "用户资料库里没有找到相关内容，且用户未开启联网搜索——"
                           "请直接回复『知识库无相关资料』，不要用通用常识作答这道题"
                           "（该用户只想学自己讲义里的内容）。与考点无关的操作"
                           "（时间、计划、打卡、闲聊）不受此限。"}
        return json.dumps(out, ensure_ascii=False)
    # S9·W3：有命中但向量最高分低于登记线=擦边（weak）——进待补账。
    # 向量腿离线时 top_vec 为空，宁缺毋滥不登记。
    tv = r.get("top_vec")
    if tv is not None and tv < GAP_WEAK:
        record_gap(ctx["user_id"], query, tv, ctx.get("channel", "web"))
    cited = ctx["citations"]
    materials = []
    for item in r["results"]:
        if not any(c["chunk_id"] == item["id"] for c in cited):
            cited.append({"chunk_id": item["id"], "material_id": item["material_id"],
                          "title": item["title"], "seq": item["seq"]})
        ref = next(n for n, c in enumerate(cited, start=1) if c["chunk_id"] == item["id"])
        materials.append({"ref": ref, "title": item["title"],
                          "seq": item["seq"], "content": item["content"]})
    out = {"found": len(materials), "materials": materials,
           "rule": "引用了哪块材料，就在对应句子末尾标注其 ref 编号，如……[1]。"}
    if r["degraded"]:
        out["degraded"] = r["degraded"]   # 让模型能说清"资料库还没完全通电"这种实话
    return json.dumps(out, ensure_ascii=False)


# ── S8 D58 甲：联网搜索兜底腿（Tavily · 2026-09-11 用户拍板「新增联网工具用 Tavily」）──
# 三件套各守一层：web_allowed=闸的账（一查）；tools_for=组装器（工具在场性闸）；
# web_search=腿本体（handler 内再查账兜底）。开关语义钉死——
# 关：模型根本看不见 web_search（形状即执法，不是「劝它别用」），行为与旧版逐字相同；
# 开：工具进 schema，资料库零命中时 note 引导模型举手，联网答案必须带「来自网络」声明。

def web_allowed(session, uid: int) -> bool:
    """用户是否开了联网（agent_settings 账；无行=默认关）——
    「只有用户打开开关才会联网」写进数据默认值，不靠 prompt 自觉。"""
    return bool(session.scalar(text(
        "SELECT web_search_enabled FROM agent_settings WHERE user_id = :u"), {"u": uid}))


def model_for(session, uid: int) -> str:
    """D60 甲 2026-09-11：本户用哪个脑子想（agent_settings.model_choice 账）。
    无行/脏名一律 resolve_model 兜向默认——默认值活在 llm.py 一处，不冻进历史账行。
    账查询放本箱与 web_allowed 同家法：orchestrator→tools 的 import 方向不许倒。"""
    from backend.llm import resolve_model   # 延迟 import：工具箱不拖电厂下水
    return resolve_model(session.scalar(text(
        "SELECT model_choice FROM agent_settings WHERE user_id = :u"), {"u": uid}))


def own_key_for(session, uid: int, model: str) -> str | None:
    """BYOK（2026-10-31）：本户选的这个脑子该不该带自带的钥匙。
    语义钉死：只有「钥匙在册 且 当前型号落 DeepSeek 平台」才给钥匙——
    换到通义/智谱型号，自带钥匙自动失效回平台路（dashscope/zhipu 不吃它，拍板）。
    ⓪⚠ 返回值是本户明文钥匙，只准就地传给电厂 get_client，永不回显、永不进日志、
    永不进 SQL 之外的账表；查询走参数化，user_id 票闸同家法。"""
    from backend.llm import platform_of   # 延迟 import：model_for 同款规矩
    if platform_of(model) != "deepseek":
        return None
    return session.scalar(text(
        "SELECT own_deepseek_key FROM agent_settings WHERE user_id = :u"), {"u": uid})


def tools_for(session, uid: int) -> list[dict]:
    """一轮对话的工具集（两腿共用的唯一真源）：常规工具人人有；
    web_search 按开关随行就市——关着就不进 schema，模型无从举手，不烧一分。"""
    return TOOLS + (WEB_TOOLS if web_allowed(session, uid) else [])


def web_search(args: dict, ctx: dict) -> str:
    """查一次网络（D58 甲）。双闸：tools_for 不挂是首闸、这里查账是兜底闸
    （假想模型凭旧上下文幻觉举手——账上没开照样拒,不烧钱）。
    一切外联故障（缺 key/超时/配额尽）转人话不外包：兜底腿不许拖垮主流程。"""
    if not web_allowed(ctx["session"], ctx["user_id"]):
        return json.dumps({"err": "closed",
                           "note": "用户未开启联网搜索——本腿不可用，请基于已有资料回答"},
                          ensure_ascii=False)
    query = str(args.get("query", "")).strip()
    if not query:
        return "检索词为空：请在 query 里给出完整搜索问句后重新调用。"
    from backend.websearch import tavily_search   # 延迟 import：工具箱不拖着外联网腿下水
    try:
        r = tavily_search(query)
    except Exception as e:
        return json.dumps({"err": "web",
                           "note": f"联网搜索腿故障或没配钥匙（{str(e)[:100]}），请如实告知用户"},
                          ensure_ascii=False)
    hits = [{"title": h.get("title", ""), "url": h.get("url", ""),
             "snippet": (h.get("content") or "")[:500]} for h in r["results"][:5]]
    out = {"found": len(hits), "hits": hits,
           "rule": "这批是网络实时资料、不是用户讲义——回答第一句必须声明『来自网络』；"
                   "借了哪条说法就在句后附其 url；不进资料库引用账（citations 不记）。"}
    if r.get("answer"):
        out["answer"] = r["answer"]   # 搜索引擎侧摘要，供参考不背书
    return json.dumps(out, ensure_ascii=False)


# ── S4 第二刀：偏好档案三只手（PRD 6.3/6.4/3.2 · D10 甲案 BR-02 轻版闭环）──

MEMORY_CATEGORIES = ("profile", "goal", "habit", "emotion_long")


def save_memory(args: dict, ctx: dict) -> str:
    """存用户档案事实（memory_facts 三键 upsert）。BR-02 后端强制闸：
    source=inferred 一律 confirmed=false——注入排除、不生效，只在查询里以
    【推测待确认】露面；用户亲口说"对"，模型以 user_stated 重存同 key 即自动
    升格生效（复用 upsert，零新机制）。确认与否不由模型嘴上说，DB 字段说话。"""
    session, uid = ctx["session"], ctx["user_id"]
    category = str(args.get("category", "")).strip()
    key = str(args.get("key", "")).strip()[:64]
    content = str(args.get("content", "")).strip()
    source = str(args.get("source", "user_stated")).strip()
    if category not in MEMORY_CATEGORIES:
        return f"category 只认 {'/'.join(MEMORY_CATEGORIES)}，收到『{category}』——请改正重调。"
    if not key or not content:
        return "key 与 content 都不能为空，请补全后重新调用。"
    if source not in ("user_stated", "inferred"):
        return "source 只认 user_stated（用户亲口说）或 inferred（你的推测），请重调。"
    confirmed = source == "user_stated"
    existing = session.scalar(text(
        "SELECT id FROM memory_facts WHERE user_id = :u AND category = :c AND key = :k"),
        {"u": uid, "c": category, "k": key})
    if existing:
        session.execute(text(
            "UPDATE memory_facts SET content = :v, source = :s, confirmed = :f, "
            "updated_at = now() WHERE id = :id"),
            {"v": content, "s": source, "f": confirmed, "id": existing})
        act = "更新"
    else:
        session.execute(text(
            "INSERT INTO memory_facts (user_id, category, key, content, source, confirmed, "
            "updated_at, created_at) VALUES (:u, :c, :k, :v, :s, :f, now(), now())"),
            {"u": uid, "c": category, "k": key, "v": content, "s": source, "f": confirmed})
        act = "记下"
    session.commit()
    tail = "" if confirmed else "【推测·未生效，需用户亲口确认】"
    return f"已{act}记忆（{category}/{key}）：{content}{tail}"


def query_memories(args: dict, ctx: dict) -> str:
    """"你记住了我什么"（PRD 338/1090）：分组清单必须区分
    【你告诉过我的】/【我推测待确认的】——source 徽章是这功能的名誉条款。
    第四刀扩权（PRD 14.5）：汇总还要带学习进度组——单查即全貌。"""
    session, uid = ctx["session"], ctx["user_id"]
    category = str(args.get("category", "")).strip()
    if category and category not in MEMORY_CATEGORIES:
        return f"category 只认 {'/'.join(MEMORY_CATEGORIES)}（或留空查全部）。"
    where = "WHERE user_id = :u" + (" AND category = :c" if category else "")
    rows = session.execute(text(
        f"SELECT category, key, content, confirmed FROM memory_facts {where} "
        "ORDER BY category, key"), {"u": uid, "c": category}).all()
    name = session.scalar(text(
        "SELECT agent_name FROM agent_settings WHERE user_id = :u"), {"u": uid})
    prog = session.execute(text(
        "SELECT n.name, m.exam_type, m.level, m.confidence FROM knowledge_mastery m "
        "JOIN knowledge_nodes n ON n.id = m.kp_ref WHERE m.user_id = :u "
        "ORDER BY m.exam_type, n.name"), {"u": uid}).all()
    stated = [{"类别": r.category, "项": r.key, "内容": r.content}
              for r in rows if r.confirmed]
    inferred = [{"类别": r.category, "项": r.key, "内容": r.content}
                for r in rows if not r.confirmed]
    progress = [{"知识点": r.name, "考试": r.exam_type, "等级": r.level,
                 "置信度": r.confidence} for r in prog]
    return json.dumps({"你告诉过我的": stated, "我推测待确认的": inferred,
                       "学习进度": progress,
                       "对你的称呼设定": name or "（未起名）",
                       "rule": "转述时保持两组区分；待确认组只问不替用户下定论"},
                      ensure_ascii=False)


def forget_memory(args: dict, ctx: dict) -> str:
    """物理删除（PRD 614/727 · BR-07）：合法命中**必删，不设判断闸**——
    建节点要讨确认、删除不要，这个不对称是故意的（用户说忘=最终决定，
    删错的责任归主权方）。唯一例外=多命中时先列候选不落刀（PRD 14.5
    「同义条目多处存在→请用户确认范围」），防的不是拒绝而是拿错范围。
    删除即 DELETE，无软删标记可留（727「不能偷偷保留」）；
    删进度只删 mastery 行、节点保留（将来重报复用）；
    审计轻版=日志一行「何时删了哪些 id」不记内容（正式埋点归 S7）。
    越权门：候选定位天然按票过滤，但模型回传的 ids 同样不可信——
    每条 DELETE 都带 user_id 闸，编造别户 id 删不动。"""
    session, uid = ctx["session"], ctx["user_id"]
    query = str(args.get("query", "")).strip()
    if not query:
        return "query 为空——请带回用户想忘掉的内容描述再调。"
    target = str(args.get("target", "auto")).strip()
    if target not in ("auto", "memory", "progress"):
        return "target 只认 auto/memory/progress，请重调。"
    like = f"%{query}%"
    hits = []   # (kind, id, label)
    if target in ("auto", "memory"):
        for r in session.execute(text(
                "SELECT id, category, key, left(content, 40) AS c FROM memory_facts "
                "WHERE user_id = :u AND (key ILIKE :q OR content ILIKE :q) "
                "ORDER BY category, key"), {"u": uid, "q": like}).all():
            hits.append(("memory", r.id, f"档案[{r.category}] {r.key}：{r.c}"))
    if target in ("auto", "progress"):
        for r in session.execute(text(
                "SELECT m.id, n.name, m.exam_type, m.level FROM knowledge_mastery m "
                "JOIN knowledge_nodes n ON n.id = m.kp_ref "
                "WHERE m.user_id = :u AND n.name ILIKE :q ORDER BY n.name"),
                {"u": uid, "q": like}).all():
            hits.append(("progress", r.id, f"进度 {r.exam_type}/{r.name}（{r.level}）"))
    mem_ids = [int(i) for i in (args.get("memory_ids") or [])]
    prog_ids = [int(i) for i in (args.get("mastery_ids") or [])]
    if not mem_ids and not prog_ids:
        if not hits:
            # 不拒绝≠谎报删除：账上真没有，就如实说没有
            return f"账上没有任何与『{query}』相关的记录——无需遗忘，也不会删错东西。"
        if len(hits) > 1:
            return json.dumps({
                "多条相似命中": [{"kind": k, "id": i, "内容": lb} for k, i, lb in hits],
                "rule": "向用户列出这些条目并确认删除范围；确认后按命中类别回传 "
                        "memory_ids / mastery_ids 重新调用。未确认前不要再调本工具。"},
                ensure_ascii=False)
        mem_ids = [i for k, i, _ in hits if k == "memory"]
        prog_ids = [i for k, i, _ in hits if k == "progress"]
    deleted = []
    for i in mem_ids:
        n = session.execute(text(
            "DELETE FROM memory_facts WHERE id = :i AND user_id = :u"),
            {"i": i, "u": uid}).rowcount
        deleted += [f"memory:{i}"] * n
    for i in prog_ids:
        n = session.execute(text(
            "DELETE FROM knowledge_mastery WHERE id = :i AND user_id = :u"),
            {"i": i, "u": uid}).rowcount
        deleted += [f"mastery:{i}"] * n
    session.commit()
    print(f"[forget] user={uid} deleted={deleted}", flush=True)   # 727 审计轻版：只记 id
    if not deleted:
        return ("没有删掉任何条目——给的 id 在该户账上不存在（可能已被删或不属于本户）。"
                "请重新 query 定位后确认。")
    return (f"已删除 {len(deleted)} 条，之后不再使用：{deleted}。"
            "请向用户复述删掉了哪些内容，让用户确认没删错、没漏删。")


def set_agent_name(args: dict, ctx: dict) -> str:
    """3.2 命名系统：用户给 Agent 起名→ agent_settings 一户一行 upsert。
    名字进表后 _system_for 每轮注入自称指令——记住名字也不靠模型记性。"""
    session, uid = ctx["session"], ctx["user_id"]
    name = str(args.get("name", "")).strip()[:32]
    if not name:
        return "name 为空——请带回用户想叫你的名字再调。"
    updated = session.execute(text(
        "UPDATE agent_settings SET agent_name = :n WHERE user_id = :u"),
        {"n": name, "u": uid}).rowcount
    if not updated:
        session.execute(text(
            "INSERT INTO agent_settings (user_id, agent_name) VALUES (:u, :n)"),
            {"u": uid, "n": name})
    session.commit()
    return f"已存入永久设定：从现在起我叫『{name}』。"


def set_remind_time(args: dict, ctx: dict) -> str:
    """S6 二刀（F-33/D24 甲）：每日提醒时点落 agent_settings.remind_time——
    S4 建表留的空列在此上户口。到点开口的是调度器不是模型，本手只改账。"""
    session, uid = ctx["session"], ctx["user_id"]
    t = str(args.get("time", "")).strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", t):
        return "时间没看懂——要 HH:MM 24 小时制（如 21:30），先把用户的话换算清楚再调。"
    hh, mm = (int(x) for x in t.split(":"))
    if hh > 23 or mm > 59:
        return f"{t} 不是合法钟点——小时 0~23、分钟 0~59。"
    norm = f"{hh:02d}:{mm:02d}"
    updated = session.execute(text(
        "UPDATE agent_settings SET remind_time = :t WHERE user_id = :u"),
        {"t": norm, "u": uid}).rowcount
    if not updated:
        session.execute(text(
            "INSERT INTO agent_settings (user_id, remind_time) VALUES (:u, :t)"),
            {"u": uid, "t": norm})
    session.commit()
    return (f"提醒时间已落账：每天 {norm}。到点系统自动读当日计划发提醒，不烧模型——"
            "用户想再改或问现在几点提醒，报这个账；没设置过的户按默认 20:00 走。")


# ── S4 第三刀：学习进度两手（PRD 694/759 · D9 甲案平铺一层）──

MASTERY_LEVELS = ("未接触", "初步了解", "一般掌握", "熟练", "薄弱")


def _default_exam(session, uid: int) -> str | None:
    """进度账挂靠规则：没明说考试就归主考——判断收后端（首场自动主考同款刀法）。"""
    return session.scalar(text(
        "SELECT exam_type FROM exam_profiles "
        "WHERE user_id = :u AND is_primary AND status = 'in-progress'"), {"u": uid})


def update_mastery(args: dict, ctx: dict) -> str:
    """学习汇报落账（PRD 14.2 场景）：知识点无节点时**不擅建**——回人话让模型
    向用户讨一句确认，确认后带 create_node=true 重调（确认语义在往返里，不新造机制）。
    同 (exam,kp) 再报=upsert 改级（一知识点一行，DB 唯一闸兜底）。"""
    session, uid = ctx["session"], ctx["user_id"]
    kp_name = str(args.get("kp_name", "")).strip()[:128]
    level = str(args.get("level", "")).strip()
    if not kp_name:
        return "kp_name 不能为空——请带回用户说的知识点再调。"
    if level not in MASTERY_LEVELS:
        return f"level 只认 {'/'.join(MASTERY_LEVELS)} 五档，收到『{level}』——请改判重调。"
    conf = args.get("confidence")
    if conf is not None:
        try:
            conf = int(conf)
        except (TypeError, ValueError):
            return f"confidence 需是 0~100 整数，收到『{conf}』——请重调。"
        if not 0 <= conf <= 100:
            return f"confidence 超出 0~100：{conf}——请修正重调。"
    exam_type = str(args.get("exam_type", "")).strip()[:32] or _default_exam(session, uid)
    if not exam_type:
        return ("用户还没有考试档案，进度账不知挂靠——"
                "请先引导用户用 save_exam_profile 登记考试，或本调用显式传 exam_type。")
    subject = str(args.get("subject", "")).strip()[:64] or None
    node_id = session.scalar(text(
        "SELECT id FROM knowledge_nodes WHERE user_id = :u AND exam_type = :e "
        "AND name = :n AND parent_id IS NULL"), {"u": uid, "e": exam_type, "n": kp_name})
    if not node_id:
        if not args.get("create_node"):
            return (f"『{kp_name}』在 {exam_type} 下还没有知识点节点。"
                    "请先向用户确认是否新增该知识点（PRD 14.2）；"
                    "得到确认后带 create_node=true 重新调用——不要擅自建节点。")
        node_id = session.scalar(text(
            "INSERT INTO knowledge_nodes (user_id, exam_type, subject, parent_id, name, "
            "source, sort, created_at) VALUES (:u, :e, :s, NULL, :n, 'user_edit', 0, now()) "
            "RETURNING id"), {"u": uid, "e": exam_type, "s": subject, "n": kp_name})
    existing = session.execute(text(
        "SELECT id, level, confidence FROM knowledge_mastery "
        "WHERE user_id = :u AND exam_type = :e AND kp_ref = :k"),
        {"u": uid, "e": exam_type, "k": node_id}).first()   # 多列必用 execute().first()：scalar 只给首列
    note = str(args.get("note", "")).strip() or None
    if existing:
        session.execute(text(
            "UPDATE knowledge_mastery SET level = :l, subject = COALESCE(:s, subject), "
            "confidence = COALESCE(:c, confidence), user_note = COALESCE(:n, user_note), "
            "last_learned_at = now() WHERE id = :id"),
            {"l": level, "s": subject, "c": conf, "n": note, "id": existing.id})
        act = f"更新（原 {existing.level}/{existing.confidence}）"
    else:
        session.execute(text(
            "INSERT INTO knowledge_mastery (user_id, exam_type, subject, kp_ref, level, "
            "confidence, user_note, last_learned_at) "
            "VALUES (:u, :e, :s, :k, :l, COALESCE(:c, 50), :n, now())"),
            {"u": uid, "e": exam_type, "s": subject, "k": node_id, "l": level,
             "c": conf, "n": note})
        act = "新建"
    session.commit()
    return (f"进度已{act}：{exam_type} / {kp_name} → {level}"
            f"（confidence {conf if conf is not None else 50}）。"
            "请向用户复述这个等级判断；若用户纠正，直接以新 level 重存同知识点。")


def query_mastery(args: dict, ctx: dict) -> str:
    """「我哪块最弱/进度如何」（PRD 338 学习画像入口）：薄弱与未接触前置、
    confidence 升序——排序即画像，不给模型编印象的机会。"""
    session, uid = ctx["session"], ctx["user_id"]
    exam_type = str(args.get("exam_type", "")).strip()[:32] or None
    subject = str(args.get("subject", "")).strip()[:64] or None
    where = "WHERE m.user_id = :u"
    q = {"u": uid}
    if exam_type:
        where += " AND m.exam_type = :e"; q["e"] = exam_type
    if subject:
        where += " AND m.subject = :s"; q["s"] = subject
    rows = session.execute(text(
        f"SELECT n.name, m.exam_type, m.subject, m.level, m.confidence, m.last_learned_at "
        f"FROM knowledge_mastery m JOIN knowledge_nodes n ON n.id = m.kp_ref {where} "
        "ORDER BY CASE WHEN m.level IN ('薄弱','未接触') THEN 0 ELSE 1 END, "
        "m.confidence ASC, n.name"), q).all()
    if not rows:
        return json.dumps({"found": 0,
                           "note": "还没有任何学习进度记录。等用户汇报学习后用 "
                                   "update_mastery 落账，或如实说账上暂无。"},
                          ensure_ascii=False)
    items = [{"知识点": r.name, "考试": r.exam_type, "科目": r.subject or "未标",
              "等级": r.level, "置信度": r.confidence,
              "最近学习": f"{r.last_learned_at:%m-%d}" if r.last_learned_at else "无记录"}
             for r in rows]
    return json.dumps({"found": len(items), "学习进度": items,
                       "rule": "排序=薄弱在前，转述时按账说话，不要额外贴『薄弱』标签吓唬用户"},
                      ensure_ascii=False)


# ── S5 第一刀：计划生成与激活（PRD F-22/23.4 · D12 往返甲案 · D13 纯函数校验器）──

def generate_plan(args: dict, ctx: dict) -> str:
    """接住模型吐的逐日计划 JSON → V1~V6 硬校验 → 全过落**草案**。
    设计关窍三枚：①校验器是纯函数（plan_validator），真值由这里查库喂参——
    V3 防编造吃的是 knowledge_nodes 真实 id 集，模型编的知识点名过不了 DB 眼；
    ②落库只到 draft（D12 往返，create_node 同形）：用户点头前计划不生效，
    防模型自说自话「计划排好了照着学」；③校验失败原样回错误清单——
    重排是模型的活，落不落库是代码的闸，两边职责焊死（23.4 确定性原则）。"""
    session, uid = ctx["session"], ctx["user_id"]
    prof = session.execute(text(
        "SELECT exam_type, exam_date, weekday_minutes, weekend_minutes FROM exam_profiles "
        "WHERE user_id = :u AND is_primary AND status = 'in-progress'"), {"u": uid}).first()
    if not prof:
        return ("还没有在考的主考档案，计划无从排起——请先引导用户用 "
                "save_exam_profile 登记考试类型与日期。")
    reserved = float(session.scalar(text(
        "SELECT COALESCE(sum(weekly_reserved_minutes), 0) FROM exam_profiles "
        "WHERE user_id = :u AND NOT is_primary AND status = 'in-progress'"), {"u": uid}) or 0) / 7.0
    node_ids = {r.id for r in session.execute(text(
        "SELECT id FROM knowledge_nodes WHERE user_id = :u AND exam_type = :e"),
        {"u": uid, "e": prof.exam_type}).all()}
    levels = {r.kp_ref: r.level for r in session.execute(text(
        "SELECT kp_ref, level FROM knowledge_mastery WHERE user_id = :u AND exam_type = :e"),
        {"u": uid, "e": prof.exam_type}).all()}

    parsed, shape_errs = parse_shape(args.get("days"))
    if shape_errs:
        return json.dumps({"形状不合格": shape_errs,
                           "rule": "days 必须逐日 {date, items[{date 内唯一, task, est_minutes, kind, 可选 kp_ref/subject}]}——改正后重传完整计划"},
                          ensure_ascii=False)
    errors = validate_plan(parsed, exam_date=prof.exam_date,
                           weekday_min=prof.weekday_minutes, weekend_min=prof.weekend_minutes,
                           reserved_daily=reserved, node_ids=node_ids, levels=levels)
    if errors:
        return json.dumps({"校验未通过": errors,
                           "rule": "逐条改正后带完整 days 重新调用 generate_plan；"
                                   "禁止部分落库、禁止绕过校验、禁止对用户宣称计划已完成。"
                                   "连续失败 3 次就向用户说明排期困难（要不要调整考试日期或每日时长）"},
                          ensure_ascii=False)

    # 全过才走到这：旧草案/旧生效版留档，version+1，新草案入库（items 批量）
    session.execute(text(
        "UPDATE plans SET status = 'archived' "
        "WHERE user_id = :u AND exam_type = :e AND status IN ('draft', 'active')"),
        {"u": uid, "e": prof.exam_type})
    version = session.scalar(text(
        "SELECT COALESCE(max(version), 0) + 1 FROM plans WHERE user_id = :u AND exam_type = :e"),
        {"u": uid, "e": prof.exam_type})
    start = parsed[0][0]
    sprint_start = min(d for d, items in parsed
                       if any(it["kind"] in ("sprint", "mock") for it in items))
    pid = session.scalar(text(
        "INSERT INTO plans (user_id, exam_type, start_date, sprint_start_date, status, "
        "version, created_at) VALUES (:u, :e, :s, :ss, 'draft', :v, now()) RETURNING id"),
        {"u": uid, "e": prof.exam_type, "s": start, "ss": sprint_start, "v": version})
    session.execute(text(
        "INSERT INTO plan_items (plan_id, user_id, date, subject, kp_ref, task_desc, "
        "est_minutes, kind, status) VALUES (:pid, :u, :d, :subj, :kp, :task, :est, :kind, 'pending')"),
        [{"pid": pid, "u": uid, "d": d, "subj": it["subject"] or None, "kp": it["kp_ref"],
          "task": it["task"], "est": it["est"], "kind": it["kind"]}
         for d, items in parsed for it in items])   # kind 落库=第三刀 D20 补账（首刀用完即弃）
    session.commit()
    n_items = sum(len(i) for _, i in parsed)
    avg = sum(it["est"] for _, items in parsed for it in items) // len(parsed)
    preview = [{"日期": str(d), "任务": [f"{it['task']}（{it['est']}分）" for it in items]}
               for d, items in parsed[:3]]
    return json.dumps({
        "plan_id": pid, "状态": f"草案 v{version}（未生效）", "总天数": len(parsed),
        "总条目": n_items, "日均分钟": avg, "冲刺起点": str(sprint_start),
        "距考试": (prof.exam_date - date.today()).days, "前三日样例": preview,
        "rule": "把计划向用户完整展示（含剩余天数）并询问是否激活；"
                "用户明确说要，才调用 activate_plan(plan_id)；用户要改就按反馈重排再生成"},
        ensure_ascii=False)


def activate_plan(args: dict, ctx: dict) -> str:
    """草案转正（F-22 流程末步「用户确认激活」的执行体）：只认本户 draft——
    plan_id 是模型回传的，照旧过 user_id 票闸（S4 第四刀铁律：模型给的目标不可信）。
    激活即换版：本场旧 active 归档，plan_change_logs 记一行（谁批的、批的哪版）。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        pid = int(args.get("plan_id"))
    except (TypeError, ValueError):
        return "plan_id 缺失或不是整数——带回 generate_plan 返回的 plan_id 重调。"
    row = session.execute(text(
        "SELECT p.id, p.status, p.version, p.exam_type, p.start_date, "
        "p.sprint_start_date, e.exam_date FROM plans p "
        "JOIN exam_profiles e ON e.user_id = p.user_id AND e.exam_type = p.exam_type "
        "WHERE p.id = :i AND p.user_id = :u"), {"i": pid, "u": uid}).first()
    if not row:
        return "本户账上没有这份计划（id 过不了 user_id 闸或已被删）——请先生成再激活。"
    if row.status == "active":
        return f"第 {pid} 号计划已是生效状态，无需重复激活。"
    if row.status != "draft":
        return f"第 {pid} 号计划状态是 {row.status}（已归档），激活不了——需要就重新 generate_plan。"
    session.execute(text(
        "UPDATE plans SET status = 'archived' WHERE user_id = :u AND exam_type = :e "
        "AND status = 'active'"), {"u": uid, "e": row.exam_type})
    session.execute(text("UPDATE plans SET status = 'active' WHERE id = :i"), {"i": pid})
    today = date.today()
    todays = session.execute(text(
        "SELECT task_desc, est_minutes FROM plan_items WHERE plan_id = :p AND date = :d "
        "ORDER BY id"), {"p": pid, "d": today}).all()
    session.execute(text(
        "INSERT INTO plan_change_logs (plan_id, user_id, actor, reason, snapshot, created_at) "
        "VALUES (:p, :u, 'user', '用户确认激活', :s, now())"),
        {"p": pid, "u": uid, "s": json.dumps({"version": row.version, "from": "draft"},
                                             ensure_ascii=False)})
    session.commit()
    left = (row.exam_date - today).days
    done = f"今日（{today:%m-%d}）任务 {len(todays)} 条：" + "；".join(f"{t.task_desc}（{t.est_minutes}分）" for t in todays[:4]) if todays else f"今日（{today:%m-%d}）无排定任务（空档日）"
    return (f"计划 v{row.version} 已生效（{row.exam_type}，{row.start_date} 起，"
            f"冲刺 {row.sprint_start_date} 起，距考试 {left} 天）。{done}。"
            "请向用户复述生效状态与今日任务。")


def report_check_in(args: dict, ctx: dict) -> str:
    """打卡消化（F-23 · S5 第二刀 · D16 甲案一只批量手）：用户亲口汇报
    「今天学完了/学了一部分」→ 把生效计划当日 pending 条置 done/partial。
    三条铁律：①指令的主语是用户的嘴——用户没说完成就不许调（替用户打卡=编造事实）；
    ②漏卡不设本手——保持 pending 由计划账次日提醒补录，不自动判失败（F-23②）；
    ③不自动升掌握度（D18 甲）：回执只列今日涉及节点现档，改不改跟用户商量，
    点头才走 update_mastery——把 F-28 跨级确认的规矩平移进打卡。"""
    session, uid = ctx["session"], ctx["user_id"]
    status = str(args.get("status", "")).strip()
    if status not in ("done", "partial"):
        return "status 只认 done（完成）或 partial（部分完成）——没学/漏打卡不必调本手，" \
               "保持 pending 次日提醒补录即可（F-23②：漏卡不判失败）。"
    try:
        d = datetime.strptime(str(args.get("date") or date.today()), "%Y-%m-%d").date()
    except ValueError:
        return "date 须是 YYYY-MM-DD（省略=今天）。"
    if not session.scalar(text("SELECT 1 FROM plans WHERE user_id = :u AND status = 'active' LIMIT 1"),
                          {"u": uid}):
        return "本户没有生效中的计划，无从打卡——先按流程问用户要不要排计划。"
    items_arg = args.get("item_ids")
    base = ("SELECT i.id, i.task_desc, i.kp_ref FROM plan_items i "
            "JOIN plans p ON p.id = i.plan_id "
            "WHERE i.user_id = :u AND i.status = 'pending' AND p.status = 'active' ")
    if items_arg in (None, "", "all", ["all"]):
        rows = session.execute(text(base + "AND i.date = :d ORDER BY i.id"),
                               {"u": uid, "d": d}).all()
    else:
        try:
            ids = [int(x) for x in items_arg]
        except (TypeError, ValueError):
            return "item_ids 须是整数数组，或传 'all'/省略表示当天全部。"
        rows = session.execute(text(base + "AND i.id = ANY(:ids) ORDER BY i.id"),
                               {"u": uid, "ids": ids}).all()
        ghost = sorted(set(ids) - {r.id for r in rows})
        if ghost:
            return (f"条目 {ghost} 不在本户生效计划的账上（票闸）——"
                    "id 只能取自【计划账】或本回执清单，禁止自造；对上号后重调。")
    if not rows:
        return f"{d:%m-%d} 没有待打卡的条目（都已打过或当天无排定任务）——没什么可打，别造卡。"
    session.execute(text(
        "UPDATE plan_items SET status = :st, done_note = :n, completed_at = now() "
        "WHERE id = ANY(:ids)"),
        {"st": status, "n": (str(args.get("note") or "").strip()[:300] or None),
         "ids": [r.id for r in rows]})
    session.commit()
    rest = session.scalar(text(
        "SELECT count(*) FROM plan_items i JOIN plans p ON p.id = i.plan_id "
        "WHERE i.user_id = :u AND i.date = :d AND i.status = 'pending' "
        "AND p.status = 'active'"), {"u": uid, "d": d})
    hint = ""
    kps = [r.kp_ref for r in rows if r.kp_ref]
    if kps:
        lvl_rows = session.execute(text(
            "SELECT n.name, COALESCE(m.level, '未接触') AS level FROM knowledge_nodes n "
            "LEFT JOIN knowledge_mastery m ON m.kp_ref = n.id AND m.user_id = :u "
            "WHERE n.id = ANY(:ks)"), {"u": uid, "ks": kps}).all()
        hint = (" 今日涉及知识点：" + "；".join(f"{r.name}（现档 {r.level}）" for r in lvl_rows)
                + "。掌握度是否变化依据用户汇报判断并向其**建议**，用户点头才调 "
                   "update_mastery；汇报平淡时建议为零也完全正当（F-23③）。")
    return (f"打卡成功：{d:%m-%d} 共 {len(rows)} 条已记为{'完成' if status == 'done' else '部分完成'}"
            + (f"；该日还剩 {rest} 条未打——问问用户是继续还是改期，别替他判失败。" if rest else "。")
            + hint + " 向用户复述打卡结果时以本回执条数为准。")


def adjust_plan_item(args: dict, ctx: dict) -> str:
    """商量顺延（F-24 · D17 甲案定点改期）：只挪 pending 条的日期并 plan_change_logs
    留痕（actor 恒 'user'——本手只在用户选定方案后调，静默改在流程上就不成立）。
    done/partial 是历史事实不许挪时间（事实不顺延，只有计划顺延）；新日期不得早于
    今天。边界自曝：定点改不重跑 V 闸，回执若显新日超时须引导整版重排。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        item_id = int(args.get("item_id"))
        nd = datetime.strptime(str(args.get("new_date")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "item_id 须整数、new_date 须 YYYY-MM-DD——对照计划账改正后再调。"
    if nd < date.today():
        return f"不能把任务挪到过去的 {nd}——顺延只朝未来；过去的缺口跟用户商量补录还是翻页。"
    row = session.execute(text(
        "SELECT i.id, i.plan_id, i.date, i.task_desc, i.status, p.version, p.exam_type "
        "FROM plan_items i JOIN plans p ON p.id = i.plan_id "
        "WHERE i.id = :i AND i.user_id = :u AND p.status = 'active'"),
        {"i": item_id, "u": uid}).first()
    if not row:
        return "这条不在本户生效计划的账上（票闸）——id 只能取自计划账/打卡回执，禁止自造。"
    if row.status != "pending":
        return (f"条目 {item_id} 已是 {row.status}——做完的历史事实不能顺延；"
                "若用户说记错了，走 report_check_in 方向修正或明说改不了。")
    reason = str(args.get("reason") or "").strip()
    if not reason:
        return "reason 不能空——PRD 剧本要求『有理由、有去向、有确认』，理由进账才留得住痕。"
    session.execute(text("UPDATE plan_items SET date = :d WHERE id = :i"), {"d": nd, "i": item_id})
    session.execute(text(
        "INSERT INTO plan_change_logs (plan_id, user_id, actor, reason, snapshot, created_at) "
        "VALUES (:p, :u, 'user', :r, :s, now())"),
        {"p": row.plan_id, "u": uid, "r": reason[:500],
         "s": json.dumps({"adjust_item": item_id, "from": str(row.date), "to": str(nd),
                          "task": row.task_desc}, ensure_ascii=False)})
    session.commit()
    prof = session.execute(text(
        "SELECT exam_date, weekday_minutes, weekend_minutes FROM exam_profiles "
        "WHERE user_id = :u AND exam_type = :e AND is_primary"),
        {"u": uid, "e": row.exam_type}).first()
    warn = ""
    if prof:
        tot = session.scalar(text(
            "SELECT COALESCE(sum(est_minutes), 0) FROM plan_items "
            "WHERE user_id = :u AND date = :d"), {"u": uid, "d": nd}) or 0
        budget = prof.weekend_minutes if nd.weekday() >= 5 else prof.weekday_minutes
        if budget and tot > budget * 1.2:
            warn = (f"注意：新日期当天已排 {tot} 分钟，超过用户声明的 {budget} 分钟"
                    "（含 1.2 容忍）——别再一条条挪了，向用户提议整版重排（generate_plan）。")
    left = f"新日期距考试 {(prof.exam_date - nd).days} 天，" if prof else ""
    return (f"条目 {item_id}「{row.task_desc[:40]}」已从 {row.date:%m-%d} 挪到 {nd:%m-%d}"
            f"（计划 v{row.version} 不变，{left}改动已留痕）。{warn}"
            "向用户复述新安排时带上剩余任务数。")


def edit_plan_item(args: dict, ctx: dict) -> str:
    """手动改单条（F-25 · D19 甲）：只改内容，分工钉死——改日期归 adjust_plan_item、
    整版重排归 generate_plan、本手管 task/subject/kp_ref/est_minutes/kind。
    三道明闸：票闸（本户 active 计划的 id 才认）、只改 pending（done 内容是历史
    事实，改它=篡改记录，与「历史事实不顺延」同形）、V3 复查（换成编的知识点照拒）。
    AC②「先警告再允许坚持」=D12 往返的代码强制：不带 force 首调若当天超载/冲刺段
    被塞学新类任务→不落库原样回警告；用户明确坚持才 force=true 重调落库留痕。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        item_id = int(args.get("item_id"))
    except (TypeError, ValueError):
        return "item_id 须整数——对照计划账回传。"
    row = session.execute(text(
        "SELECT i.id, i.plan_id, i.date, i.subject, i.kp_ref, i.task_desc, i.est_minutes, "
        "i.kind, i.status, p.version, p.exam_type, p.sprint_start_date "
        "FROM plan_items i JOIN plans p ON p.id = i.plan_id "
        "WHERE i.id = :i AND i.user_id = :u AND p.status = 'active'"),
        {"i": item_id, "u": uid}).first()
    if not row:
        return "这条不在本户生效计划的账上（票闸）——id 禁自造。"
    if row.status != "pending":
        return (f"条目 {item_id} 已是 {row.status}——历史事实不改内容；"
                "若打卡打错了，如实向用户说明记错账，绝不回头改任务来圆。")
    changes = {}
    if str(args.get("task") or "").strip():
        changes["task_desc"] = str(args["task"]).strip()[:500]
    if "subject" in args:
        changes["subject"] = str(args["subject"] or "").strip()[:64] or None
    if args.get("est_minutes") is not None:
        try:
            est = int(args["est_minutes"])
        except (TypeError, ValueError):
            return "est_minutes 须整数分钟。"
        if est <= 0 or est > 16 * 60:
            return f"est_minutes={est} 出界（0<est≤960）——和校验器同一把尺。"
        changes["est_minutes"] = est
    if args.get("kp_ref") is not None:
        try:
            kp = int(args["kp_ref"])
        except (TypeError, ValueError):
            return "kp_ref 须整数节点 id。"
        real = session.scalar(text("SELECT 1 FROM knowledge_nodes "
                                   "WHERE id = :k AND user_id = :u"), {"k": kp, "u": uid})
        if not real:
            return (f"V3 复查：节点 {kp} 不在本户账上（禁止编造）——要新知识点先走 "
                    "update_mastery 的建点确认流。")
        changes["kp_ref"] = kp
    if args.get("kind") is not None:
        if args["kind"] not in KINDS:
            return f"kind=『{args['kind']}』不认，只许 {'/'.join(KINDS)}。"
        changes["kind"] = args["kind"]
    if not changes:
        return "至少给一个要改的字段（task/subject/kp_ref/est_minutes/kind）——空改不算改。"
    # AC② 警告关：模拟改后状态，超限就停手回警告（force 才放行）
    warns = []
    est_eff = changes.get("est_minutes", row.est_minutes)
    tot = (session.scalar(text(
        "SELECT COALESCE(sum(i.est_minutes), 0) FROM plan_items i JOIN plans p "
        "ON p.id = i.plan_id WHERE i.user_id = :u AND i.date = :d AND p.status = 'active'"),
        {"u": uid, "d": row.date}) or 0) - row.est_minutes + est_eff
    prof = session.execute(text(
        "SELECT weekday_minutes, weekend_minutes FROM exam_profiles "
        "WHERE user_id = :u AND exam_type = :e AND is_primary"),
        {"u": uid, "e": row.exam_type}).first()
    if prof:
        budget = prof.weekend_minutes if row.date.weekday() >= 5 else prof.weekday_minutes
        if budget and tot > budget * 1.2:
            warns.append(f"改完当天排 {tot} 分钟，超用户声明的 {budget} 分钟（含 1.2 容忍）")
    kind_eff = changes.get("kind", row.kind)
    if row.date >= row.sprint_start_date and kind_eff in ("new", "exercise"):
        warns.append(f"{row.date:%m-%d} 已在冲刺段（{row.sprint_start_date:%m-%d} 起），"
                     f"改成 {kind_eff} 是学新内容——挤占复习时间的后果请用户自己拍")
    if warns and not bool(args.get("force")):
        return json.dumps({"需用户确认后才能改": warns, "item_id": item_id,
                           "rule": "把警告原样带给用户（『可以，但……确认吗？』）；"
                                   "仅当用户明确表示坚持，才带 force=true 重调本手；"
                                   "禁止自己替用户点头"}, ensure_ascii=False)
    session.execute(text("UPDATE plan_items SET "
                         + ", ".join(f"{c} = :{c}" for c in changes)
                         + " WHERE id = :i"), {**changes, "i": item_id})
    old = {k: getattr(row, {"task_desc": "task_desc"}.get(k, k)) for k in changes}
    session.execute(text(
        "INSERT INTO plan_change_logs (plan_id, user_id, actor, reason, snapshot, created_at) "
        "VALUES (:p, :u, 'user', :r, :s, now())"),
        {"p": row.plan_id, "u": uid,
         "r": (str(args.get("reason") or "").strip() or "用户主动改内容")[:500],
         "s": json.dumps({"edit_item": item_id, "from": old, "to": changes,
                          "warned": bool(warns)}, ensure_ascii=False)})
    session.commit()
    note = "（警告后用户坚持，照改）" if warns else ""
    return (f"条目 {item_id} 已即时更新 {len(changes)} 个字段{note}，"
            f"计划 v{row.version} 不变、改动已留痕。向用户复述新内容。")


# ── S6 首刀：时效事件链四只手（PRD F-15/F-26 · D22 甲减量往返 · D25 甲 mock/sprint 豁免）──

def _half(est: int) -> int:
    """减量算术（D25 甲）：减半后向上贴 5 分钟（120→60、45→25、10→5、5→5）。
    这笔账归程序不归模型——模型只负责把「下周三」听成日期，数字它不碰。"""
    return max(5, ((est + 1) // 2 + 4) // 5 * 5)


def create_life_event(args: dict, ctx: dict) -> str:
    """登记时效事件，不碰计划（F-26 前半 · D22 甲）：「全程无需用户再开口」指的是
    不用反复下指令改计划，不等于跳过首次确认——静默改违反 84 行产品要求。
    日期换算归模型的嘴（它最会读人话），工具闸替它把关算术：倒置/过去/超界拒收。
    回执带程序算好的逐日减量预览，模型拿预览征询，用户点头才 apply_life_event。"""
    session, uid = ctx["session"], ctx["user_id"]
    content = str(args.get("content") or "").strip()
    if not content:
        return "content 不能空——事件本体也要落账（『去杭州出差』），日期是另一回事。"
    try:
        sd = datetime.strptime(str(args.get("start_date")), "%Y-%m-%d").date()
        ed = datetime.strptime(str(args.get("end_date")), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "start_date/end_date 须 YYYY-MM-DD——先把用户的话换算成真日期" \
               "（星期几拿不准先调 get_current_time）；倒置、过去、超界工具都会复检。"
    today = date.today()
    if sd > ed:
        return f"start({sd}) 比 end({ed}) 还晚——日期倒置了，对照用户原话改正。"
    if ed < today:
        return f"事件 {ed} 就已经结束了——过去的日子不减量也不登记；要跟用户商量的是补救不是计划。"
    if (ed - sd).days > 90:
        return f"跨度 {(ed - sd).days} 天超过 90 天界限——这不是时效事件是要重排计划（generate_plan），先跟用户商量。"
    eid = session.scalar(text(
        "INSERT INTO life_events (user_id, content, type, start_at, end_at, impact_note, created_at) "
        "VALUES (:u, :c, 'one_time', :s, :e, :n, now()) RETURNING id"),
        {"u": uid, "c": content[:500], "s": sd, "e": ed,
         "n": (str(args.get("impact_note") or "").strip() or None)})
    session.commit()
    plan = session.execute(text(
        "SELECT id, version FROM plans WHERE user_id = :u AND status = 'active'"),
        {"u": uid}).first()
    if not plan:
        return (f"事件已登记（event_id={eid}，{sd:%m-%d}~{ed:%m-%d}「{content[:30]}」），"
                "但本户没有生效计划——没有可减的账；用户要计划时排期会吃到本事件。")
    rows = session.execute(text(
        "SELECT id, date, task_desc, est_minutes FROM plan_items "
        "WHERE user_id = :u AND plan_id = :p AND date BETWEEN :s AND :e AND status = 'pending' "
        "AND (kind IS NULL OR kind NOT IN ('mock', 'sprint')) ORDER BY date, id"),
        {"u": uid, "p": plan.id, "s": sd, "e": ed}).all()
    exempt = session.scalar(text(
        "SELECT count(*) FROM plan_items "
        "WHERE user_id = :u AND plan_id = :p AND date BETWEEN :s AND :e AND status = 'pending' "
        "AND kind IN ('mock', 'sprint')"), {"u": uid, "p": plan.id, "s": sd, "e": ed}) or 0
    if not rows:
        return (f"事件已登记（event_id={eid}）。区间内没有可减的 pending 任务"
                f"（{f'{exempt} 条模考/冲刺被豁免，' if exempt else ''}也许正逢休整日）"
                "——账如实，无需 apply_life_event，照实向用户说明。")
    tb = sum(r.est_minutes for r in rows)
    ta = sum(_half(r.est_minutes) for r in rows)
    by_day: dict = {}
    for r in rows:
        b, a = by_day.get(r.date, (0, 0))
        by_day[r.date] = (b + r.est_minutes, a + _half(r.est_minutes))
    days = "；".join(f"{d:%m-%d} {b}→{a} 分" for d, (b, a) in sorted(by_day.items()))
    return (f"事件已登记（event_id={eid}，{sd:%m-%d}~{ed:%m-%d}「{content[:30]}」）。"
            f"减量预览：{len(rows)} 条 {tb}→{ta} 分钟"
            f"{f'（另有 {exempt} 条模考/冲刺豁免不减）' if exempt else ''}。逐日：{days}。"
            "rule: 把预览原样给用户看过、他明确说要，才调 apply_life_event(event_id) 执行——"
            "替他点头=静默改（禁）；他说不用减就 forget_life_event 退账，计划本来就没动。")


def apply_life_event(args: dict, ctx: dict) -> str:
    """执行减量（F-26 后半）：用户对着预览点过头才准调。四道闸：票闸、
    防重入（applied_at——二次调用会再减一遍，这闸拦的正是它）、过期拒
    （end_at<今天：过去的日子不减，到期清账归 03:00）。留痕一条 change_logs
    （actor='life_event'——PRD 预留的第三源上岗），snapshot 存前后值+end_date：
    事件行明天就被物理删，次日恢复建议的真账全靠这本留痕。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        event_id = int(args.get("event_id"))
    except (TypeError, ValueError):
        return "event_id 须整数——只能取自 create_life_event 回执（票闸）。"
    row = session.execute(text(
        "SELECT id, content, start_at, end_at, applied_at FROM life_events "
        "WHERE id = :i AND user_id = :u"), {"i": event_id, "u": uid}).first()
    if not row:
        return "本户账上没有这个事件（票闸）——id 禁自造；已过期的事件会被清理删除，翻不出账来。"
    if row.applied_at:
        return ("本事件已减过量——重复 apply 会再砍一半，防重入闸拦下。"
                "要回滚用 restore_plan_items（log_id 在首次 apply 回执里）。")
    if row.end_at < date.today():
        return (f"事件 {row.end_at:%m-%d} 已结束——过去的日子不补减；"
                "如果用户是想恢复节奏，聊 restore_plan_items 或直接改。")
    plan = session.execute(text(
        "SELECT id FROM plans WHERE user_id = :u AND status = 'active'"),
        {"u": uid}).first()
    if not plan:
        return "本户没有生效计划可减（事件留着——将来排计划时它是参考账）。"
    targets = session.execute(text(
        "SELECT id, date, est_minutes FROM plan_items "
        "WHERE user_id = :u AND plan_id = :p AND date BETWEEN :s AND :e AND status = 'pending' "
        "AND (kind IS NULL OR kind NOT IN ('mock', 'sprint')) ORDER BY date, id"),
        {"u": uid, "p": plan.id, "s": row.start_at, "e": row.end_at}).all()
    items = [{"item_id": r.id, "date": str(r.date), "from": r.est_minutes,
              "to": _half(r.est_minutes)} for r in targets]
    for it in items:
        session.execute(text("UPDATE plan_items SET est_minutes = :t WHERE id = :i AND user_id = :u"),
                        {"t": it["to"], "i": it["item_id"], "u": uid})
    log_id = session.scalar(text(
        "INSERT INTO plan_change_logs (plan_id, user_id, actor, reason, snapshot, created_at) "
        "VALUES (:p, :u, 'life_event', :r, :s, now()) RETURNING id"),
        {"p": plan.id, "u": uid, "r": f"生活事件：{row.content[:200]}（用户确认减量）",
         "s": json.dumps({"phase": "apply", "event_id": row.id,
                          "end_date": str(row.end_at), "items": items}, ensure_ascii=False)})
    session.execute(text("UPDATE life_events SET applied_at = now() WHERE id = :i"), {"i": row.id})
    session.commit()
    if not items:
        return (f"已确认：{row.start_at:%m-%d}~{row.end_at:%m-%d} 区间内没有可减的 pending 任务"
                f"（留痕 log_id={log_id} 记『无改动』）。向用户照实说，别造变化。")
    tb = sum(it["from"] for it in items)
    ta = sum(it["to"] for it in items)
    return (f"已按预览减量 {len(items)} 条（{tb}→{ta} 分钟，{row.start_at:%m-%d}~{row.end_at:%m-%d}），"
            f"留痕 log_id={log_id}——随时可反悔：restore_plan_items({log_id}) 只回滚"
            "用户之后没再动过的条。事件结束次日账上会提恢复建议，你照账开口。")


def forget_life_event(args: dict, ctx: dict) -> str:
    """提前忘掉事件（F-15②「随时可删」）：与 forget_memory 同一价值观——不拒绝、
    不拖延。只删事件行；已减过的量不自动回滚（一只手不办两件事：事件归事件、
    计划归计划，回滚与否把 log_id 递到用户面前让他选——可感知、可撤销）。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        event_id = int(args.get("event_id"))
    except (TypeError, ValueError):
        return "event_id 须整数（票闸）。"
    row = session.execute(text(
        "DELETE FROM life_events WHERE id = :i AND user_id = :u "
        "RETURNING content, applied_at"), {"i": event_id, "u": uid}).first()
    if not row:
        return ("本户账上没有这个事件（票闸）——可能已被 03:00 清理删掉；"
                "若用户想恢复被减的任务量，用 restore_plan_items 对着变更账办。")
    extra = ""
    if row.applied_at:
        log = session.scalar(text(
            "SELECT id FROM plan_change_logs WHERE user_id = :u AND actor = 'life_event' "
            "AND snapshot ->> 'phase' = 'apply' AND snapshot ->> 'event_id' = :e "
            "ORDER BY id DESC LIMIT 1"), {"u": uid, "e": str(event_id)})
        if log:
            extra = (f" 该事件此前减过量（log_id={log}）——计划未自动回滚，"
                     f"用户想要回来的话调 restore_plan_items({log})。")
    session.commit()
    return f"事件「{row.content[:30]}」已删除，不再影响计划。{extra}".strip()


def restore_plan_items(args: dict, ctx: dict) -> str:
    """按变更账快照回滚事件减量（F-26② 恢复确认腿 / forget 后的撤销腿）。
    只回滚「当前值仍=减量后值」的行——用户后来手改或打卡动过的绝不覆盖：
    历史事实与人的意志都凌驾于这本账之上（与 adjust/edit 的 pending 闸同一立场）。
    天然幂等：第二次来全部错位，无事可回。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        log_id = int(args.get("log_id"))
    except (TypeError, ValueError):
        return "log_id 须整数——只能取自 apply/forget 回执（票闸）。"
    row = session.execute(text(
        "SELECT plan_id, snapshot FROM plan_change_logs "
        "WHERE id = :l AND user_id = :u AND actor = 'life_event' "
        "AND snapshot ->> 'phase' = 'apply'"), {"l": log_id, "u": uid}).first()
    if not row:
        return "本户变更账上没有这条事件减量账（票闸）——log_id 禁自造。"
    restored, skipped = [], []
    for it in row.snapshot.get("items", []):
        hit = session.scalar(text(
            "UPDATE plan_items SET est_minutes = :f "
            "WHERE id = :i AND user_id = :u AND est_minutes = :cur RETURNING id"),
            {"f": it["from"], "i": it["item_id"], "u": uid, "cur": it["to"]})
        (restored if hit else skipped).append(it["item_id"])
    if not restored:
        return ("没有可回滚的条目——要么已经恢复过（幂等），要么这些条后来被用户改过"
                "（手改不被覆盖）。向用户照实说明，别重复操作。")
    session.execute(text(
        "INSERT INTO plan_change_logs (plan_id, user_id, actor, reason, snapshot, created_at) "
        "VALUES (:p, :u, 'life_event', '恢复：回滚事件减量的任务量', :s, now())"),
        {"p": row.plan_id, "u": uid,
         "s": json.dumps({"phase": "restore", "origin_log": log_id,
                          "restored": restored, "skipped": skipped}, ensure_ascii=False)})
    session.commit()
    note = f"（{len(skipped)} 条因用户已改动/已恢复而跳过）" if skipped else ""
    return (f"已恢复 {len(restored)} 条到原任务量{note}。"
            "向用户复述恢复后的安排；今天学什么的账从此回到正常口径。")


# ── S7 首刀：出题与判分两手（PRD F-27/F-28 · D30 甲「判定权全归程序」· D29 甲聊天闭环）──

def generate_questions(args: dict, ctx: dict) -> str:
    """出题（F-27 · 补充二五步判定的程序化）：知识点必须已在进度账（票闸同款
    价值观——id/名字都对不上账就拒，引导走建点确认流）；库存、新鲜度（近 7 天
    做过的不重出）、数量下限全部 SQL 判定，模型只在缺口时当命题人。
    两段式自检在 questioning.gen_and_check 里（生成→独立重做比对→冲突弃题）。
    **防泄题闸**：回执逐字段拼装，answer/analysis 压根不进返回 JSON（F-27②
    的「前端拿不到」在聊天形状下的等价实现）。嵌套电厂的运费单独记 usage_logs
    ——外层循环看不见的调用最容易漏扣，配额闸不认漏网的。
    假电厂注入：ctx["inner_chat_fn"]（真链路缺席走 chat_once；单测塞脚本函数）。"""
    session, uid = ctx["session"], ctx["user_id"]
    kp_name = str(args.get("kp_name") or "").strip()[:128]
    if not kp_name:
        return "kp_name 不能为空——带回用户想练的知识点再调。"
    try:
        count = int(args.get("count") or 5)
    except (TypeError, ValueError):
        return "count 须是整数（1~10）。"
    if not 1 <= count <= 10:
        return f"count={count} 出界——一次 1~10 道，题海战术也讲排队。"
    difficulty = str(args.get("difficulty") or "").strip()
    if difficulty not in ("", "easy", "mid", "hard"):
        return f"difficulty 只认 easy/mid/hard（或省略），收到『{difficulty}』。"
    qtype = str(args.get("qtype") or "").strip()
    if qtype not in ("", "single", "multi", "fill", "short"):
        return f"qtype 只认 single/multi/fill/short（或省略），收到『{qtype}』。"
    exam_type = str(args.get("exam_type") or "").strip()[:32] or _default_exam(session, uid)
    if not exam_type:
        return ("还没有在考的主考档案，题库无从挂靠——请先引导用户用 "
                "save_exam_profile 登记考试。")
    # 知识点解析：精确名→模糊 ILIKE；0 命中回建点确认流（update_mastery 同规矩，
    # 出题不擅建点）；多命中列候选让用户挑（forget 候选闸同款刀法）。
    node = session.execute(text(
        "SELECT id, name, subject FROM knowledge_nodes WHERE user_id = :u AND exam_type = :e "
        "AND name = :n AND parent_id IS NULL"), {"u": uid, "e": exam_type, "n": kp_name}).first()
    if not node:
        like = session.execute(text(
            "SELECT id, name FROM knowledge_nodes WHERE user_id = :u AND exam_type = :e "
            "AND name ILIKE :q AND parent_id IS NULL ORDER BY id"),
            {"u": uid, "e": exam_type, "q": f"%{kp_name}%"}).all()
        if len(like) == 1:
            node = session.execute(text(
                "SELECT id, name, subject FROM knowledge_nodes WHERE id = :i"),
                {"i": like[0].id}).first()
        elif len(like) > 1:
            return json.dumps({"多知识点同名相近": [{"id": r.id, "名": r.name} for r in like],
                               "rule": "向用户确认要练哪个，带更具体的 kp_name 重调"},
                              ensure_ascii=False)
        else:
            return (f"『{kp_name}』在 {exam_type} 的进度账上没有节点——出题只练有账的知识点"
                    "（kp_ref 必填树内节点，F-27①）。请先向用户确认是否新增该知识点，"
                    "确认后走 update_mastery(create_node=true) 建点，再来出题。")
    # ---- 补充二程序判定：库存（题型/难度过滤）+ 新鲜度（近 7 天有答题记录的不重出）----
    where = ("WHERE q.user_id = :u AND q.exam_type = :e AND q.kp_ref = :k AND q.status = 'active'"
             " AND q.id NOT IN (SELECT question_id FROM quiz_attempts a"
             "  WHERE a.user_id = :u AND a.created_at > now() - interval '7 days')")
    q = {"u": uid, "e": exam_type, "k": node.id}
    if qtype:
        where += " AND q.qtype = :qt"; q["qt"] = qtype
    if difficulty:
        where += " AND q.difficulty = :df"; q["df"] = difficulty
    stock = session.execute(text(
        f"SELECT q.id, q.qtype, q.difficulty, q.stem, q.options, q.pitfall_hint "
        f"FROM questions q {where} ORDER BY q.id"), q).all()
    # ---- 三刀 3b：薄弱强化（F-30① D33 甲）——用户点名的 kp 若被 count≥3 的老毛病
    # 账牵着（该模式名下的错题就出自这个知识点），本次出题就要强化：额度=
    # ceil(总题量×40%)；库存里 pitfall_hint 与模式描述全等者算强化题（生成时程序
    # 盖章，见下），不够的缺口单开「强化批」一轮命题。声明按真实数——AC② 不暗箱。
    hits = session.execute(text(
        "SELECT ep.id, ep.description FROM error_patterns ep WHERE ep.user_id = :u "
        "AND ep.exam_type = :e AND ep.resolved = false AND ep.count >= 3 "
        "AND EXISTS (SELECT 1 FROM quiz_attempts a JOIN questions q ON q.id = a.question_id "
        "            WHERE a.error_pattern_ref = ep.id AND a.user_id = :u AND q.kp_ref = :k "
        "            AND a.invalidated_at IS NULL) "   # 报错作废的记录不算证据（F-31② 语义延伸）
        "ORDER BY ep.count DESC"), {"u": uid, "e": exam_type, "k": node.id}).all()
    focus_desc = hits[0].description if hits else ""   # 治疗对象=top1；其余连线只是触发条件
    target = math.ceil(count * WEAK_BOOST_RATIO) if hits else 0
    if hits:
        boosted = [r for r in stock if r.pitfall_hint == focus_desc]
        rest = [r for r in stock if r.pitfall_hint != focus_desc]
        picked = (boosted[:target] + rest)[:count]
    else:
        picked = list(stock[:count])
    gen_rows: list[dict] = []
    # 领走的题保证有 pending 答题行（计时起点=题到手，F-28④用时的根）
    for st in picked:
        if not session.scalar(text("SELECT 1 FROM quiz_attempts WHERE question_id = :i "
                                   "AND user_id = :u AND user_answer IS NULL"), {"i": st.id, "u": uid}):
            session.execute(text("INSERT INTO quiz_attempts (question_id, user_id, created_at) "
                                 "VALUES (:i, :u, now())"), {"i": st.id, "u": uid})
    need = count - len(picked)
    boost_have = sum(1 for r in picked if r.pitfall_hint == focus_desc)
    boost_real = boost_have
    problems: list[str] = []
    if need > 0:
        from backend.llm import chat_once            # 延迟 import：工具箱不拖电厂下水
        from backend.questioning import gen_and_check
        from backend.search import search
        materials = ""
        try:
            r = search(session, f"{kp_name} 典型例题 解题方法", uid, top_k=3)
            materials = "\n---\n".join(f"《{m['title']}》片段：{m['content'][:600]}"
                                       for m in r["results"][:3])
        except Exception:
            problems.append("资料检索腿故障——已按通用考纲常识命题")   # 降级不断腿
        level = session.scalar(text(
            "SELECT level FROM knowledge_mastery WHERE user_id = :u AND kp_ref = :k"),
            {"u": uid, "k": node.id}) or "未接触"
        # 二刀 2b：错误模式注入命题（F-30 铺垫）——top5 未结案的坑喂给命题人，
        # 让新题的干扰项精准踩坑。没账就空串，prompt 原样，零成本。
        pats = session.execute(text(
            "SELECT category, description FROM error_patterns WHERE user_id = :u "
            "AND exam_type = :e AND resolved = false "
            "ORDER BY count DESC, last_occurred_at DESC LIMIT 5"),
            {"u": uid, "e": exam_type}).all()
        weak_spots = "\n".join(f"- [{x.category}] {x.description}" for x in pats)
        fn = ctx.get("inner_chat_fn") or (
            lambda msgs, tools=None: chat_once(msgs, tools=tools, model=model_for(session, uid)))
        qs, ptok, ctok = [], 0, 0
        # 强化批先行（三b D33 甲）：整批专治 top1 老毛病；每题的强化身份由程序
        # 盖章进 pitfall_hint——「治了什么坑」是程序记的账，不是命题人自报的功。
        rq = []
        reinforce_n = min(need, max(0, target - boost_have))
        if reinforce_n > 0:
            rq, errs, p, c = gen_and_check(
                fn, kp_name=node.name, subject=node.subject or "", exam_type=exam_type,
                level=level, count=reinforce_n, difficulty=difficulty, materials=materials,
                node_id=node.id, weak_spots=weak_spots, qtype=qtype,
                pitfall_focus=focus_desc)
            problems += errs; ptok += p; ctok += c
            for it in rq:
                it["pitfall_hint"] = focus_desc
            qs += rq
        if need - len(rq) > 0:   # 强化批被自检枪毙的名额由普通批补足，总题量不亏
            nq, errs, p, c = gen_and_check(
                fn, kp_name=node.name, subject=node.subject or "", exam_type=exam_type,
                level=level, count=need - len(rq), difficulty=difficulty, materials=materials,
                node_id=node.id, weak_spots=weak_spots, qtype=qtype)
            problems += errs; ptok += p; ctok += c
            qs += nq
        if qtype:   # 双保险后闸：提示词钉了「一律 X」仍跑题型来，程序当场踢——
            off = [q for q in qs if q["qtype"] != qtype]
            if off:
                qs = [q for q in qs if q["qtype"] == qtype]
                problems.append(f"命题人越型 {len(off)} 道（要 {qtype} 出了 "
                                f"{'/'.join(sorted({q['qtype'] for q in off}))}），已程序剔除")
        # 声明按真实数（F-30② 不暗箱）：越型剔除、入库截断都发生在前，账对得上
        boost_real = boost_have + sum(1 for it in qs[:need] if it.get("pitfall_hint") == focus_desc)
        if ptok + ctok:   # 运费独立 commit：后面就算炸了，电厂的电钱也已经在账上
            session.execute(text("INSERT INTO usage_logs (user_id, day, tokens, created_at) "
                                 "VALUES (:u, :d, :t, now())"),
                            {"u": uid, "d": date.today(), "t": ptok + ctok})
            session.commit()
        for item in qs[:need]:
            qid = session.scalar(text(
                "INSERT INTO questions (user_id, exam_type, source, subject, kp_ref, qtype, "
                "difficulty, stem, options, answer, analysis, pitfall_hint, status, created_at) "
                "VALUES (:u, :e, 'llm', :s, :k, :qt, :df, :st, CAST(:op AS JSONB), :ans, :an, :ph, "
                "'active', now()) RETURNING id"),
                {"u": uid, "e": exam_type, "s": node.subject, "k": node.id, "qt": item["qtype"],
                 "df": item["difficulty"], "st": item["stem"], "op": json.dumps(item["options"]),
                 "ans": item["answer"], "an": item["analysis"], "ph": item["pitfall_hint"]})
            session.execute(text("INSERT INTO quiz_attempts (question_id, user_id, created_at) "
                                 "VALUES (:i, :u, now())"), {"i": qid, "u": uid})
            gen_rows.append({"qid": qid, "qtype": item["qtype"], "难度": item["difficulty"],
                             "题面": item["stem"], "选项": item["options"]})
    session.commit()
    out = {"知识点": node.name, "要求": count, "到手": len(picked) + len(gen_rows),
           "题目": [{"qid": s.id, "qtype": s.qtype, "难度": s.difficulty,
                    "题面": s.stem, "选项": s.options or []} for s in picked] + gen_rows,
           "rule": "逐题把『题面+选项』原样发给用户（编号带 qid），在用户交卷之前"
                   "严禁输出答案或讲解——它们不在本回执里，你编一个就是幻觉。"
                   "用户报答案后带 qid 调 grade_answer 判分，对错由程序裁定。"
                   + (f" 出题过程注记：{problems}" if problems else "")}
    if hits and boost_real > 0:   # F-30②：透明声明进回执，模型只许转述不许藏
        out["强化批"] = (f"本轮 {out['到手']} 题里有 {boost_real} 道是专治「{focus_desc}」"
                        f"的强化题（依据你的未结案错题账，F-30①）。")
        out["rule"] = ("回复第一句必须原样念出【强化批】声明——用户有权先知道自己"
                       "被加练了哪里；数字与坑名不许改、不许藏。" + out["rule"])
    if not out["题目"]:
        return json.dumps({"出题失败": problems or ["库存与生成双双空手"],
                           "rule": "向用户如实道歉，建议换个知识点或稍后再试；禁止自己编题冒充出库"},
                          ensure_ascii=False)
    return json.dumps(out, ensure_ascii=False)


def grade_answer(args: dict, ctx: dict) -> str:
    """判分（F-28 · D30 甲 · 二刀 2a）：客观题对错**程序裁决**（grade_one：
    single 比字母、fill 归一化对多可接受答案、multi 集合比对且漏选/错选区分）；
    short 是唯一让口——要点对照+思路点评交模型语义腿（short_review），
    不打分（23.7 承诺），verdict 档位枚举由程序执法。反馈五件套（5.3.3：
    对错/解析/关联知识点/思维误区/掌握度建议）逐题进本回执；答案判后才放行。
    三道闸不变：票闸（qid 必须本户未判分行）、幂等（判过的行自然翻不出）、
    用时=判分时刻−问题时刻（程序计时不归嘴）。主观腿与归类腿的嵌套运费单独入 usage_logs。
    答错客观题即触发错误模式沉淀（F-29 · 2b）：模型语义归类+合并，五类枚举与
    match_id 真实性由程序执法；归类腿炸了只注记不断判分腿——沉淀是加分项，判分是主业。
    判后手算本轮知识点的全对连击（剔除作废记录），≥10 挂【已克服提议】（F-30③
    · 三c）——只是提议，销账须用户点头后走 resolve_error_pattern，本手绝不自翻。"""
    session, uid = ctx["session"], ctx["user_id"]
    answers = args.get("answers")
    if not isinstance(answers, list) or not answers:
        return 'answers 须是非空数组：[{"qid":…, "answer":"…"}, …]。'
    if len(answers) > 20:
        return "一次最多判 20 题——大题量分批交。"
    from backend.questioning import grade_one
    details, ghosts = [], []
    graded_kps: set[int] = set()   # 本轮判到的知识点——三c 已克服提议按它算连对
    freight = [0, 0]      # 主观腿的嵌套电厂累计——首刀教训：嵌套运费必独立入账
    for row in answers:
        if not isinstance(row, dict):
            continue
        try:
            qid = int(row.get("qid"))
        except (TypeError, ValueError):
            ghosts.append({"qid": row.get("qid"), "原因": "qid 不是整数"})
            continue
        att = session.execute(text(
            "SELECT a.id AS att_id, a.created_at, q.qtype, q.answer, q.analysis, "
            "q.stem, q.pitfall_hint, q.exam_type, q.subject, q.kp_ref, n.name AS kp FROM quiz_attempts a JOIN questions q "
            "ON q.id = a.question_id "
            "JOIN knowledge_nodes n ON n.id = q.kp_ref "
            "WHERE a.question_id = :i AND a.user_id = :u AND a.user_answer IS NULL "
            "AND q.status = 'active' "     # 三a：报错下架的题判不动（F-31②判分作废的路之一）
            "ORDER BY a.id LIMIT 1"), {"i": qid, "u": uid}).first()
        if not att:
            ghosts.append({"qid": qid, "原因": "本户账上没有这道题的未判分记录（票闸）"})
            continue
        graded_kps.add(att.kp_ref)
        ua = str(row.get("answer") or "")
        dur = max(0, int((datetime.now(timezone.utc) - att.created_at).total_seconds()))
        if att.qtype == "short":
            from backend.llm import chat_once          # 延迟 import，出题手同款规矩
            from backend.questioning import short_review
            review, p, c = short_review(
                ctx.get("inner_chat_fn") or (
                    lambda msgs, tools=None: chat_once(msgs, tools=tools,
                                                       model=model_for(session, uid))),
                stem=att.stem, points=att.answer, user_answer=ua)
            freight[0] += p; freight[1] += c
            session.execute(text("UPDATE quiz_attempts SET user_answer = :ua, is_correct = NULL, "
                                 "duration_sec = :d, thinking_note = :tn WHERE id = :i"),
                            {"ua": ua[:500], "d": dur,
                             "tn": review["commentary"] or None, "i": att.att_id})
            adv = ("建议上调方向（同级微调免确认直接办；跨级或首达熟练是重大变更，"
                   "需用户点头）" if review["verdict"] == "基本达标" else
                   "先听用户思路再【建议】调档，点头才 update_mastery"
                   if review["verdict"] in ("未达标", "对照失败") else
                   "建议保持或小幅上调，用户说了算")
            details.append({"qid": qid, "题目": att.stem[:40], "你的回答": ua[:100] or "（空）",
                            "判定": review["verdict"], "参考答案要点": att.answer,
                            "点评": review["commentary"],
                            "错因参考": "要点对照（模型语义腿·程序锁枚举·不打分）",
                            "解析": att.analysis, "思维误区": review["pitfall"] or att.pitfall_hint,
                            "掌握度建议": adv, "知识点": att.kp})
        else:
            correct, note = grade_one(att.qtype, att.answer, ua)
            session.execute(text("UPDATE quiz_attempts SET user_answer = :ua, is_correct = :c, "
                                 "duration_sec = :d WHERE id = :i"),
                            {"ua": ua[:500], "c": correct, "d": dur, "i": att.att_id})
            row_out = {"qid": qid, "题目": att.stem[:40], "你的回答": ua[:100] or "（空）",
                       "判定": "对" if correct else "错", "正确答案": att.answer,
                       "错因参考": note, "解析": att.analysis,
                       "思维误区": att.pitfall_hint,
                       "掌握度建议": ("同级微调可直接 update_mastery；跨级/首达熟练需用户确认"
                                     if correct else
                                     "先问用户当时怎么想的，再【建议】调档，点头才落账"),
                       "知识点": att.kp}
            if not correct:
                # F-29 沉淀腿（2b）：答错→归类。电厂炸只注记、不断判分——
                # 判分是主业，沉淀是加分项，倒贴不许把主腿拖下水。
                try:
                    from backend.llm import chat_once      # 延迟 import，主观腿同款
                    from backend.questioning import classify_error
                    pats = session.execute(text(
                        "SELECT id, category, description FROM error_patterns "
                        "WHERE user_id = :u AND exam_type = :e AND resolved = false "
                        "ORDER BY count DESC, id LIMIT 20"),
                        {"u": uid, "e": att.exam_type}).all()
                    cls, p, c = classify_error(
                        ctx.get("inner_chat_fn") or (
                            lambda msgs, tools=None: chat_once(
                                msgs, tools=tools, model=model_for(session, uid))),
                        stem=att.stem, ref_answer=att.answer, user_answer=ua,
                        judge_note=note, subject=att.subject or "",
                        patterns=[{"id": x.id, "category": x.category, "description": x.description}
                                  for x in pats])
                    freight[0] += p; freight[1] += c
                    if cls["match_id"] is not None:        # 同义合并：count 归程序加（BR-21）
                        cnt = session.scalar(text(
                            "UPDATE error_patterns SET count = count + 1, last_occurred_at = now(), "
                            "description = :d WHERE id = :i RETURNING count"),
                            {"d": cls["description"], "i": cls["match_id"]})
                        cat = next((x.category for x in pats if x.id == cls["match_id"]),
                                   cls["category"])        # 合并回老账：类口径以原账行为准
                        row_out["错误模式"] = (f"老毛病复发，归入『{cat}』"
                                             f"{cls['description']}（第 {cnt} 次）")
                        ep_id = cls["match_id"]
                    else:                                   # 新建一账；越档的挂「待观察」旗
                        ep_id = session.scalar(text(
                            "INSERT INTO error_patterns (user_id, exam_type, subject, category, "
                            "description, count, last_occurred_at, resolved, tags, created_at) "
                            "VALUES (:u, :e, :s, :c, :d, 1, now(), false, CAST(:t AS JSONB), now()) "
                            "RETURNING id"),
                            {"u": uid, "e": att.exam_type, "s": att.subject,
                             "c": cls["category"], "d": cls["description"],
                             "t": json.dumps(["待观察"]) if cls["watch"] else None})
                        row_out["错误模式"] = (f"新开一账：『{cls['category']}』{cls['description']}"
                                             + ("（归类越出五档，由程序兜底挂『待观察』）"
                                                if cls["watch"] else ""))
                    session.execute(text("UPDATE quiz_attempts SET error_pattern_ref = :p "
                                         "WHERE id = :i"), {"p": ep_id, "i": att.att_id})
                    row_out["作答_id"] = att.att_id        # F-29③ 解绑凭据：用户否认时按此剪线
                except Exception:
                    row_out["错误模式"] = "归类腿故障——本题已正常判分，模式账暂未落，可向用户如实说明"
            details.append(row_out)
    session.commit()
    if sum(freight):   # 没有主观题就零运费不入账——判分腿本身免费（客观题纯程序）
        session.execute(text("INSERT INTO usage_logs (user_id, day, tokens, created_at) "
                             "VALUES (:u, :d, :t, now())"),
                        {"u": uid, "d": date.today(), "t": sum(freight)})
        session.commit()
    out = {"判分": len(details), "详情": details,
           "rule": "逐题把判定/正确答案（要点）/解析/思维误区/掌握度建议原样转述——"
                   "客观题对错是程序裁决的不许改判；简答题只有三档（基本达标/部分达标/未达标）"
                   "没有分数，这是 23.7 对用户的承诺，索要分数就解释不给。"
                   "多选漏选/错选按判语区分转述（少选和多选是两种病）。"
                   "答错先问用户当时怎么想的，掌握度只【建议】、点头才 update_mastery；"
                   "详情带『错误模式』字段的必须转述——那是老毛病账（F-29），"
                   "用户说『这条不是我的老毛病』时带该题 作答_id 调 unbind_error_pattern 解绑，"
                   "不与用户争这条归属；"
                   "想继续练再 generate_questions。"}
    if ghosts:
        out["没判成"] = ghosts
        out["rule"] += " 没判成的题如实向用户说明（可能已判过、qid 不对、或题目已报错下架" \
                       "——下架题判分作废），禁止重造。"
    # ---- 三c 已克服提议（F-30③ D34 甲）：手算本轮知识点最近的全对连击——
    # 剔除作废记录（F-31② 语义），简答题 is_correct 为 NULL 天然不入列（全对
    # 只对客观题成立）；连击 ≥10 且该 kp 还挂着未结案模式，才值得开口提议。----
    proposals = []
    for kp in graded_kps:
        seq = session.execute(text(
            "SELECT a.is_correct FROM quiz_attempts a JOIN questions q ON q.id = a.question_id "
            "WHERE a.user_id = :u AND q.kp_ref = :k AND a.user_answer IS NOT NULL "
            "AND a.is_correct IS NOT NULL AND a.invalidated_at IS NULL "
            "ORDER BY a.created_at DESC, a.id DESC LIMIT 30"), {"u": uid, "k": kp}).all()
        streak = 0
        for r in seq:
            if not r.is_correct:
                break
            streak += 1
        if streak < 10:
            continue
        for pat in session.execute(text(
                "SELECT ep.id, ep.category, ep.description FROM error_patterns ep "
                "WHERE ep.user_id = :u AND ep.resolved = false "
                "AND EXISTS (SELECT 1 FROM quiz_attempts a JOIN questions q ON q.id = a.question_id "
                "            WHERE a.error_pattern_ref = ep.id AND a.user_id = :u AND q.kp_ref = :k "
                "            AND a.invalidated_at IS NULL) ORDER BY ep.count DESC"),
                {"u": uid, "k": kp}).all():
            proposals.append({"模式_id": pat.id, "坑": f"『{pat.category}』{pat.description}",
                              "连续全对": streak})
    if proposals:
        out["已克服提议"] = proposals
        out["rule"] = ("若回执带【已克服提议】：转述完判定后顺口问一句「这个毛病看架势"
                       "是治好了，要不要把它从账上销掉？」——用户点头才调 "
                       "resolve_error_pattern(模式_id)，没点头绝不自行销账（F-30③ "
                       "是确认制不是自动制）。" + out["rule"])
    return json.dumps(out, ensure_ascii=False)


def unbind_error_pattern(args: dict, ctx: dict) -> str:
    """解绑误归（F-29③ · 2b）：用户说「这条不是我的老毛病」时，把那几次作答与
    错误模式的连线剪掉（error_pattern_ref 置 NULL，题目与判分记录原样保留）。
    票闸同判分手：只认本户真实挂着 ref 的作答 id——别人的、没挂过的、重复撤的都不算。
    **count 不回退**：PRD 只授权解绑单题，没授权翻模式账；用户否认的是「这题归我
    这条老毛病」这层归属，不是「这题我没错」——账按事实留着，误挂的线剪掉。"""
    session, uid = ctx["session"], ctx["user_id"]
    ids = args.get("answer_ids")
    if not isinstance(ids, list) or not ids:
        return 'answer_ids 须是非空数组：[作答_id, …]（grade_answer 详情里的 作答_id）。'
    if len(ids) > 20:
        return "一次最多解绑 20 条。"
    done, rejected = [], []
    for raw in ids:
        try:
            aid = int(raw)
        except (TypeError, ValueError):
            rejected.append({"作答_id": raw, "原因": "不是整数"})
            continue
        hit = session.scalar(text(
            "UPDATE quiz_attempts SET error_pattern_ref = NULL "
            "WHERE id = :i AND user_id = :u AND error_pattern_ref IS NOT NULL RETURNING id"),
            {"i": aid, "u": uid})
        if hit:
            done.append(hit)
        else:
            rejected.append({"作答_id": aid, "原因": "本户账上没有挂着错误模式的这条作答（票闸或已解绑过）"})
    session.commit()
    out = {"已解绑": done,
           "rule": "向用户复述解绑结果即可——原错误模式与其 count 不动（用户否认的是归属不是事实）。"
                   "用户若说『这个毛病我已经改了』，那是另一码事：走已克服确认——"
                   "带判分回执【已克服提议】里的模式_id 调 resolve_error_pattern，"
                   "没有提议就先练到位让提议浮出来，不许拿解绑当销账。"}
    if rejected:
        out["没动成的"] = rejected
    return json.dumps(out, ensure_ascii=False)


def report_question_error(args: dict, ctx: dict) -> str:
    """报错下架（F-31 · D35 甲 · 三a）：用户说「这题有问题」= 立即下架进核查队列——
    status 翻 reporting 后三路自然出局（库存/出题/判分的 SQL 都只认 active），
    不搞暗箱也不靠模型记仇。该题已判分记录标 invalidated_at（时间戳=审计线），
    其挂着的错误模式 count 按失效连线回滚、滚到 ≤0 连账带销：错题是幻觉题生的，
    母题作废子账同死——这才是 PRD「计入错误模式时排除」的完全体。
    恢复上架是管理页功能（PRD 15 章第 9 条原形），聊天端不办、记欠账。
    全程零电厂调用：这是纯程序活，报错本身免费。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        qid = int(args.get("qid"))
    except (TypeError, ValueError):
        return "qid 须是整数（出题/判分回执里的题号）。"
    note = str(args.get("note") or "").strip()[:500]
    hit = session.scalar(text(
        "UPDATE questions SET status = 'reporting', report_note = :n, reported_at = now() "
        "WHERE id = :i AND user_id = :u AND status = 'active' RETURNING id"),
        {"i": qid, "u": uid, "n": note or None})
    if not hit:
        ex = session.scalar(text("SELECT status FROM questions WHERE id = :i AND user_id = :u"),
                            {"i": qid, "u": uid})
        return json.dumps({"报错没办成": "这题已经在核查队列里了" if ex == "reporting"
                           else "本户题库没有这道题（票闸）——只认出题/判分回执里的真 qid，别报编的号"},
                          ensure_ascii=False)
    graded = session.scalar(text("SELECT count(*) FROM quiz_attempts WHERE question_id = :i "
                                 "AND user_id = :u AND user_answer IS NOT NULL"),
                            {"i": qid, "u": uid}) or 0
    session.execute(text("UPDATE quiz_attempts SET invalidated_at = now() WHERE question_id = :i "
                         "AND user_id = :u AND user_answer IS NOT NULL AND invalidated_at IS NULL"),
                    {"i": qid, "u": uid})
    rolled, dead = [], []
    for r in session.execute(text(
            "SELECT error_pattern_ref AS p, count(*) AS n FROM quiz_attempts "
            "WHERE question_id = :i AND user_id = :u AND user_answer IS NOT NULL "
            "AND error_pattern_ref IS NOT NULL GROUP BY 1"), {"i": qid, "u": uid}).all():
        left = session.scalar(text("UPDATE error_patterns SET count = count - :n WHERE id = :p "
                                   "RETURNING count"), {"n": r.n, "p": r.p})
        if left is None or left <= 0:   # 账全靠这道错题活着——连账带销
            session.execute(text("DELETE FROM error_patterns WHERE id = :p"), {"p": r.p})
            dead.append(r.p)
        else:
            rolled.append({"pattern_id": r.p, "新count": left})
    queue = session.scalar(text("SELECT count(*) FROM questions WHERE user_id = :u "
                                "AND status = 'reporting'"), {"u": uid}) or 0
    session.commit()
    return json.dumps({"已下架": qid, "失效判分记录": graded,
                       "错误模式回滚": {"减账": rolled or None, "销账": dead or None},
                       "核查队列现有": queue,
                       "rule": "如实转述：题已进核查队列（不再出、不再判、判分作废），"
                               "报错原话已存档供核查。用户反悔要恢复上架=管理页功能，"
                               "聊天端暂不办——如实说明，绝不自翻 status 当没报错。"},
                      ensure_ascii=False)


def resolve_error_pattern(args: dict, ctx: dict) -> str:
    """已克服销账（F-30③ · D34 甲 · 三c）：判分回执的【已克服提议】只是提议，
    真翻 resolved 只有这一把刀，且必须用户点头后才由模型代落——提议→点头→落刀，
    顺序不许颠倒。票闸：只认本户未结案的真模式 id。销的是「参与加权/归类」的资格，
    不是抹账：description、count 与历史连线原样留着（解绑手同款价值观——审计线
    谁也不许销毁，用户改好了是事实，抹掉他曾经犯过倒显得账能涂改）。
    纯程序活，零电厂调用。"""
    session, uid = ctx["session"], ctx["user_id"]
    try:
        pid = int(args.get("pattern_id"))
    except (TypeError, ValueError):
        return "pattern_id 须是整数（判分回执【已克服提议】里的模式_id）。"
    hit = session.execute(text(
        "UPDATE error_patterns SET resolved = true WHERE id = :i AND user_id = :u "
        "AND resolved = false RETURNING id, category, description"),
        {"i": pid, "u": uid}).first()
    if not hit:
        ex = session.scalar(text("SELECT resolved FROM error_patterns WHERE id = :i "
                                 "AND user_id = :u"), {"i": pid, "u": uid})
        return json.dumps({"销账没办成": "这条老账已经结过了" if ex is not None else
                           "本户错误模式账上没有这条（票闸）——只认回执里的真模式_id，"
                           "别销编的号"}, ensure_ascii=False)
    session.commit()
    return json.dumps({"已结案": hit.id, "坑": f"『{hit.category}』{hit.description}",
                       "rule": "如实转述：这条毛病从此不再触发加权出题、不再接新错题"
                               "的归类，账目本身保留可溯。用户反悔要重开不算聊天端功能"
                               "——如实说明，绝不自翻 resolved 当没销过。"},
                      ensure_ascii=False)


# ── S9·W7 数学 MCP 四手：只转发不算数——真算术在 sympy 子进程里 ──
# mcp_client.call 永不抛异常（起程失败/超时/熄火都回人话），run_tool 的
# 三层守护在它之下永远用不上；消费方=出题验算（事务轨），教学轨不调工具。


def mcp_solve_equation(args: dict, _ctx: dict | None = None) -> str:
    return mcp_client.call("solve_equation", args)


def mcp_simplify_expression(args: dict, _ctx: dict | None = None) -> str:
    return mcp_client.call("simplify_expression", args)


def mcp_compute_statistics(args: dict, _ctx: dict | None = None) -> str:
    return mcp_client.call("compute_statistics", args)


def mcp_verify_answer(args: dict, _ctx: dict | None = None) -> str:
    return mcp_client.call("verify_answer", args)


# 给模型的说明书：函数名、什么时候该用、参数什么形状（无参就给空 object）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "查询当前真实日期、星期与时刻，并附带用户档案里每场在考考试的"
                           "剩余天数及主辅标注。凡是涉及今天几号、星期几、现在几点、"
                           "离考试还剩多少天这类时间问题，必须先调用本工具，禁止凭记忆回答。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_exam_profile",
            "description": "登记或更新用户的考试档案。当用户明确说出考试类型和考试日期"
                           "（如『2026年12月4日考公务员』）时必须调用本工具落库；同类型考试"
                           "再次调用视为更新——重复调用绝对安全，你看不见数据库，"
                           "聊天里『记得』不算数，只有本工具落库才算，宁可多存不可漏存。"
                           "首场考试会自动设为主考，之后仅当用户明确表示"
                           "『以这场为主考』才传 is_primary=true（旧主考会自动降级）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_type": {"type": "string", "description": "考试类型，如：公务员考试、事业单位考试"},
                    "exam_date": {"type": "string", "description": "考试日期，YYYY-MM-DD 格式"},
                    "target_desc": {"type": "string", "description": "可选：用户口述的目标描述"},
                    "is_primary": {"type": "boolean", "description": "仅用户明确指定主考时传 true"},
                    "weekday_minutes": {"type": "integer", "description": "可选：用户声明的工作日每天可用学习分钟数（『工作日晚上下班后有2小时』→120），计划校验 V2 依赖它"},
                    "weekend_minutes": {"type": "integer", "description": "可选：用户声明的周末每天可用学习分钟数"},
                },
                "required": ["exam_type", "exam_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_materials",
            "description": "检索该用户上传入库的备考资料（讲义、真题解析、笔记等）。"
                           "当用户问具体考点、题目做法、公式或概念，且其上传资料可能有"
                           "第一手内容时，先调用本工具再回答；query 必须是一个完整的问句"
                           "（如『基期量怎么算』），不要只丢关键词。返回的每块材料带 ref 编号，"
                           "引用时在句末标注 [N]。闲聊或纯通用知识问题不要调用。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "完整问句"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "记住用户关于自身的信息（身份/目标/习惯/长期情绪）。用户亲口"
                           "说出或明确确认过时 source=user_stated；只有你自己的推测用 "
                           "inferred（会存为未确认、不生效，等用户亲口确认后再以 "
                           "user_stated 重存同 key 升格）。同 (category,key) 再存=更新。"
                           "密码、密钥等敏感隐私不存；一次性闲聊不存。",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "profile(身份档案)/goal(目标)/habit(习惯偏好)/emotion_long(长期情绪，须用户确认过)"},
                    "key": {"type": "string", "description": "事实的账名，如『身份』『学习时段』"},
                    "content": {"type": "string", "description": "记住的内容原文"},
                    "source": {"type": "string", "description": "user_stated 或 inferred，默认 user_stated"},
                },
                "required": ["category", "key", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_memories",
            "description": "查看你记住了用户什么。当用户问『你记住了我什么』『我的档案』"
                           "这类问题时调用；可选 category 只看一类。返回已区分好"
                           "【用户告诉的】与【推测待确认】两组，转述时保持这个区分。",
            "parameters": {
                "type": "object",
                "properties": {"category": {"type": "string", "description": "可选：只看某类"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_agent_name",
            "description": "用户给教练起名/改称呼时调用（如『以后叫你小知』）。"
                           "存入永久设定，之后自称用这个名字。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "用户指定的自称名"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_mastery",
            "description": "记录用户的学习进度/自评掌握度。当用户汇报学了什么、"
                           "做了什么题、感觉哪里弱哪里强时调用（如『今天学了基期量，"
                           "感觉不错』→ kp_name=基期量, level=一般掌握）。level 五档："
                           "未接触/初步了解/一般掌握/熟练/薄弱。confidence 0~100 是"
                           "你对自评的把握（用户说得笃定就给高）。不传 exam_type 默认"
                           "挂主考。若返回提示节点不存在，先向用户确认是否新增该知识点，"
                           "确认后带 create_node=true 重调——绝对不要擅自建节点或跳过确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_name": {"type": "string", "description": "知识点名称，如：基期量"},
                    "level": {"type": "string", "description": "未接触/初步了解/一般掌握/熟练/薄弱"},
                    "confidence": {"type": "integer", "description": "0~100，可选"},
                    "subject": {"type": "string", "description": "科目，如：资料分析，可选"},
                    "exam_type": {"type": "string", "description": "考试类型，默认挂主考"},
                    "note": {"type": "string", "description": "用户原话要点，可选"},
                    "create_node": {"type": "boolean", "description": "仅用户确认新增知识点后传 true"},
                },
                "required": ["kp_name", "level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_mastery",
            "description": "查看用户的学习进度账（掌握度清单，薄弱在前）。当用户问"
                           "『我哪块最弱』『进度怎么样』『上次学到哪』时调用，"
                           "按账回答，禁止凭聊天印象编进度。可选 exam_type/subject 过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_type": {"type": "string", "description": "可选：限定考试"},
                    "subject": {"type": "string", "description": "可选：限定科目"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_memory",
            "description": "按用户指令遗忘/删除记忆（PRD 6.4 用户主权）。用户说"
                           "『忘掉X』『别记得我X』『删掉那条』时调用，query 带回用户"
                           "说的内容描述。本工具任何情况下不得拒绝执行、不得用口头"
                           "安抚代替真删；命中多条时会先返回候选清单——向用户列出"
                           "确认范围后，按清单类别回传 memory_ids 或 mastery_ids 重调"
                           "完成删除。删除是物理删除，不可恢复，回执后向用户复述删了哪些。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要忘掉的内容描述，如：数学差"},
                    "target": {"type": "string", "description": "auto(默认)/memory(仅档案)/progress(仅进度)"},
                    "memory_ids": {"type": "array", "items": {"type": "integer"},
                                   "description": "仅用户确认范围后回传：删这些档案条目"},
                    "mastery_ids": {"type": "array", "items": {"type": "integer"},
                                    "description": "仅用户确认范围后回传：删这些进度条目"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_plan",
            "description": "生成到考试前一日的逐日学习计划（F-22）。用户说『帮我排计划/"
                           "重排计划』时调用。前提：主考日期与每日可用时长都已在档案里"
                           "（缺就先问用户再用 save_exam_profile 补）。days 必须从今天排到"
                           "考试前一日、一天不落；每条 task 含具体动作和量（禁止『复习数学』"
                           "式空任务）；kp_ref 只能引用用户进度账里真实存在的节点 id，"
                           "编的名字过不了 V3；考前最后 14~35 天是冲刺段，段内只许 "
                           "sprint/mock/review 类任务。后端会做 V1~V6 硬校验：返回"
                           "『校验未通过』就按原因重排后重传完整计划，绝不能绕过校验、"
                           "只落一半、或对用户谎称计划完成。校验全过也只是一份草案"
                           "（未生效）——向用户完整展示并问一句，用户确认后用返回的 "
                           "plan_id 调 activate_plan 才生效。",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "array",
                        "description": "逐日安排，从今天到考试前一日",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": "string", "description": "YYYY-MM-DD"},
                                "items": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "kp_ref": {"type": "integer", "description": "可选：知识点节点 id，必须是进度账里真实存在的"},
                                            "subject": {"type": "string", "description": "科目，如：资料分析"},
                                            "task": {"type": "string", "description": "具体动作+量，如：刷基期量20题并错题复盘"},
                                            "est_minutes": {"type": "integer", "description": "预计分钟数"},
                                            "kind": {"type": "string", "description": "new/exercise/review/mock/sprint"},
                                        },
                                        "required": ["task", "est_minutes", "kind"],
                                    },
                                },
                            },
                            "required": ["date", "items"],
                        },
                    },
                },
                "required": ["days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "activate_plan",
            "description": "把 generate_plan 生成的草案转正生效（F-22『用户确认激活』）。"
                           "仅当用户在看到计划后明确表示要（『激活』『就用这份』）时调用，"
                           "带回草案的 plan_id。用户没点头绝对不许调；自动换版：旧的生效"
                           "计划会归档并留痕。",
            "parameters": {
                "type": "object",
                "properties": {"plan_id": {"type": "integer", "description": "草案 id"}},
                "required": ["plan_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_check_in",
            "description": "每日打卡落账（F-23）。仅当用户亲口汇报完成情况时调用"
                           "（『今天学完了』『增长率那项做了，其他的没碰』）——"
                           "用户没说你绝不调，替他打卡=编造事实。status：全完成 done，"
                           "部分 done 之外 partial；items 可传 item_ids 清单（id 取自计划账"
                           "或回执，走票闸）或省略/'all' 表示当天全部。漏打卡不必调本手"
                           "假装没发生——保持 pending 次日账上会提，绝不自动判失败。"
                           "回执列出的涉及知识点仅供你向用户『建议』掌握度调整，"
                           "用户点头才 update_mastery，建议为零也正当；绝不自动升档。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD，省略=今天"},
                    "item_ids": {"type": "array", "items": {"type": "integer"},
                                 "description": "要打卡的条目 id；省略或 'all'=当天全部 pending"},
                    "status": {"type": "string", "description": "done 或 partial"},
                    "note": {"type": "string", "description": "可选：用户原话要点一句话（凭据）"},
                },
                "required": ["status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_plan_item",
            "description": "顺延/改期单条任务并留痕（F-24 商量流的落库腿）。"
                           "流程铁律：先给用户 2~3 种方案（顺延/压缩/砍目标模块），"
                           "每种附『距考试 X 天』（从计划账读，禁止自己算）——"
                           "用户选定后你才调本手，绝不静默改。参数：item_id（票闸）、"
                           "new_date（不得早于今天）、reason（用户给的理由，必填）。"
                           "只挪 pending 条；done/partial 是历史事实不许挪。"
                           "回执若提示新日期超时，停下向用户提议整版重排。",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "要改期的条目 id"},
                    "new_date": {"type": "string", "description": "挪去哪天，YYYY-MM-DD"},
                    "reason": {"type": "string", "description": "改动理由（用户的话），必填"},
                },
                "required": ["item_id", "new_date", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_plan_item",
            "description": "按用户自然语言指令改单条任务的内容（F-25，如『周四那条换成"
                           "判断推理』『这道题改做 30 分钟』）。分工：改日期用 "
                           "adjust_plan_item，整版重排用 generate_plan，本手只改内容"
                           "（task/subject/kp_ref/est_minutes/kind 至少一项）。只认本户"
                           "active 计划的 pending 条；改法若让当天超载或往冲刺段塞学新"
                           "内容，会先返回『需用户确认后才能改』——把警告原样带给用户，"
                           "他明确坚持才带 force=true 重调，不许自己点头。即时生效并留痕。",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "要改的条目 id"},
                    "task": {"type": "string", "description": "新任务描述（具体动作+量）"},
                    "subject": {"type": "string", "description": "新科目"},
                    "kp_ref": {"type": "integer", "description": "新知识点 id（真实存在）"},
                    "est_minutes": {"type": "integer", "description": "新预计分钟"},
                    "kind": {"type": "string", "description": "new/exercise/review/mock/sprint"},
                    "reason": {"type": "string", "description": "可选：用户的改动原话"},
                    "force": {"type": "boolean", "description": "仅用户看过警告仍坚持时 true"},
                },
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_life_event",
            "description": "登记带日期的一次性生活事件（F-15/F-26：出差、住院、"
                           "临时加班周）。先把用户的话换算成真日期再调（星期的真假"
                           "拿不准先问 get_current_time；工具会复检倒置/过去/超 90 天）。"
                           "本手只落事件并返回逐日减量预览（程序算的，你不算数），"
                           "计划一字不动——预览必须展示给用户，他明确说要才调 "
                           "apply_life_event，替他点头=静默改（禁）。『每周三晚上加班』"
                           "这类周期性事件不走本手：按 6.3.6 规则 5 用 save_memory 存成"
                           "习惯，不建时效条目。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "事件本体（『去杭州出差』），必填"},
                    "start_date": {"type": "string", "description": "YYYY-MM-DD 起始日，必填"},
                    "end_date": {"type": "string", "description": "YYYY-MM-DD 结束日（含当天），必填"},
                    "impact_note": {"type": "string", "description": "可选：用户说的影响（『只能晚上学』）"},
                },
                "required": ["content", "start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_life_event",
            "description": "执行事件区间内的任务减量（预览的落库腿）：区间内 pending 条"
                           "减半（模考/冲刺豁免，算术程序做）。仅当用户看过 create_life_event "
                           "的预览并明确同意后调用；防重入（减过的不能再减）；回执给 log_id，"
                           "反悔/恢复都靠它。",
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "integer", "description": "事件 id（取自登记回执）"}},
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_life_event",
            "description": "用户说『忘掉出差这件事/不去了』时立即删事件（F-15②，不拒绝"
                           "不拖延——与 forget_memory 同价值观）。只删事件；若此前减过量，"
                           "回执带 log_id 并如实说明计划未自动回滚，用户要恢复再走 "
                           "restore_plan_items。",
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "integer", "description": "事件 id"}},
                "required": ["event_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restore_plan_items",
            "description": "按变更账快照回滚事件减量（事件结束次日的恢复建议腿 / 撤销腿）。"
                           "账上只回滚『用户之后没再动过』的条——手改与打卡不被覆盖。"
                           "log_id 取自 apply/forget 回执；幂等，重复调无事可做。"
                           "用户在『要恢复原节奏吗』面前点头了才调。",
            "parameters": {
                "type": "object",
                "properties": {"log_id": {"type": "integer", "description": "减量留痕的变更账 id"}},
                "required": ["log_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_remind_time",
            "description": "设每日学习提醒的时点（F-33）。用户说『以后晚上九点半提醒我』"
                           "这类话时调用——先把话换算成 HH:MM 24 小时制再落账，拿不准"
                           "当前日期配合 get_current_time 想。提醒到点是系统自己开口"
                           "（读当日计划拼内容），不经你手，也不烧 token；落账后向用户"
                           "复述一遍新时点。没设过的户默认 20:00。",
            "parameters": {
                "type": "object",
                "properties": {"time": {"type": "string", "description": "HH:MM，24 小时制"}},
                "required": ["time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_questions",
            "description": "给用户出练习题（F-27）。用户说『来 5 道基期量』『出几道判断题』"
                           "时调用：kp_name 必须是进度账里真实存在的知识点（没节点会返回"
                           "提示——先向用户确认建点走 update_mastery，不许擅自建）。程序先查"
                           "题库库存（近 7 天做过的不重出），不足才现场命题+两段式自检。"
                           "返回的题目**不含答案与讲解**（防泄题是程序保证的）——把题面选项"
                           "逐题发给用户，等你收到他的作答再调 grade_answer 判分；你自己"
                           "口头出的题不算数、你判的对错也不算数。若该知识点挂着 count≥3 "
                           "的未结案错误模式，程序会自动加权出强化题并在回执挂【强化批】"
                           "声明——第一句就要念给用户（F-30② 透明）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "kp_name": {"type": "string", "description": "知识点名（进度账里的真实节点）"},
                    "count": {"type": "integer", "description": "题数 1~10，默认 5"},
                    "difficulty": {"type": "string", "description": "可选：easy/mid/hard"},
                    "qtype": {"type": "string", "description": "可选：single 单选 / multi 多选 / "
                                                                  "fill 填空 / short 简答"},
                    "exam_type": {"type": "string", "description": "可选，默认挂主考"},
                },
                "required": ["kp_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grade_answer",
            "description": "判分用户交上来的答案（F-28）：客观题对错由程序裁决，"
                           "你不参与判定；多选题会区分『漏选/错选』判语，简答（short）走"
                           "要点对照点评——只有三档结论没有分数，索要分数也不给（系统承诺）。"
                           "answers=[{qid, answer}, …]，qid 只能取自 generate_questions "
                           "回执（票闸；判过的不能重判）。返回反馈五件套：判定/正确答案"
                           "（要点）/解析/思维误区/掌握度建议——判分后才允许转述。答错的题"
                           "先问用户当时怎么想的，再按建议走（用户点头才 update_mastery）；"
                           "答错的客观题会自动沉淀进错误模式账（返回『错误模式』字段，必须转述），"
                           "用户否认归属时调 unbind_error_pattern 解绑。",
            "parameters": {
                "type": "object",
                "properties": {
                    "answers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "qid": {"type": "integer", "description": "题目 id（出题回执照抄）"},
                                "answer": {"type": "string", "description": "用户的答案原话（单选填字母）"},
                            },
                            "required": ["qid", "answer"],
                        },
                    },
                },
                "required": ["answers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unbind_error_pattern",
            "description": "撤销一次错误的「老毛病」归属（F-29③）。用户对判分回执里的"
                           "『错误模式』说『这条不是我的老毛病』『归错了』时调用："
                           "answer_ids 填该题详情里的 作答_id。只剪这道题与模式的连线，"
                           "错误模式账本身与 count 不动（用户否认的是归属，不是答错的事实）——"
                           "别拿这个当删账手，也别和用户争论归属。",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "grade_answer 详情里的 作答_id 列表（本户、当前挂着模式的）",
                    },
                },
                "required": ["answer_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_question_error",
            "description": "用户对某道题说『这题有问题』『答案错了』时立即调用（F-31）："
                           "题目下架进核查队列、该题判分记录作废、其喂给错误模式账的"
                           "计数回滚（多报不脏账）。qid 取回执里的真题号（票闸），note 尽量"
                           "带上用户说的毛病（供人工核查）。报了就生效，不许拖延也不许"
                           "替用户判断『应该没问题』而不报；恢复上架是管理页功能，"
                           "用户反悔就如实说聊天端暂不办，绝不自翻状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qid": {"type": "integer", "description": "有问题的题目 id"},
                    "note": {"type": "string", "description": "用户报的毛病原话（可选但尽量给）"},
                },
                "required": ["qid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_error_pattern",
            "description": "已克服销账（F-30③）：把一条错误模式标记为已结案——结案后"
                           "它不再触发加权出题、不再出现在归类清单里，但账目保留可溯。"
                           "只有两条路能调：①判分回执带【已克服提议】且用户点头；"
                           "②用户主动明说『这个毛病我改了/销了这条账』且模式_id 有出处。"
                           "顺序铁律：提议在前、点头在中、落刀在后——没点头绝不自销，"
                           "pattern_id 不许编。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern_id": {"type": "integer",
                                   "description": "【已克服提议】里的 模式_id（票闸：本户未结案真账）"},
                },
                "required": ["pattern_id"],
            },
        },
    },
]

# D58 甲：联网工具单列一队——进不进一轮的工具集由 tools_for 按用户开关裁决
WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "联网搜索（仅当用户开启联网开关时才会出现在工具集）："
                           "当 search_materials 零命中、或需要资料库之外的实时信息时调用；"
                           "回网络摘要与链接列表。用户的讲义优先——网络资料只在库中无货时兜底。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "完整搜索问句（自然语言）"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solve_equation",
            "description": "精确解方程（sympy 数学服务）。出题时验算题干参数是否自洽、"
                           "或用户要求解方程时调用；eq 是含等号的方程串如『2*x+3=9』"
                           "（没等号按 =0 处理），可指定变量名（默认 x）。"
                           "返回精确解文本。纯四则运算不用调（自己算即可）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "eq": {"type": "string", "description": "方程，如 2*x+3=9；幂用 ^"},
                    "variable": {"type": "string", "description": "可选：变量名，默认 x"},
                },
                "required": ["eq"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "simplify_expression",
            "description": "代数式化简（sympy）。需要把表达式化到最简形再讲解/出题时调用，"
                           "如『(x+1)^2-x^2』→『2*x + 1』。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expr": {"type": "string", "description": "代数式，幂用 ^"},
                },
                "required": ["expr"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_statistics",
            "description": "一组数的精确统计量（个数/均值/中位数/众数/极差/样本标准差）。"
                           "核对分数、算平均分等对账场景调用——比心算可信。",
            "parameters": {
                "type": "object",
                "properties": {
                    "numbers": {"type": "array", "items": {"type": "number"},
                                "description": "数字列表"},
                },
                "required": ["numbers"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_answer",
            "description": "验根：把候选值代回方程看残差是否为 0。出题给出标准答案前"
                           "先用这只手自验，答案是真话再出口；不满足时会报出实际残差。",
            "parameters": {
                "type": "object",
                "properties": {
                    "eq": {"type": "string", "description": "方程，如 x^2=4"},
                    "value": {"type": "number", "description": "候选根的值"},
                    "variable": {"type": "string", "description": "可选：变量名，默认 x"},
                },
                "required": ["eq", "value"],
            },
        },
    },
]

# 名字 → 真函数：模型举手报名字，这里对号执行
HANDLERS = {
    "get_current_time": get_current_time,
    "search_materials": search_materials,
    "save_exam_profile": save_exam_profile,
    "save_memory": save_memory,
    "query_memories": query_memories,
    "set_agent_name": set_agent_name,
    "update_mastery": update_mastery,
    "query_mastery": query_mastery,
    "forget_memory": forget_memory,
    "generate_plan": generate_plan,
    "activate_plan": activate_plan,
    "report_check_in": report_check_in,
    "adjust_plan_item": adjust_plan_item,
    "edit_plan_item": edit_plan_item,
    "create_life_event": create_life_event,
    "apply_life_event": apply_life_event,
    "forget_life_event": forget_life_event,
    "restore_plan_items": restore_plan_items,
    "set_remind_time": set_remind_time,
    "generate_questions": generate_questions,
    "grade_answer": grade_answer,
    "unbind_error_pattern": unbind_error_pattern,
    "report_question_error": report_question_error,
    "resolve_error_pattern": resolve_error_pattern,
    "web_search": web_search,   # D58 甲：schema 挂不挂看开关，调度表常在（兜底闸在 handler 里）
    # S9·W7 数学四手（sympy 子进程，只转发不算数）：
    "solve_equation": mcp_solve_equation,
    "simplify_expression": mcp_simplify_expression,
    "compute_statistics": mcp_compute_statistics,
    "verify_answer": mcp_verify_answer,
}


def run_tool(name: str, arguments: str, ctx: dict | None = None) -> str:
    """执行器：模型传来的参数是一段 JSON 文本；解析失败/工具不存在都不许炸后端，
    回一句人话让模型下一轮自己纠正——手抖不死人。
    ctx 由编排层注入（user_id/session/citations 记账本），模型碰不到。"""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return "工具参数不是合法 JSON，请重新调用。"
    fn = HANDLERS.get(name)
    if fn is None:
        return f"未知工具：{name}"
    try:
        return fn(args, ctx or {})
    except Exception:
        # 降级腿最后一公里：回人话给模型自纠——但必须留声（print 进容器日志），
        # 哑吞异常=调试黑洞（S4 首刀真机验案：光看回复分不清"没举手"还是"举手被吞"）
        print(f"[tool-fail] {name} args={arguments[:200]}", flush=True)
        return "这件工具执行故障了，请基于通用知识继续回答并说明情况。"
