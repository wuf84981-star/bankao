# ============================================================
# S9·W5 教学状态图（backend/teaching_graph.py）—— 2026-10-11
# 六步一线：safety→context→retrieve→diagnose→generate→verify。
# 回环=跨轮不轮内：一次 HTTP = 图走一遍线性六步；「未懂」轮数由 verify
# 落进检查点（thread_id=conv:{id}），同会话下一条消息续上轮数；
# 轮数≥5 触发转教师策略。轮内二次生成会作废已流出的字，绝路一条。
# 架构铁律（D71）：检查点=排障工具不是账本——教练行/流水/积分三本真账
# 只在一处：流尾结算事务（teaching_track.py 的结算段）。
# 电厂一字未改：generate 节点照喂 llm.chat_stream，每个 delta 事件转一条
# custom 事件，接线层原样成 delta 帧——D67 打字机效果复用。
# ============================================================
import operator
from typing import Annotated, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from backend.gaps import GAP_WEAK, record_gap
from backend.llm import chat_once, chat_stream
from backend.questioning import extract_json
from backend.safety import screen
from backend.search import search
from backend.teaching_strategies import (
    ADVANCE, ANALOGY, ANSWER_REVERSE, CASE_APPLY, CLARIFY, CONCEPT,
    DIRECTION, EMOTION, ERROR_REVIEW, FEYNMAN, HANDOFF, METHOD_VERIFY,
    SOCRATIC, STEP, VARIANT, STRATEGY_CN, extract_features, pick_strategy,
)


class TeachingState(TypedDict, total=False):
    """图状态：全 JSON 可序列化（检查点存盘的要求，塞不进活对象）。
    三个 add 通道是回环的机关：
    · round_no 跨轮累加——「未懂」轮数即回环本体，懂一轮清零；
    · ptok/ctok 每轮由 safety 节点先清零再逐节点累加——终值=本轮账单，
      才能与 usage_logs/points_ledger 三本账对得上（检查点不是账本，
      但它得经得起对账）。"""
    # ── 接线层每轮给新（覆盖语义） ──
    user_text: str
    user_id: int
    channel: str
    model: str | None
    system: str                 # 人设真源（orchestrator._system_for 注入，两轨同脑）
    history: list[dict]         # [{role, content}] 正序，接线层查库带入
    # ── 跨轮经检查点续存（add 通道） ──
    round_no: Annotated[int, operator.add]
    ptok: Annotated[int, operator.add]
    ctok: Annotated[int, operator.add]
    # ── 轮内产物（覆盖语义） ──
    knowledge: list[dict]       # 带 ref 编号的讲义块
    citations: list[dict]       # 出处账（chunk_id/material_id/title/seq——tools 同形契约）
    diagnosis: dict             # 诊断腿七键 JSON（宽容解析，坏文本=空表）
    strategy: str | None        # W4 规则表命中（None=模型自选兜底）
    feynman: bool | None        # D89 费曼意愿闸（接线层每轮查账注入；None=没注入按关）
    reply: str
    understood: bool | None     # 本轮验懂结论（下轮 diagnose 的输入）
    handoff: bool               # 本轮走了转教师话术
    stop_reason: str | None     # 目前只有 "safety"；后续节点见它空转，链不断


# ── 提示词三块（诊断腿契约 = teaching_strategies.extract_features 的 docstring）──

_DIAG_PROMPT = """你是学情诊断腿（教学轨内部）。只输出一个 JSON，不许任何别的话：
{"recent_wrong": 整数, "recent_correct": 整数, "off_topic": 布尔, "vague_streak": 布尔, "seen_before": 布尔, "same_kp_wrong_again": 布尔, "understood": 布尔}
判据（看不准的键给 null）：
- recent_wrong / recent_correct：近几轮里学生就当前知识点连续答错/答对的次数（答非所问、概念混淆算错）。
- off_topic：学生完全没头绪、答非所问。
- vague_streak：答对但表述含糊，说不出所以然。
- seen_before：这个知识点此前在对话里讲过吗。
- same_kp_wrong_again：同知识点此前答错过、本轮又错。
- understood：若上一轮教练话以反问收尾，学生本轮的回应是否显出真懂（能复述/能用对=真懂）；没有反问或无从判断给 null。"""

