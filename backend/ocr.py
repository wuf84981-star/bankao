# ============================================================
# 拍照汇报的 OCR 通道腿（S7 四刀 · F-09/D36 甲 · PRD 518 选型 qwen-vl-plus）
# 「随 F-18 的 OCR 通道」那条通道的第一处上岗：图片进、文字出。
# 与 embedder 同家规矩：百炼 OpenAI 兼容接口，复用现成 openai SDK——
# 连接对象本就与模型无关（model 写在每次请求里），不另起炉灶建第二只客户端。
# 纪律两条（与电厂家规同族）：
# ①运费入账——OCR 也是烧钱的腿，tokens 由调用方记进户主 usage_logs；
# ②单测绝不真调——真 .env 里的 key 在测试里就是真钞票，注入假腿是铁律。
# 「原图不进模型上下文」的 9.1 承诺：本模块只在 OCR 这一跳把图递给千问
# （它就是干这个的），递进对话大脑的永远只有转写出的文本。
# ============================================================
import base64

from openai import OpenAI

from backend.embedder import get_embed_client

OCR_MODEL = "qwen-vl-plus"    # PRD 518 原案；换模型=改这行，别处零碰

_PROMPT = (
    "这是备考用户的笔记/刷题照片。请把图中文字完整转写：保留条目结构与公式"
    "（用普通文本近似即可）；图表、算式等非文字内容用括号简述。"
    "看不清的地方绝不猜——凡看不清处，原样标注【没看清】三字。"
    "只输出转写内容，不要评论、不要总结。"
)


def build_image_part(data: bytes | None = None, url: str | None = None) -> dict:
    """OneBot 的 http 图链与网页的字节流共用一个消息零件：
    字节流折成 data URL（qwen-vl 兼容接口认这个形状），url 原样直通。"""
    if url:
        return {"type": "image_url", "image_url": {"url": url}}
    if data is None:
        raise ValueError("图与 url 至少给一个")
    return {"type": "image_url",
            "image_url": {"url": "data:image;base64," + base64.b64encode(data).decode()}}


def transcribe_image(client: OpenAI | None = None, *, data: bytes | None = None,
                     url: str | None = None) -> tuple[str, int, int]:
    """图片 → 转写文本。返回 (text, prompt_tokens, completion_tokens)。
    缺 key/超时/接口炸一律抛错——降级话术是调用方的活，这里不吞故障只如实炸，
    吞了故障的 OCR 会把「电厂没电」伪装成「图上没字」。"""
    cli = client or get_embed_client()
    resp = cli.chat.completions.create(
        model=OCR_MODEL,
        messages=[{"role": "user", "content": [
            build_image_part(data=data, url=url),
            {"type": "text", "text": _PROMPT},
        ]}],
        timeout=60,   # PRD 625：OCR 同 60s 纪律
    )
    text = (resp.choices[0].message.content or "").strip()
    usage = getattr(resp, "usage", None)
    return (text,
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0)


def looks_unclear(text: str) -> bool:
    """低置信判定（程序执法，不信模型语气）：转写里出现【没看清】或整段为空，
    就是「没看清」——PRD 15 章第 4 条的话术由调用方负责说。"""
    return (not text.strip()) or "【没看清】" in text
