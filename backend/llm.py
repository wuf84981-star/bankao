# ============================================================
# 模型客户端（llm.py）：伴考的"真脑子"接线盒
# PRD 12.6 定案：OpenAI SDK 统一调多家——一个客户端形状通吃多平台。
# D60 甲 2026-09-11（用户拍板七路模型清单）：从单平台写死升级为
# 「型号→平台」路由表：每户的选模落在 agent_settings.model_choice（账在编排层查，
# 本层只收 model 参数——电厂保持无 DB 依赖）。换/加模型只动本表一处。
# ============================================================
import os

from openai import OpenAI

# ── D60 花名册：型号 → 平台。名单按用户 2026-09-11 拍板的原样（含其书写大小写），
#    名字若与平台真实 ID 有出入（404 model not found），修这一张表即可，业务零动。──
MODEL_PLATFORM: dict[str, str] = {
    "deepseek-flash": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "qwen3.8-max": "dashscope",
    "qwen3.8-flash": "dashscope",
    "GLM-5.3": "zhipu",
    "GLM-5.3-Flash": "zhipu",
    "GLM-5.2": "zhipu",
}
DEFAULT_MODEL = "deepseek-flash"   # 未落选模账的户用这个（=花名册在册首项）

# ── D64 甲 2026-09-11（积分差别计费）：型号 → 扣分倍率。1 积分=100 tokens 这个汇率
#    锚在基准脑 deepseek-flash 上；其余型号按「相对贵多少」挂倍率——贵模型烧真钱多，
#    扣分就多，堵住「切旗舰狂刷、账却和便宜脑一个价」的漏洞。
#    数字是起步桌牌（占位比例，非官网实价）：申请 key 时按各平台价目表校准一版即可，
#    改价=只动本表一格（MODEL_PLATFORM 同家法）。没登记的名字按 1.0 兜底。──
MODEL_MULTIPLIER: dict[str, float] = {
    "deepseek-flash": 1.0,     # 基准脑：1 分=100 tokens 对它字面成立
    "deepseek-v4-pro": 4.0,
    "qwen3.8-max": 4.0,
    "qwen3.8-flash": 1.0,
    "GLM-5.3": 3.0,
    "GLM-5.3-Flash": 1.0,
    "GLM-5.2": 2.0,
}

# 平台 → (OpenAI 兼容 base_url, env 键名)。钥匙值永不进代码/对话/git。
_PLATFORMS = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "dashscope": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "zhipu": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
}

_clients: dict[str, OpenAI] = {}   # 按平台懒建缓存：模块 import 不碰网，第一次用才建


def platform_of(model: str) -> str:
    """型号查平台；花名册没有的名字回退默认型号的落点（错名不炸现场，兜向最熟的脑）。"""
    return MODEL_PLATFORM.get(model, MODEL_PLATFORM[DEFAULT_MODEL])


def multiplier_of(model: str | None) -> float:
    """D64 扣分倍率：型号查表（None/没登记=按基准 1.0——脏账不炸计费，兜向最便宜的算法，
    宁可少扣也不多扣：多扣是冤枉钱，少扣是自家电。差一个桌牌位的损失可忽略）。"""
    return MODEL_MULTIPLIER.get(model if model in MODEL_MULTIPLIER else DEFAULT_MODEL, 1.0)


def key_ok(model: str) -> bool:
    """该型号所在平台的钥匙在不在（env 实时读，不缓存——.env 换钥匙重建容器后即刻反映）。"""
    return bool(os.environ.get(_PLATFORMS[platform_of(model)][1], "").strip())


def resolve_model(model: str | None) -> str:
    """把来路不明的 model 归一：认账的型号原样走，不认的兜向默认（防脏账炸电厂）。"""
    return model if model in MODEL_PLATFORM else DEFAULT_MODEL


def get_client(model: str = DEFAULT_MODEL) -> OpenAI:
    """建（或复用）该型号平台的客户端：密钥只从环境变量来——永不明写进代码。
    旧调用无参照走默认平台，形状兼容。"""
    plat = platform_of(model)
    if plat not in _clients:
        base, keyenv = _PLATFORMS[plat]
        key = os.environ.get(keyenv, "").strip()
        if not key:
            raise RuntimeError(f"{keyenv} 未配置（检查 .env 是否挂上；改过 .env 要重建容器）")
        _clients[plat] = OpenAI(api_key=key, base_url=base)
    return _clients[plat]


def chat_once(messages: list[dict], tools: list[dict] | None = None,
              model: str | None = None) -> tuple[dict, int, int]:
    """电厂跑一轮：把上下文喂进去，拿回 (助手消息 dict, prompt tokens, completion tokens)。
    助手这轮要么"开口"（content 有字）、要么"举手要工具"（tool_calls 非空）——
    要不要循环、跑几轮，是编排层（main.py chat）的事，本层只管一轮一结。
    usage 是模型账单的真实数字；举手那轮 content 常为空，属正常。
    model=D60 选模（None/不认=DEFAULT_MODEL）；按平台路由，烧哪家记哪家账。"""
    m = resolve_model(model)
    resp = get_client(m).chat.completions.create(
        model=m,
        messages=messages,
        tools=tools,   # None=纯聊天；给了说明书，模型才可能举手
        timeout=60,   # PRD 12.6：超时 60s；重试/切备用是后几刀的事
    )
    msg = resp.choices[0].message
    call: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        # 手抄成普通 dict，原样塞回 msgs 电厂才认得出"这是我上轮举的手"
        call["tool_calls"] = [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ]
    usage = resp.usage
    return (
        call,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
    )


def chat_stream(messages: list[dict], tools: list[dict] | None = None,
                model: str | None = None):
    """电厂流式跑一轮（四刀）：边想边吐，逐个产出事件——
      ("delta", 文字片段)                      → 可以直接往浏览器转发的字
      ("message", 助手整轮 dict, ptok, ctok)   → 本轮收尾：要么纯话，要么含 tool_calls
    举手的 arguments 在网络上是碎着来的，这里按 index 拼回完整函数呼叫；
    usage 默认不随流回，要用 stream_options 点名要（最后一块才带）。
    model=D60 选模，规则同 chat_once。"""
    m = resolve_model(model)
    stream = get_client(m).chat.completions.create(
        model=m,
        messages=messages,
        tools=tools,
        timeout=60,
        stream=True,
        stream_options={"include_usage": True},
    )
    content_parts: list[str] = []
    calls: dict[int, dict] = {}   # tool_call 碎片按 index 归拢拼装
    ptok = ctok = 0
    for chunk in stream:
        if chunk.usage:   # usage 挂在收尾块上，此时 choices 是空列表
            ptok = chunk.usage.prompt_tokens
            ctok = chunk.usage.completion_tokens
        if not chunk.choices:
            continue
        d = chunk.choices[0].delta
        if d is None:
            continue
        if d.content:
            content_parts.append(d.content)
            yield ("delta", d.content)
        for tc in (d.tool_calls or []):
            slot = calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                slot["id"] = tc.id
            if tc.function:
                slot["name"] += tc.function.name or ""
                slot["arguments"] += tc.function.arguments or ""
    call: dict = {"role": "assistant", "content": "".join(content_parts)}
    if calls:
        call["tool_calls"] = [
            {"id": v["id"], "type": "function",
             "function": {"name": v["name"], "arguments": v["arguments"]}}
            for k in sorted(calls) for v in [calls[k]]
        ]
    yield ("message", call, ptok, ctok)