# 教学轨检索配额（D82 乙，2026-10-18 用户拍板）：与事务轨同步取 3。
# 2026-10-11 甲案 5→3（跨域配角摆牌案），10-18 曾随甲案试 2，评测裁决回 3：
# g23 答案块排第 3，供 2 就看不见（命中率 30 题跌一分），供 3 零掉分。
# 票面摆几张归 cited_by_reply 票闸管（正文标几张摆几张），供给归秤定。
# 保留独立常量不复用 search.TOP_K——两轨配额历来可分别调（先撞痛先动），
# 合并一个数省一行、埋一堵墙。各档实测见 reports/eval-2026-10-18-goldsetv2-k2.md。
TEACH_TOP_K = 3

_IRON = """【教学模式·五条铁律】你正在给卡住的学生讲知识点：
1. 不直接给最终答案——用递进反问把学生带到答案门口，让他自己迈进去；
2. 用到讲义块时，句子末尾标出处，如……[ref 1][ref 2]（编号对照下方材料块）；
3. 每轮收尾必须留一个检验性反问——懂不懂由学生下一句说了算，不由我宣布；
4. 一次只推一步，别把整节讲义一次倾倒；
5. 每轮话不超过三句+一个反问——简短才是教练（转教师那轮可免反问，同样收在三句内）；
严禁输出 <call>…</call>、工具参数 JSON、内部思考这类伪调用文本——那不是给人看的话。"""

# 策略→一句话演法（选策略的逻辑在 W4 规则表，这里是消费侧的话术指令；
# 未命中=None 时不钉策略，交模型自选——规则表知道自己不知道什么）。
_STRATEGY_HINT = {
    SOCRATIC: "他连着错还在硬算：别再讲公式，拆到最小一步问他「你这步的依据是什么」。",
    EMOTION: "他情绪上来了：先接住情绪再谈题——短句、站他那边，别催他。",
    DIRECTION: "他完全没头绪：先给一条入手的线索，别急着上细节。",
    VARIANT: "刚讲过同一知识点：换数字/换场景来道变式练习，看他会不会用。",
    ERROR_REVIEW: "同一知识点又栽了：先带他复盘上次错在哪一步，再决定补哪步。",
    CASE_APPLY: "他答对但说不清所以然：给个真实案例让他把道理讲出来。",
    ADVANCE: "他连对几轮：上道稍难的变式，往上爬一格。",
    ANALOGY: "他在死记硬背：找个他熟的类比把概念挂上去，再让他复述一遍。",
    STEP: "他拿着带选项/已知条件的具体题：只给第一步的提示，让他自己往下走。",
    METHOD_VERIFY: "他在报自己的思路：先指出思路里哪步对哪步偏，别替他算完。",
    ANSWER_REVERSE: "他直接要答案：拒代答，从答案倒推一步反问，把他引回推理。",
    CONCEPT: "这个概念他从没碰过：先铺垫定义（带材料出处），别直接跳应用。",
    CLARIFY: "他问得太短没头没尾：先反问一句澄清他到底问什么。",
    FEYNMAN: "他说懂了/要自己讲：换他当老师——请他用大白话把这个概念讲给你听，"
             "「就当教一个完全不懂的小学生」，你装学生；他讲到哪讲不下去，断点就补哪，"
             "别抢话代讲。",
    HANDOFF: "五轮还没带懂：给转教师话术——坦率承认 AI 教学到这里够用了，"
             "把这五轮卡在哪一步小结一句，建议他把这个知识点标记下来去问真人老师/同学。",
}


