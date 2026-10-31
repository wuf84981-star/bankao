# ============================================================
# 对话编排核心（S6 三刀手术 · D23 甲：import 复用，不架跨箱 HTTP）
# 从 main.py 的 /api/chat 路由整段提出来：组上下文→function-call 循环→
# 落库记账。网页腿（FastAPI 路由）和 QQ 腿（bot 容器 import）共用这一颗心——
# PRD 636「QQ 端与 Web 端共享同一账号、记忆与配额」从此不是愿望，是调用栈。
# 失败一律回 {"err": …} 不抛 HTTP——QQ 侧没有 HTTP 语义，路由自己翻译成人话。
# ============================================================
from datetime import date, timedelta

from sqlalchemy import func, select, text

from backend.jobs import DEFAULT_REMIND
from backend.llm import chat_once
from backend.models import Conversation, Message, UsageLog
from backend.points import (LOW_BALANCE_WARN, POINTS_EMPTY_MSG, balance_of, spend)
from backend.short_memory import note_message, window_get, with_summary
from backend.tools import (cited_by_reply, model_for, own_key_for, run_tool,
                           tools_for, web_allowed)

DAILY_QUOTA = 2_000_000  # BR-12：每用户每日 token 预算（服务器本地日为账期；
                        # D66 甲 2026-09-12：20 万→200 万——保险丝不撤只加粗，
                        # 20 万对「集中测试日」（五路模型轮聊+出题判分+点火）太细，
                        # 防程序跑飞烧穿账单的原意不变；账以真实 tokens 计、不乘倍率）

MAX_TOOL_ROUNDS = 6     # PRD 12.6：function-call 循环轮数封顶，超限视为失败掐断

