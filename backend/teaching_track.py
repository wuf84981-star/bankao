# ============================================================
# S9·W5 教学轨接线（backend/teaching_track.py）—— 2026-10-11
# /api/chat/stream 里的「教学轨」分叉：五关全过才进状态图，
# 任何一关失手一字不差回事务轨（误判进教学轨代价高、回旧路代价低——
# 拿不准一律 False，与 intent.py 同一偏斜立场）。
# 回滚旗 TEACHING_TRACK_ENABLED=0 → 本轨整个消失，账/表/检查点原地不动。
# 帧协议一帧不发明：custom→delta、: ping 心跳、done 键集与事务轨逐项同构；
# 真账只在流尾一个事务——检查点是排障工具，不是账本（D71 铁律）。
# main.py 只花两行：一句 teaching_eligible、一句 yield from。
# ============================================================
import json
import os
from collections.abc import Iterator
from datetime import date

from sqlalchemy import select

from backend.analytics import _track
from backend.db import SessionLocal
from backend.intent import is_teaching_question
from backend.models import AgentSetting, Chunk, Message, UsageLog
from backend.orchestrator import DAILY_QUOTA, SYSTEM_PROMPT, _system_for
from backend.points import LOW_BALANCE_WARN, balance_of, spend
from backend.short_memory import note_message, with_summary
from backend.teaching_graph import build_graph, get_saver
from backend.tools import cited_by_reply, model_for