def make_nodes(session=None) -> dict:
    """六节点闭包工厂：retrieve 节点要有活的 session 才能捞库，其余五步不直触 DB。
    测试从这里拿单步节点逐个验；生产走 build_graph。"""

    def safety(state: TeachingState) -> dict:
        """第一步关闸：纯规则安全腿（零 token）。拦下则固定话术直接进 reply。
        本节点还兼任每轮清零器：ptok/ctok 归零（add 通道负值冲账）、stop_reason/
        handoff 复位——上一轮的残留不清，这一轮开局就是残局。"""
        out = {"ptok": -(state.get("ptok") or 0), "ctok": -(state.get("ctok") or 0),
               "stop_reason": None, "handoff": False}
        hit = screen(state.get("user_text") or "")
        if hit:
            out |= {"stop_reason": "safety", "reply": hit["reply"]}
        return out

    def context(state: TeachingState) -> dict:
        """第二步读语境：检查点已自动续上轮图状态（LangGraph 的 thread 机制，
        无需回表捞）；本节点只裁对话窗口——近 10 条进提示词，整串线程不吞。"""
        return {"history": list(state.get("history") or [])[-10:]}

    def retrieve(state: TeachingState) -> dict:
        """第三步取弹药：三腿检索本轮问题（user_id 恒带=结构闸，隔离绕不动）。
        块按 [ref] 编号、出处落 citations——与 tools.search_materials 同形契约；
        缺口账两处写点（工具消费端 + 这里）同一套语义：零命中记 zero，
        向量最高分低于登记线记 weak。安全拦下的句子不进检索更不进账。"""
        if state.get("stop_reason"):
            return {}
        q = state.get("user_text") or ""
        r = search(session, q, state["user_id"], top_k=TEACH_TOP_K)
        results = r["results"]
        cited, mats = [], []
        for item in results:
            cited.append({"chunk_id": item["id"], "material_id": item["material_id"],
                          "title": item["title"], "seq": item["seq"],
                          # D79 甲案：票面带编号——正文 [ref N]/[N] 标注按它对齐，
                          # 流尾「嘴账对齐」过滤靠这个键，前端票根也拿它显示序号
                          # （dict 在 append 前构造，len 尚是旧长度——+1 才是 1 起）
                          "ref": len(cited) + 1})
            mats.append({"ref": len(cited), "title": item["title"],
                         "seq": item["seq"], "content": item["content"]})
        tv = r.get("top_vec")
        ch = state.get("channel") or "web"
        if not results:
            record_gap(state["user_id"], q, None, ch)
        elif tv is not None and tv < GAP_WEAK:
            record_gap(state["user_id"], q, tv, ch)
        return {"knowledge": mats, "citations": cited}

    def diagnose(state: TeachingState) -> dict:
        """第四步读学生：全图唯一允许的非流式小调用（延迟预算 ≤1.5s）。
        吃近几条对话 + 本轮问题 + 上轮验懂结论（检查点续来的 understood），
        吐七键 JSON；坏文本当空表——宽容，回环不因此断链。"""
        if state.get("stop_reason"):
            return {}
        hist = state.get("history") or []
        recent = "\n".join(f"{m.get('role')}: {str(m.get('content'))[:200]}"
                           for m in hist[-6:])
        prev_u = state.get("understood")
        call, p, c = chat_once([
            {"role": "system", "content": _DIAG_PROMPT},
            {"role": "user", "content":
                f"【近几轮对话】\n{recent or '（首次开问）'}\n"
                f"【上一轮验懂结论】"
                f"{'未判定' if prev_u is None else ('已懂' if prev_u else '还没懂')}\n"
                f"【本轮学生问】\n{state.get('user_text') or ''}\n"
                "现在只输出 JSON。"}], tools=None, model=state.get("model"))
        d = extract_json(call.get("content") or "")
        return {"diagnosis": d if isinstance(d, dict) else {}, "ptok": p, "ctok": c}

    def generate(state: TeachingState) -> dict:
        """第五步开口讲：特征表→策略（W4 规则表，零 token）→ system 钉人设+
        四条铁律+策略演法+讲义块，整段流交 chat_stream：每个 delta 事件转一条
        custom 事件往外递。安全拦下时不调电厂——固定话术同样走一帧 delta，
        帧协议只认 delta，整段当一帧发会杀掉打字机效果，不发明新帧型。"""
        writer = get_stream_writer()
        if state.get("stop_reason"):
            writer({"delta": state.get("reply") or ""})
            return {}
        f = extract_features(state.get("user_text") or "",
                             diagnosis=state.get("diagnosis"),
                             history=state.get("history"),
                             round_no=state.get("round_no") or 0,
                             feynman_on=bool(state.get("feynman")))
        strat = pick_strategy(f)
        hint = _STRATEGY_HINT.get(strat) if strat else None
        mats = state.get("knowledge") or []
        mat_txt = "\n\n".join(f"[{m['ref']}] {m['title']}·第{m['seq']}段\n{m['content']}"
                              for m in mats)
        sys = ((state.get("system") or "") + "\n\n" + _IRON + "\n\n"
               + (f"本轮教学策略：{STRATEGY_CN[strat]}——{hint}" if hint
                  else "本轮未命中规则策略：自行选最合适的教法，五条铁律照守。")
               + (f"\n\n【讲义块（出处编号即此）】\n{mat_txt}" if mats else
                  "\n\n【讲义】材料里没查到这块内容：如实告诉学生资料里暂时没找到，"
                  "别编出处、别硬撑门面。"))
        msgs = [{"role": "system", "content": sys}]
        msgs += [{"role": m["role"], "content": m["content"]}
                 for m in (state.get("history") or [])]
        msgs.append({"role": "user", "content": state.get("user_text") or ""})
        reply, p, c = "", 0, 0
        for ev in chat_stream(msgs, tools=None, model=state.get("model")):
            if ev[0] == "delta":
                writer({"delta": ev[1]})
            else:
                p, c = ev[2], ev[3]
                reply = ev[1].get("content") or ""
        return {"strategy": strat, "reply": reply, "ptok": p, "ctok": c}

    def verify(state: TeachingState) -> dict:
        """第六步确认真懂：验懂权在学生回应手里（diagnose 判上轮反问的接球），
        不由模型自宣。未懂→轮数+1 存检查点；懂→负值冲账清零；
        转教师策略→举 handoff 旗。安全拦下的句子不算教学轮，不烧轮数。"""
        if state.get("stop_reason"):
            return {"understood": None}
        if state.get("strategy") == HANDOFF:
            return {"handoff": True, "understood": False}
        u = (state.get("diagnosis") or {}).get("understood")
        if u is False:
            return {"understood": False, "round_no": 1}
        if u is True:
            return {"understood": True, "round_no": -(state.get("round_no") or 0)}
        return {"understood": None}

    return {"safety": safety, "context": context, "retrieve": retrieve,
            "diagnose": diagnose, "generate": generate, "verify": verify}