SYSTEM_PROMPT = (
    "你是「伴考」，长期陪伴式公考备考教练，学长口吻：直接、具体、不灌水，全程简体中文。"
    "核心方法是教练而非答案贩卖机：用户问方法或题目时，先肯定问点对路，"
    "然后只给一个步骤或一个判断标准，结尾必须抛一个反问探用户的底（他怎么想的/先试哪步），"
    "等他回应再往下讲——一次别倒完全部答案。不知道就说不确定，禁止编造。"
    "一切日期、星期、时刻类问题必须先调用 get_current_time 工具查真历法再回答，禁止心算（BR-21）。"
    "用户明确说出自己的考试类型和考试日期时，调用 save_exam_profile 存档；"
    "聊天上文里『记得』不算数——凡是拿不准档案是否已存过，就直接再调本工具（重复调用=安全更新）。"
    "离考试还剩多少天一律以 get_current_time 返回的档案倒计时为准，不得自行推算。"
    "用户问具体考点、题目做法、公式概念时，先调用 search_materials 查他上传的资料，"
    "用了哪块材料就在对应句末标注 [ref 编号]；资料零命中时基于通用知识回答并明说"
    "『资料中未找到相关内容』，禁止把编的出处安到资料头上（PRD 632 防幻觉）。"
    "用户告诉你他自身的稳定信息（身份/目标/习惯/长期情绪）时，用 save_memory 落账"
    "（用户亲口说=source user_stated，你的猜测=inferred，猜测须用户口头确认后才"
    "可转 user_stated 重存升格）；用户问『你记住了我什么』调 query_memories；"
    "用户给你起名用 set_agent_name。system 尾部【数据库真账】优先于对话记忆，"
    "账上没有的档案信息就当没说过，不要凭上文冒充。"
    "用户汇报学习（学了X/做了X题/感觉哪弱哪强）时用 update_mastery 落进度账；"
    "工具提示知识点没节点时，先向用户确认是否新增，确认后才带 create_node=true 重调——"
    "擅自建点等于替用户做主（PRD 6.4）；问进度/哪最弱一律 query_mastery 查账，"
    "【学习进度·数据库真账】里没有的就不算学过。"
    "用户说『忘掉/删掉/别记得』任何记忆时，立即调用 forget_memory 执行——"
    "不得拒绝、不得反问拖延、不得用口头安抚代替真删（BR-07 铁律）；"
    "工具返回候选清单时向用户列条目确认范围，确认后回传 ids 重调完成删除；"
    "删完必须复述删掉了哪些内容。"
    "排学习计划是全程唯一『必须确定性』的环节（PRD 23.4）：只能经 generate_plan "
    "落库，嘴上排的天衣无缝不算数；工具回『校验未通过』就照错误清单逐条改后重传"
    "完整 days——校验器是代码执法，你无权讨价还价；校验过了也只是草案，必须向用户"
    "展示并等用户明确说要，才调 activate_plan 激活。排期需要每日可用时长："
    "用户没说就先问（『工作日每天大概几小时？周末呢』），问到就用 "
    "save_exam_profile 的 weekday_minutes/weekend_minutes 存进档案。"
    "计划生效后的日子靠打卡闭环（F-23/24）：用户亲口汇报『学完了/学了一部分』才调 "
    "report_check_in 落账——用户没说绝不调，替他打卡就是编造；漏打卡不判失败，"
    "账上【昨日欠】提示提出来就温和提醒补录。用户说安排不可行/要顺延：先给 2~3 种"
    "方案（顺延/压缩/砍目标模块）并附距考天数（读计划账，不许自己算），"
    "用户选定才调 adjust_plan_item 定点改期留痕——绝不静默改（PRD 5.2.2）。"
    "打卡回执里的知识点档位只是建议素材：改动须向用户提议、用户点头才 "
    "update_mastery，建议为零也正当。"
    "用户点名改某条任务内容（『周四那条换成判断推理』）用 edit_plan_item 即时改"
    "（改日期归 adjust_plan_item、整版归 generate_plan）；工具回"
    "『需用户确认后才能改』就把警告原样带给用户，他坚持才带 force=true 重调——"
    "警告关是代码设的，你无权替他点头。"
    "生活事件链（F-26）：用户说出带日期的一次性事件（『下周三到周五出差』），"
    "把话换算成真日期调 create_life_event 登记——本手只落事件、回逐日减量预览，"
    "不碰计划；预览必须展示给用户，他说好才 apply_life_event 执行减半，"
    "替他点头=静默改（禁止）。『每周三加班』类周期性事件不建时效条目，"
    "用 save_memory 存成 habit。用户说『不去了/忘掉出差』立即 forget_life_event，"
    "删完如实带出计划是否要恢复（restore_plan_items）。"
    "账上出现【生活事件】段就按它口径说话：减量中别按原量催学，"
    "待确认别谎称已减，次日恢复建议要主动提——提不提由账定，你照账开口。\n"
    "每日提醒（F-33）：到点发提醒是调度器的活（它读当日计划自动拼，不经你口），"
    "你只负责改时点（set_remind_time 落账）和答『现在几点提醒我』——"
    "答前看【每日提醒】账，没落账的『改好了』就是撒谎。\n"
    "出题与判分（F-27/28）：用户要练题只走 generate_questions——你口头出的题不在"
    "账上不算数；用户交卷前严禁给答案或讲解（回执里根本没有，编出来就是幻觉）；"
    "客观题对错由 grade_answer 程序裁决，你原样转述，判分权不在你手上；"
    "简答题只转述三档判定（基本达标/部分达标/未达标）与点评，**永不给分数**——"
    "这是系统承诺，用户索要也解释不给；"
    "答错的题先问用户当时怎么想的，掌握度只【建议】、他点头才 update_mastery 落账；"
    "判分回执带『错误模式』的转述给用户，他说『这条不是我的老毛病』就带 作答_id 调 "
    "unbind_error_pattern 解绑——归属用户说了算，你不与他争，也不许替他记毛病；"
    "出不出得来题、出得来什么题型都以回执为准：回执没有的题型就如实说系统暂时没有，"
    "可改参数重试——不许说『我给你想想别的路子』然后口头出题，口头题不进账也判不了，"
    "那是绕开系统撒谎；"
    "用户对题说『这题有问题/答案错了』立即 report_question_error 下架（F-31，宁可错报"
    "不可瞒报——核查队列是人工的活，不由你裁决题的对错），报完转述回执即可；"
    "出题回执带【强化批】时，回复第一句先念声明再发题——用户有权先知道自己被"
    "加练了哪里，这是透明规则，藏了就是暗箱（F-30②）；"
    "判分回执带【已克服提议】时转述完判定顺口问一句要不要销账，用户点头才调 "
    "resolve_error_pattern——提议→点头→落刀，顺序不许颠倒，没点头自销就是替用户"
    "做主（F-30③ 是确认制不是自动制）；"
    "带「[拍照汇报·图转写]」头的消息是 OCR 从照片里抄来的口供，可能含错——"
    "引用或落账时读着不对劲就先请用户核对原图，别把转写当用户原话照单全收。"
)


