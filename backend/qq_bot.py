# ============================================================
# 伴考 · S6 B 段 bot 入口（D23 甲 · D28 甲：与 api 同镜像同账本）
# 这一层薄得只剩「耳朵接上嘴」：NapCat（登着 QQ 小号的箱子）把私聊
# 事件 POST 进来 → 转交 backend.qq.handle_qq_event → 回话原路发回。
# 大脑一行不新写——绑定闸、认码链、编排心脏全在 A 段备好的货里。
# 形状：NoneBot2 的 FastAPI driver 直接暴露 ASGI app，uvicorn 拉起；
# 不架跨箱 HTTP 调后端——同 import 共库（PRD 16 章 bot 注释原形）。
# ============================================================
import asyncio

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter
from nonebot.adapters.onebot.v11 import MessageEvent

from backend.db import SessionLocal
from backend.qq import handle_qq_event, push_via_onebot

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotAdapter)

# 收所有消息事件，私聊与否在函数里自筛（message_type 是 v11 事件自带字段）——
# 不赌 rule 库的现成谓词，判据摊在明面上。
matcher = nonebot.on_message()


@matcher.handle()
async def _recv(event: MessageEvent):
    if event.message_type != "private":
        return   # 群里刷屏不关伴考的事
    # str() 一把撸的老路作废：message[] 段里的图在字符串形态是 CQ 码，塞进大脑
    # 只会污染上下文。遍历分段各归各——文字段拼字进脑，图片段取网络 url 递给
    # OCR 通道（D38 甲：url 直喂 qwen-vl，零下载零落盘；没有 url 的段不要，
    # 本地 file 路径 qwen-vl 隔着容器够不着）。
    text = "".join(seg.data.get("text", "") for seg in event.message
                   if seg.type == "text").strip()
    images = [{"url": u, "ref": {"kind": "url", "url": u}}
              for seg in event.message if seg.type == "image" and (u := seg.data.get("url"))]
    if not text and not images:
        return   # 纯表情/空消息：不进大脑不烧电
    def work():
        # handle_qq_event 是同步阻塞函数（模型一答几十秒）——挪去线程池跑，
        # 别把 bot 的事件循环冻住（同一条循环还要收下一位 QQ 的话）。
        with SessionLocal() as s:
            return handle_qq_event(s, str(event.user_id), text, images=images or None)
    reply = await asyncio.to_thread(work)
    # S6 真机血案·甲案：回话不走 nonebot 自带的 send——NapCat 推事件时自报的
    # API 地址是 127.0.0.1:3000（回环），同容器能用、跨容器必死（bot 容器里
    # 回环敲的是自己），send 当场 ApiNotAvailable。改走已验过的推送腿
    # push_via_onebot：地址写在 env（ONEBOT_API_URL），与提醒推送同一本地址账。
    # 同步 httpx 同样挪线程池；发失败只记日志——账是大脑落的，嘴没到不算逻辑失败。
    sent = await asyncio.to_thread(push_via_onebot, str(event.user_id), reply)
    if not sent:
        nonebot.logger.error(f"QQ 回话未送达：user={event.user_id}")


# NapCat 的 HTTP POST 打到本服务根路径即入上表（v11 adapter 自动挂路由）；
# 回话不走事件通道——经 push_via_onebot 主动打 NapCat 的 HTTP server（见上·甲案）。
app = nonebot.get_asgi()