def _sse(obj: dict) -> str:
    """与 main._sse 同形契约（帧协议键必须一致）；在此重抄一份，
    因为 main import 本文件、反向取用会成循环依赖——两处的「形状」由测试钉住。"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def track_enabled() -> bool:
    """回滚旗：env 里 TEACHING_TRACK_ENABLED 置 0 即整轨消失（默认开）。"""
    return os.getenv("TEACHING_TRACK_ENABLED", "1").strip() != "0"


def has_materials(session, user_id: int) -> bool:
    """有材料可教才教：本户库里至少一个块。判「有没有块」而非「有没有 done」——
    没点火的块仍走关键词/分词两腿，教学轨照样有料。"""
    return session.execute(select(Chunk.id).where(Chunk.user_id == user_id)
                           .limit(1)).first() is not None


# 人设举手指令与教学轨「无手」的冲突（真机漏案 2026-10-12：qwen 把整句
# 工具调用 XML 吐进正文）：SYSTEM_PROMPT 命「考点问题必须先调
# search_materials」，而教学轨 generate 腿 tools=None——模型遵命又无处
# 举手，就模仿训练格式写进正文。铁律第五条喊「别伪调用」治不了指令打架，
# 解法是就地改写这一句：讲义本就由 retrieve 节点代搜，直接告诉它
# 「已备好，无需举手」。两串逐字对齐 orchestrator.SYSTEM_PROMPT 原句；
# 对不上就不换（宁留原句——replace 静默失手由单测的存在性断言兜住）。
_TEACH_TOOL_OLD = (
    "用户问具体考点、题目做法、公式概念时，先调用 search_materials 查他上传的资料，"
    "用了哪块材料就在对应句末标注 [ref 编号]；资料零命中时基于通用知识回答并明说"
    "『资料中未找到相关内容』，禁止把编的出处安到资料头上（PRD 632 防幻觉）。")
_TEACH_TOOL_NEW = (
    "用户问具体考点、题目做法、公式概念时：本轮资料已由系统代搜，结果就在下文讲义块里"
    "（块为空即零命中）——据块作答，用了哪块就在对应句末标注编号；零命中时基于通用知识"
    "回答并明说『资料中未找到相关内容』，禁止把编的出处安到资料头上（PRD 632 防幻觉）。"
    "本轨永远不会调用任何工具，也无需调用——回复正文里出现任何形式的工具调用文本"
    "（<tool_call>、函数名加参数 JSON 等）都是事故。")


def _teaching_system(user_id: int, session, conv) -> str:
    """教学轨 system：同一串人设就地换掉「必须先举手」那句（冲突根除见上），
    再叠滚动摘要——与事务轨 with_summary 同源同法，两轨同脑。"""
    sys_txt = _system_for(user_id, session)
    if _TEACH_TOOL_OLD in sys_txt:
        sys_txt = sys_txt.replace(_TEACH_TOOL_OLD, _TEACH_TOOL_NEW)
    return with_summary(sys_txt, conv)


def user_teaching_on(session, user_id: int) -> bool:
    """D81 挂招牌刀（用户拍板）：教学轨用户级闸。NULL=从没动过开关=开——
    默认档只活在这一个函数（与 model_choice 同法，不冻进列默认值）；
    False=用户在设置页关了「苏格拉底式引导」，问题全走事务轨直答。
    env 旗是运维总闸、本闸是用户意愿闸，两级串联互不越权。"""
    val = session.execute(select(AgentSetting.teaching_mode)
                          .where(AgentSetting.user_id == user_id)).scalar()
    return val is not False


def user_feynman_on(session, user_id: int) -> bool:
    """D89 费曼意愿闸（用户拍板加招）：教学轨内 FEYNMAN 一招的开档。
    NULL=从没动过=开（默认档只活在这一个函数，与 user_teaching_on 同法）；
    False=他说「懂了」也不请他复述。从属大门：教学轨都没进，本闸无台可唱。"""
    val = session.execute(select(AgentSetting.feynman_mode)
                          .where(AgentSetting.user_id == user_id)).scalar()
    return val is not False


def teaching_eligible(session, user_id: int, user_text: str) -> bool:
    """分流四查全 AND：env 旗开 → 用户没关教学模式 → 有材料 → 是教学问句
    （intent 纯函数终审）。"""
    if not track_enabled():
        return False
    if not user_teaching_on(session, user_id):
        return False
    if not has_materials(session, user_id):
        return False
    return is_teaching_question(user_text, has_materials=True)


# 甲案·嘴账对齐（D79/D80，2026-10-12 用户拍板）：小票只展示正文真引用的块。
# D82（2026-10-18）闸升格两轨共闸，函数搬去 tools.cited_by_reply（票据记账本
# 同家同住）——此处与事务轨消费的是同一判据，两轨永不各说各话。


def teaching_events(*, user_id: int, username: str, user_msg: str, conv,
                    history, tool_session, today: date, spent: int,
                    model: str | None = None) -> Iterator[str]:
    """教学轨正身：状态图走一遍、delta 帧原样外转、流尾一个事务结算。
    入参对齐 main 的闭包变量——分叉处 main 只许一句 yield from。
    教学轨不调工具（used_tools 恒空是立场不是遗漏：讲义问答不需要举手循环）。"""
    if model is None:
        model = model_for(tool_session, user_id)   # D60 选模同账；D64 倍率按它折
    graph = build_graph(get_saver(), session=tool_session)
    state_in = {
        "user_text": user_msg,
        "user_id": user_id,
        "channel": "web",
        "model": model,
        "system": _teaching_system(user_id, tool_session, conv),
        # W6：main 已交纯 dict 窗（window_get 产物），直搬进图状态（JSON 资格不变）
        "history": list(history),
        # D89：费曼闸每轮查一次账塞进图（意愿要即时生效，不经检查点续存旧档）
        "feynman": user_feynman_on(tool_session, user_id),
    }
    final: dict = {}
    try:
        yield ": ping\n\n"   # 与事务轨同款心跳：检索+诊断腿的静默期不被当断线
        for kind, payload in graph.stream(
                state_in,
                config={"configurable": {"thread_id": f"conv:{conv.id}"}},
                stream_mode=["custom", "values"]):
            if kind == "custom":
                yield _sse(payload)     # generate 节点的 delta 事件原样转帧
            else:
                final = payload         # values 模式每超步都发，留最后一份=末态
    except Exception as e:
        # 电厂故障留声（与 main 流式腿同药方）：error 帧后直接回——
        # 半句不落库（BR-11 对教学轨同样成立：走到这没记账就是没扣）
        print(f"[teaching_track] 图腿故障 {type(e).__name__}: {str(e)[:280]}",
              flush=True)
        yield _sse({"error": "模型电厂暂时故障，稍后再试"})
        return
    reply = final.get("reply") or ""
    ptok = final.get("ptok") or 0
    ctok = final.get("ctok") or 0
    raw_cites = final.get("citations") or []
    citations = cited_by_reply(raw_cites, reply)   # D79 甲案：票面以嘴为准（D82 起两轨共闸）
    # 排障留声（检查点=排障工具的正解姿势：一行日志，不落任何账）：
    print(f"[teaching_track] conv={conv.id} strategy={final.get('strategy')} "
          f"round_no={final.get('round_no')} handoff={bool(final.get('handoff'))} "
          f"tokens={ptok}+{ctok} cites={len(citations)}/{len(raw_cites)}", flush=True)
    with SessionLocal() as session:
        # 流尾结算（main :1207-1215 的复制形状）：教练行+流水+积分一笔事务；
        # 用户行已随进门落账——这里补第二份就是双胎账（D67 家法）
        session.add(Message(conversation_id=conv.id, role="assistant",
                            content=reply, token_count=ctok,
                            citations=citations or None))
        session.add(UsageLog(user_id=user_id, day=today, tokens=ptok + ctok))
        cost = spend(session, user_id, ptok + ctok, model, today)
        session.commit()
        note_message(conv.id, "assistant", reply)   # W6：教练句落库添窗（与事务轨同点同法）
        balance = balance_of(session, user_id)
    _track(user_id, "chat_message_sent", channel="web")   # D55 埋点：两轨同账
    remaining = DAILY_QUOTA - spent - ptok - ctok
    notice = (f"积分余额只剩 {balance}——记得签到续口粮，省着点用"   # 资产命门优先播报
              if balance <= LOW_BALANCE_WARN
              else (f"今日剩余配额约 {max(remaining, 0)} token（不足 10%）"
                    if remaining < DAILY_QUOTA * 0.1 else None))
    yield _sse({"done": {"remaining": remaining, "notice": notice,
                         "balance": balance, "points_spent": cost,
                         "used_tools": [], "username": username,
                         "conv_id": conv.id, "citations": citations}})