def _system_for(user_id: int, session) -> str:
    """S4 组装器——「消息会撒谎，档案不会」硬通道（首刀真机验案：长会话里模型
    把自己上轮的假'记下了'当事实，0/3 不再举手）。每轮钉账进 system 尾部：
    考试（exam_profiles）→ 档案（memory_facts）→ 称呼/提醒（agent_settings）
    → 进度 → 计划 → 生活事件。
    注入闸（D10 甲案·第二刀血案修订）：confirmed 行进【真账】段当依据用；
    inferred 行也进账但挂【推测待确认·未生效】旗——休眠≠对模型隐身，
    隐身反而给「假升格」留窟窿（真机案：模型嘴称升格、库里纹丝没动）。"""
    parts = [SYSTEM_PROMPT]

    rows = session.execute(text(
        "SELECT exam_type, exam_date, is_primary FROM exam_profiles "
        "WHERE user_id = :u AND status = 'in-progress' ORDER BY exam_date"
    ), {"u": user_id}).all()
    if not rows:
        parts.append("【用户考试档案·数据库真账】尚未登记任何考试。")
    else:
        lines = "；".join(
            f"{r.exam_type} {r.exam_date:%Y-%m-%d}{'（主考）' if r.is_primary else '（辅考）'}"
            for r in rows)
        parts.append(f"【用户考试档案·数据库真账】{lines}。"
                     "用户提到档案里没有或不符的考试信息时，"
                     "调用 save_exam_profile 登记/更正，回复口径以本账为准。")

    facts = session.execute(text(
        "SELECT category, key, content, confirmed FROM memory_facts "
        "WHERE user_id = :u ORDER BY category, key"
    ), {"u": user_id}).all()
    stated = "；".join(f"[{r.category}] {r.key}：{r.content}" for r in facts if r.confirmed)
    inferred = "；".join(f"[{r.category}] {r.key}：{r.content}" for r in facts if not r.confirmed)
    if stated:
        parts.append(f"【用户档案·数据库真账】{stated}。"
                     "用户说某条不对/要删时以 save_memory 更正（同 key 覆盖）；"
                     "提到档案外的个人新信息时存进本账，回复口径以本账为准。")
    if inferred:
        parts.append(f"【档案·推测待确认（未生效，不得当依据用）】{inferred}。"
                     "用户亲口确认某条时，必须以 save_memory(source=user_stated) 重存"
                     "同 (category,key) 完成升格——不落账的『升格了』就是撒谎。"
                     "若上文里你自称已确认/已升格、但本条仍挂在本段，"
                     "那正是你上轮没落账的现场：本轮立刻重存，别拿假回复当已办。")
    parts.append("本段真账由数据库实时生成：账上没有的信息，无论上文你说过什么，"
                 "都视为未登记，需要它就在本轮调用工具真正落库。")

    name = session.scalar(text(
        "SELECT agent_name FROM agent_settings WHERE user_id = :u"), {"u": user_id})
    if name:
        parts.append(f"【自称设定】用户为你起名『{name}』，回复中以此自称（PRD 3.2）。")

    # D61 甲 2026-09-11（用户拍板设置页人设接真腿，PRD 3.1 F-07 兑现）：人设=腔调账，
    # 只改说话风格，改不动功能规则、数据库真账与引导内核（不直接给答案）。
    # senior=全局默认语气（SYSTEM_PROMPT 本以此写），故不注入——无行/默认值零打扰，
    # 行为与旧版逐字相同；custom 用用户原文但注入句自带底线（代写/辱骂封死，F-07 注记）。
    prow = session.execute(text(
        "SELECT persona, custom_prompt FROM agent_settings WHERE user_id = :u"),
        {"u": user_id}).first()
    ps = (prow[0] if prow else None) or "senior"
    if ps == "strict":
        parts.append("【人设·数据库真账】用户设定你为严师型：不达标直说、批评督促、"
                     "要具体数字与结果，不绕弯和稀泥。但人设只改说话的软硬——"
                     "引导内核（不给现成答案）、数据库真账与功能规则一律照旧，不得辱骂用户。")
    elif ps == "buddy":
        parts.append("【人设·数据库真账】用户设定你为学习搭子型：平等陪伴、互相鼓励、"
                     "口吻轻松口语化。但督促标准和引导内核不因搭子语气放松——人设只改腔调。")
    elif ps == "custom" and prow and (prow[1] or "").strip():
        parts.append(f"【人设·用户自定义·数据库真账】用户给的说话风格描述：{prow[1].strip()}。"
                     "仅约束语气腔调，不得覆盖：不代写申论类答案、不辱骂用户、"
                     "不改变引导式内核与【数据库真账】优先级——账和人设打架时，账赢。")

    rt = session.scalar(text(
        "SELECT remind_time FROM agent_settings WHERE user_id = :u"), {"u": user_id})
    parts.append(f"【每日提醒·账】时点 {rt or DEFAULT_REMIND}{'（默认，未设置过）' if not rt else ''}。"
                 "到点开口的是调度器（它读当日计划拼提醒，不经你手、不烧 token）；"
                 "用户问几点提醒按本账答，要改时点调 set_remind_time 落账——别嘴上改了账没动。")

    # D59 乙 2026-09-11（用户改口径，覆盖 PRD 632 的无条件常识兜底）：关着开关=严格
    # 讲义模式。光改零命中提示语拦不住「压根不检索、直接凭常识作答」的路——源头立法。
    if not web_allowed(session, user_id):
        parts.append("【回答边界·数据库真账】该用户未开启联网搜索：考点类问题只在资料库"
                     "有货时作答；search_materials 零命中就直说『知识库无相关资料』，"
                     "不得改用通用常识补答，也不得跳过检索凭自有知识直接回答考点。"
                     "问候、计划、打卡、闲聊等与考点无关的对话不受此限。")

    prog = session.execute(text(
        "SELECT n.name, m.subject, m.level, m.confidence FROM knowledge_mastery m "
        "JOIN knowledge_nodes n ON n.id = m.kp_ref "
        "WHERE m.user_id = :u ORDER BY m.exam_type, m.level, n.name"
    ), {"u": user_id}).all()
    if prog:
        ledger = "；".join(
            f"[{r.subject or '未标科'}] {r.name}：{r.level}({r.confidence})" for r in prog)
        parts.append(f"【学习进度·数据库真账】{ledger}。"
                     "用户汇报学习时用 update_mastery 落账（知识点没账先向用户确认再建节点）；"
                     "问进度以本账为准，账上没有就是没学过，不许凭上文编进度。")

    # 计划账（S5 第五本）：生效计划+今日任务——隔天开口「今天学什么」不用举手就有实底
    plan = session.execute(text(
        "SELECT p.id, p.version, p.exam_type, p.sprint_start_date, e.exam_date "
        "FROM plans p JOIN exam_profiles e ON e.user_id = p.user_id "
        "AND e.exam_type = p.exam_type AND e.is_primary "
        "WHERE p.user_id = :u AND p.status = 'active'"), {"u": user_id}).first()
    if not plan:
        parts.append("【计划账·数据库真账】没有生效中的学习计划。用户要计划就调 "
                     "generate_plan（草案→展示→用户确认→activate_plan）；"
                     "上文里说过的『计划』若本账没有，视为不存在。")
    else:
        today = date.today()   # 与工具层/校验器同一天钟口径（服务器本地日）
        todays = session.execute(text(
            "SELECT task_desc, est_minutes, status FROM plan_items "
            "WHERE plan_id = :p AND date = :d ORDER BY id"), {"p": plan.id, "d": today}).all()
        tasks = "；".join(f"{t.task_desc}（{t.est_minutes}分/{t.status}）" for t in todays[:6]) or "无排定任务（休整日）"
        yest = today - timedelta(days=1)
        owed = session.scalar(text(
            "SELECT count(*) FROM plan_items WHERE plan_id = :p AND date = :d "
            "AND status = 'pending'"), {"p": plan.id, "d": yest}) or 0
        owing = (f"昨日（{yest:%m-%d}）还有 {owed} 条没打卡——主动提醒补录一次即可，"
                 "绝不自动判失败（F-23②）。" if owed else "")
        parts.append(f"【计划账·数据库真账】{plan.exam_type} 计划 v{plan.version} 生效中"
                     f"（{plan.sprint_start_date:%m-%d} 进冲刺，距考试 {(plan.exam_date - today).days} 天）。"
                     f"今日（{today:%m-%d}）任务：{tasks}。{owing}"
                     "问『今天学什么』按本账答；用户汇报完成时以本账核对，别凭上文编任务清单。")

    # 题库账（S7 首刀 · F-27/28）：存量+未判分两笔——「发出去没判的题」是悬案，
    # 用户说「我做完题了」而本段有 pending，就是等他交卷：引导报答案走 grade_answer。
    # 错误模式账条数（2b · F-29）：未结案几条照账报——老毛病数口径在库里，不在嘴里。
    qn = session.scalar(text(
        "SELECT count(*) FROM questions WHERE user_id = :u AND status = 'active'"),
        {"u": user_id}) or 0
    pend = session.scalar(text(
        "SELECT count(*) FROM quiz_attempts a JOIN questions q ON q.id = a.question_id "
        "WHERE a.user_id = :u AND a.user_answer IS NULL"), {"u": user_id}) or 0
    ep = session.scalar(text(
        "SELECT count(*) FROM error_patterns WHERE user_id = :u AND resolved = false"),
        {"u": user_id}) or 0
    rqueue = session.scalar(text(
        "SELECT count(*) FROM questions WHERE user_id = :u AND status = 'reporting'"),
        {"u": user_id}) or 0
    parts.append(f"【题库·数据库真账】库内 {qn} 题"
                 + (f"（另有核查队列 {rqueue} 题下架待核）" if rqueue else "")
                 + f"，已发出未判分 {pend} 题，"
                 f"错误模式账未消除 {ep} 条。"
                 "出题只走 generate_questions（口头出题=账上不存在）；"
                 + (f"有 {pend} 题在等用户交卷——他提做题就引导报答案去 grade_answer 判分。"
                    if pend else "用户要练题就按流程出题。"))

    # 生活事件账（S6 首刀 · F-26）：三态——区间内已减量 / 已登记待确认 / 结束次日提恢复。
    # 恢复行是「无状态一次性触发」：等值条件 end_date==昨天 只真一天，
    # 不立状态位——账说话、嘴跟着（S5 昨日欠同款打法）。
    ev_today = date.today()
    ongoing = session.execute(text(
        "SELECT content, start_at, end_at, applied_at FROM life_events "
        "WHERE user_id = :u AND start_at <= :d AND end_at >= :d ORDER BY id"),
        {"u": user_id, "d": ev_today}).all()
    for r in ongoing:
        if r.applied_at:
            parts.append(f"【生活事件·数据库真账】『{r.content[:30]}』进行中"
                         f"（{r.start_at:%m-%d}~{r.end_at:%m-%d}），这几天任务量已减半"
                         "（模考/冲刺豁免）——答『今天学什么』按现账，别说减前的量；"
                         "用户说不去了就 forget_life_event 再商量恢复。")
        else:
            parts.append(f"【生活事件·数据库真账】『{r.content[:30]}』"
                         f"（{r.start_at:%m-%d}~{r.end_at:%m-%d}）已登记但减量未经用户确认"
                         "——主动拿预览向用户要这一句话，点头才 apply_life_event，"
                         "绝不擅自改计划。")
    ended = session.execute(text(
        "SELECT id FROM plan_change_logs "
        "WHERE user_id = :u AND actor = 'life_event' AND snapshot ->> 'phase' = 'apply' "
        "AND (snapshot ->> 'end_date')::date = :y"),
        {"u": user_id, "y": ev_today - timedelta(days=1)}).all()
    if ended:
        logs = "、".join(str(r.id) for r in ended)
        parts.append("【生活事件·数据库真账】时效事件已于昨日结束——主动提议恢复原节奏"
                     f"（变更账 log_id={logs}）；用户点头才 restore_plan_items 逐本回滚，"
                     "他没接话就只提这一次，别追着改。")

    return "\n".join(parts)