def build_graph(checkpointer=None, *, session=None):
    """编译六节点线性图。checkpointer=None（降级态）：图照跑，只是回环
    轮数每条消息都归零——教学照常，没有断点。"""
    n = make_nodes(session)
    g = StateGraph(TeachingState)
    for name, fn in n.items():
        g.add_node(name, fn)
    g.add_edge(START, "safety")
    for a, b in [("safety", "context"), ("context", "retrieve"),
                 ("retrieve", "diagnose"), ("diagnose", "generate"),
                 ("generate", "verify")]:
        g.add_edge(a, b)
    g.add_edge("verify", END)
    return g.compile(checkpointer=checkpointer)


# ── 检查点基建三钉（施工图钉死，位置在此是因为只有图的家当归图管）──

_saver = None
_saver_dead = False


def checkpoint_dsn() -> str:
    """钉①：psycopg3 不认 SQLAlchemy 的 +psycopg 方言前缀——原样喂必炸，剥掉。"""
    from backend.db import DATABASE_URL as url
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def get_saver():
    """钉②：不借 from_conn_string 的短命上下文，自管连接池（min1/max4、
    autocommit、dict_row——PostgresSaver 说明书口径）。
    钉③：setup() 首用懒调、try 包死——任何失败=永久静默（_saver_dead），
    返回 None 让图无检查点编译。不进 lifespan：建表炸了会拖垮全箱启动。"""
    global _saver, _saver_dead
    if _saver is not None or _saver_dead:
        return _saver
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        pool = ConnectionPool(conninfo=checkpoint_dsn(), min_size=1, max_size=4,
                              kwargs={"autocommit": True, "row_factory": dict_row})
        saver = PostgresSaver(pool)
        saver.setup()   # 幂等：四张外来表已存在就原样跳过
        _saver = saver
    except Exception as e:
        print(f"[teaching_graph] 检查点不可用，降级为无断点模式："
              f"{type(e).__name__}: {str(e)[:200]}", flush=True)
        _saver_dead = True
        _saver = None
    return _saver