def _get_or_create_conv(session, user_id: int, channel: str = "web",
                        conv_id: int | None = None) -> Conversation | None:
    """取该渠道最近会话，没有就开新——三刀起 QQ 会话与网页分家（channel 列
    S1 预留至此真上岗）：网页历史不能被正在活跃的 QQ 会话串道。
    F-08 五刀：显式给 conv_id 则**定点取**（本户+本渠道票闸），取不到返回 None
    由调用方拒——绝不悄悄新建行，否则伪造 id 每试一次就插一条垃圾会话。"""
    if conv_id is not None:
        return session.scalar(
            select(Conversation)
            .where(Conversation.id == conv_id,
                   Conversation.user_id == user_id,
                   Conversation.channel == channel))
    conv = session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.channel == channel)
        .order_by(Conversation.id.desc())
    )
    if conv is None:
        conv = Conversation(user_id=user_id, channel=channel,
                            title="伴考对话" if channel == "web" else "QQ 对话")
        session.add(conv)
        session.flush()   # 先领自增 id，消息才有得挂
    return conv


def answer_turn(session, user_id: int, user_text: str, *,
                channel: str = "web", chat_fn=None, image_refs=None,
                conv_id: int | None = None) -> dict:
    """一轮对话的心脏（从 /api/chat 路由整段搬来，语义不变）：
    钱包护栏→组上下文→举手循环→两句+流水同 commit 落库。
    chat_fn 可注入假电厂——真 key 缺席的纸面世界，循环形状照样全链验收。
    D60：真电厂路线收本户 model_choice 选模；注入的假电厂不感知（旧签名照活）。
    BYOK（2026-10-31）：本户带自带钥匙且选的是 DeepSeek 系型号——换钥匙烧自家的油、
    免扣积分（花销不再走平台账），但 token 流水照记、日配额闸照守（防失控家规不变）。
    注入的假电厂不参与 BYOK 判定（测试世界无钥匙概念，形状零变）。"""
    model = model_for(session, user_id)
    own_key = own_key_for(session, user_id, model)
    byo = bool(own_key) and chat_fn is None   # 假电厂=纸面世界，免扣逻辑别串进来
    kw = {"api_key": own_key} if own_key else {}   # 无钥匙=旧调用形状（假件家法）
    fn = chat_fn or (lambda msgs, tools=None: chat_once(msgs, tools=tools,
                                                        model=model, **kw))
    today = date.today()
    spent = session.scalar(
        select(func.sum(UsageLog.tokens))
        .where(UsageLog.user_id == user_id, UsageLog.day == today)
    ) or 0
    if spent >= DAILY_QUOTA:   # F-35/BR-12 钱包护栏（QQ 腿同闸：多端共一份配额）
        return {"err": "quota", "msg": "今日 200 万 token 预算用完啦，明天零点自动回血～"}
    if not byo and balance_of(session, user_id) <= 0:   # D64 积分闸：资产见底不开口——零成本人话，
        return {"err": "points", "msg": POINTS_EMPTY_MSG}   # 电厂一毛不烧（QQ 腿 msg 透传同形）
        # BYOK 闸旁路（2026-10-31）：自带钥匙烧的是用户自己的平台账，平台积分不扣即无「见底不开口」之说
    conv = _get_or_create_conv(session, user_id, channel, conv_id=conv_id)
    if conv is None:   # F-08 定点票闸：编的 id/别人的/QQ 行的，一律拒（不烧电厂不落账）
        return {"err": "conv", "msg": "这个会话不存在或不是你的——刷新侧栏重新选一个？"}
    # S9·W6：会话窗走近 20 条热缓存路（PRD 12.6 上下文窗口，D41 摘要接上）——
    # Redis 全灭时 window_get 回落原 PG select，行为逐字等于旧代码（降级语义钉）
    history = window_get(session, conv.id)
    msgs = [{"role": "system",
             "content": with_summary(_system_for(user_id, session), conv)}]
    msgs += history   # 纯 dict [{role, content}]——窗形状即提示词形状，直喂
    msgs.append({"role": "user", "content": user_text})
    # 工具执行上下文：后端注入的 user_id + 当前会话 + 引用记账本（模型碰不到）
    # channel 随行：S9·W3 缺口账按来源记账（web/qq），answer_turn 签名本就带着它
    # BYOK：仅自带钥匙在场时递 inner_chat_fn——嵌套电厂（出题/判分点评/错因归类）换钥匙；
    # 无钥匙=不注入，三处默认腿走老路逐字不变（外科手术最小扰动）
    ctx = {"user_id": user_id, "session": session, "citations": [], "channel": channel}
    if byo:
        ctx["inner_chat_fn"] = lambda msgs, tools=None: chat_once(
            msgs, tools=tools, model=model, api_key=own_key)
    try:
        # ── function-call 循环：举手→执行工具→喂结果→再问，最多 6 轮 ──
        ptok = ctok = 0
        used_tools: list[str] = []
        tools = tools_for(session, user_id)   # D58：web_search 按用户开关随行就市（关着=不在场）
        for _ in range(MAX_TOOL_ROUNDS):
            call_msg, p, c = fn(msgs, tools=tools)
            ptok += p
            ctok += c
            msgs.append(call_msg)   # 助手说的话（含举手的）也要进上下文
            if not call_msg.get("tool_calls"):
                reply = call_msg["content"]
                break               # 开口了，就是最终回复
            for tc in call_msg["tool_calls"]:
                f = tc["function"]
                used_tools.append(f["name"])
                # tool 角色三连：答的是谁举的手 + 执行结果是什么
                msgs.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": run_tool(f["name"], f["arguments"], ctx)})
        else:
            # 6 轮没收口=一直举手：视为失败，半句不落库
            return {"err": "stall", "msg": "模型连续调用工具未收敛，6 轮封顶已截断"}
    except Exception as e:
        # PRD BR-11：模型失败不计费不记账——半句都不落库（原子性第三次当法）
        # 但必须留声：2026-09-12 Qwen 大小写 404 悬案，吞异常无日志让排障全靠箱内重放
        print(f"[answer_turn] 电厂故障 {type(e).__name__}: {str(e)[:280]}")
        return {"err": "llm", "msg": "模型电厂暂时故障，稍后再试"}
    # D82 甲（2026-10-18 用户拍板·事务轨补票闸）：票面以嘴为准——本函数管
    # 非流式/QQ/拍照三条腿，与 main 流式腿、教学轨同一函数，四处一本账
    cited = cited_by_reply(ctx["citations"], reply)
    session.add(Message(conversation_id=conv.id, role="user",
                        content=user_text, token_count=len(user_text),
                        image_refs=image_refs))   # 拍照汇报的原图账随 user 行落库
    session.add(Message(conversation_id=conv.id, role="assistant",
                        content=reply, token_count=ctok,
                        citations=cited or None))   # 引用账随答案落库
    session.add(UsageLog(user_id=user_id, day=today, tokens=ptok + ctok))  # 流水+对话同 commit 同生共死
    # D64：积分扣分与 token 流水同笔事务签发；BYOK：烧的是用户自家平台账，积分不扣（cost=0），
    # 但 UsageLog 照记、日配额照算——流水是真花过的，账不能骗
    cost = 0 if byo else spend(session, user_id, ptok + ctok, model, today)
    session.commit()
    # S9·W6：落库后把本句与教练句添进会话窗——写路只添不删，Redis 灭时 no-op
    note_message(conv.id, "user", user_text)
    note_message(conv.id, "assistant", reply)
    balance = balance_of(session, user_id)
    remaining = DAILY_QUOTA - spent - ptok - ctok
    notice = (f"积分余额只剩 {balance}——记得签到续口粮，省着点用"   # 资产命门优先播报（BYOK 不扣分不播这条）
              if not byo and balance <= LOW_BALANCE_WARN
              else (f"今日剩余配额约 {max(remaining, 0)} token（不足 10%）"
                    if remaining < DAILY_QUOTA * 0.1 else None))
    return {"reply": reply, "remaining": remaining, "notice": notice,
            "points_spent": cost, "balance": balance, "byo": byo,
            "used_tools": used_tools, "citations": cited,
            "conv_id": conv.id}


# ── S7 四刀：拍照汇报腿（F-09 · D36~D39 甲 · PRD 518 qwen-vl-plus）──

IMAGE_BUDGET_24H = 4      # AC①「会话内 ≤4 张」的落地口径：同端最近 24 小时滚动窗


def _image_budget(session, user_id: int, channel: str) -> int:
    """近 24h 该端已收图片数（纯读账）：闸在 OCR 之前——拦下的图一分钱电费不烧。"""
    return session.scalar(text(
        "SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE c.user_id = :u AND c.channel = :ch AND m.role = 'user' "
        "AND m.image_refs IS NOT NULL AND m.created_at > now() - interval '24 hours'"),
        {"u": user_id, "ch": channel}) or 0


def image_turn(session, user_id: int, *, text: str = "", images: list[dict],
               channel: str = "web", chat_fn=None, ocr_fn=None,
               conv_id: int | None = None) -> dict:
    """拍照汇报正身（网页与 QQ 共用，同 answer_turn 的「多端同脑」家法）：
    每张图 → OCR 转写 → 拼成带「[拍照汇报·图转写]」头的用户消息 → 走 answer_turn。
    三条铁律：
    ①9.1 承诺代码化——原图只递 ocr_fn 这一跳，模型上下文里永远只有文本；
    ②运费家规——OCR 烧的电独立入 usage_logs（外层循环看不见这条腿），
      ocr_fn 注入口=假腿闸口，单测绝不真调千问；
    ③低置信程序执法——looks_unclear 说了算（转写带【没看清】或为空=不可信），
      不可信的图占位不猜；全不可读又零文字 → 大脑一次都不叫醒，回人话引导。
    超限（24h ≤4 张）与图无关的账：_image_budget 拦在函数最前，拒了不烧钱。"""
    from backend.llm import chat_once          # 延迟 import，answer_turn 同款下水规矩
    from backend.ocr import looks_unclear, transcribe_image
    # F-08 定点票闸排在一切烧钱动作之前：假 conv_id 连 OCR 的电都不配烧
    if conv_id is not None and _get_or_create_conv(
            session, user_id, channel, conv_id=conv_id) is None:
        return {"reply": "这个会话不存在或不是你的——刷新侧栏重新选一个？",
                "remaining": None, "notice": None, "used_tools": [], "citations": [],
                "err": "conv", "msg": "这个会话不存在或不是你的——刷新侧栏重新选一个？"}
    if balance_of(session, user_id) <= 0:   # D64：积分见底连 OCR 都不烧——闸排在运费之前
        return {"reply": POINTS_EMPTY_MSG,
                "remaining": None, "notice": None, "used_tools": [], "citations": [],
                "err": "points", "msg": POINTS_EMPTY_MSG}
    if _image_budget(session, user_id, channel) + len(images) > IMAGE_BUDGET_24H:
        return {"reply": f"这个端口 24 小时内最多收 {IMAGE_BUDGET_24H} 张照片，"
                         "先把手头这几张消化掉，或者直接用文字说～",
                "remaining": None, "notice": None, "used_tools": [], "citations": [],
                "rejected": "image_budget"}
    fn = ocr_fn or transcribe_image
    parts, refs, ocr_tok, unclear = [], [], 0, 0
    for im in images:
        if im.get("ref"):
            refs.append(im["ref"])
        try:
            t, p, c = fn(data=im.get("data"), url=im.get("url"))
            ocr_tok += p + c
            if looks_unclear(t):
                unclear += 1
                parts.append("（没看清，未转写）")
            else:
                parts.append(t)
        except Exception:
            unclear += 1
            parts.append("（图片识别失败：OCR 通道故障）")   # 故障自曝不静默（S3 家规）
    if ocr_tok:   # OCR 运费先落账再进大脑——后面炸了电钱也已经在账上（tools 同款）
        session.add(UsageLog(user_id=user_id, day=date.today(), tokens=ocr_tok))
        session.commit()
    body = (text or "").strip()
    merged = "\n\n".join(([body] if body else []) +
                         [f"[拍照汇报·图转写{i+1}]\n{p}" for i, p in enumerate(parts)])
    if not parts or (unclear == len(parts) and not body):
        # 全不可读且没带文字：不烧大脑的电，但用户发过图这事实必须进历史
        # （定点会话的存在性已在函数头票闸，这里按同形取回即可）
        conv = _get_or_create_conv(session, user_id, channel, conv_id=conv_id)
        session.add(Message(conversation_id=conv.id, role="user",
                            content=merged or "（发来一张图）",
                            token_count=len(merged), image_refs=refs or None))
        session.commit()
        return {"reply": "这张没看清呢——补张清楚点的，或者直接用文字告诉我也行～",
                "remaining": None, "notice": None, "used_tools": [], "citations": [],
                "message": merged, "ocr": {"images": len(images), "usable": 0},
                "conv_id": conv.id}
    out = answer_turn(session, user_id, merged, channel=channel, chat_fn=chat_fn,
                      image_refs=refs or None, conv_id=conv_id)
    out["message"] = merged   # 转写原文回给前端/日志：引用块核对的就是它（F-09 流程）
    out["ocr"] = {"images": len(images), "usable": len(parts) - unclear}
    return out
