# ============================================================
# S9·W6 短期记忆（backend/short_memory.py）—— 2026-10-11
# 两件事：会话窗热缓存（Redis 近 20 条）+ 前情摘要读取助手
# （conversations.context_summary 预建列的读方，写方归压缩闹钟）。
# 降级语义钉死（施工图铁律）：**Redis 全灭时行为逐字等于今天的代码**——
# 读路 window_get 未命中回落原 PG select 一条不减，写路静默丢刀。
# 永久静默姿势与 teaching_graph.get_saver 同款：连接失败置 _dead 后
# 不再重试（防重试风暴）；PG 是唯一真账，Redis 只是热副本。
# ============================================================
import json
import os

from sqlalchemy import select

from backend.models import Message

WINDOW_N = 20          # 与两处旧读取点（orchestrator/main 流式轨）的 limit(20) 同口径
WINDOW_TTL = 7200      # 两小时无读写自动蒸发——冷会话不占内存，PG 随时能重建


def get_client():
    """懒建单例 + 永久静默：ping 不通=整文件降级为直读 PG，永不炸答题腿。
    socket_timeout 1.5s：Redis 卡死时也不许把回复腿拖长。"""
    global _client, _dead
    if _client is not None or _dead:
        return _client
    try:
        import redis
        c = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            socket_timeout=1.5, socket_connect_timeout=1.5, decode_responses=True)
        c.ping()
        _client = c
    except Exception as e:
        print(f"[short_memory] Redis 不可用，永久降级为直读 PG："
              f"{type(e).__name__}: {str(e)[:200]}", flush=True)
        _dead = True
        _client = None
    return _client


_client = None
_dead = False


def window_get(session, conv_id: int) -> list[dict]:
    """读会话窗（正序 [{role, content}] 纯 dict——图状态与提示词组装只认这个形状）。
    命中：LRANGE 整窗直还，PG 一眼不查。
    未命中/坏窗/缓存腿不通：原 PG select 一字不改再查一遍 + 回填。
    解析不过的任何元素=整窗作废回落 PG——宁可多查一遍，不把烂数据喂进提示词。"""
    client = get_client()
    key = f"mem:conv:{conv_id}"
    if client is not None:
        try:
            rows = client.lrange(key, 0, -1)
            if rows:
                out = [json.loads(r) for r in rows]
                if all(isinstance(d, dict) and "role" in d and "content" in d
                       for d in out):
                    return out
        except Exception:
            pass   # 缓存腿任何失手都不许慢回复腿
    hist = list(session.scalars(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.id.desc()).limit(WINDOW_N)
    ).all())[::-1]
    dicts = [{"role": m.role, "content": m.content} for m in hist]
    if client is not None and dicts:
        try:
            client.delete(key)
            client.rpush(key, *[json.dumps(d, ensure_ascii=False) for d in dicts])
            client.ltrim(key, -WINDOW_N, -1)
            client.expire(key, WINDOW_TTL)
        except Exception:
            pass
    return dicts


def note_message(conv_id: int, role: str, content: str) -> None:
    """落库后往窗尾追一条（写路只添不删——真账在 PG，这里掉刀只是窗短一条，
    下轮读取回填自愈）。窗不在场时跳过：不给新会话写半窗孤儿，
    第一条消息的窗口交给下次 window_get 全窗回填。"""
    client = get_client()
    if client is None:
        return
    key = f"mem:conv:{conv_id}"
    try:
        if not client.exists(key):
            return
        client.rpush(key, json.dumps({"role": role, "content": content},
                                     ensure_ascii=False))
        client.ltrim(key, -WINDOW_N, -1)
        client.expire(key, WINDOW_TTL)
    except Exception:
        pass


def try_lock(name: str, secs: int = 300) -> bool:
    """提示性锁（SET NX EX）：只防双实例重复工，**不是正确性闸**——
    Redis 灭/摸不到一律放行 True，幂等交给压缩写回的 until_id 乐观条件
    （「Redis 灭也照跑」是压缩闹钟的施工图口径，锁只是省运费的礼貌）。"""
    client = get_client()
    if client is None:
        return True
    try:
        return bool(client.set(f"lock:{name}", "1", nx=True, ex=secs))
    except Exception:
        return True


def summary_of(conv) -> str | None:
    """前情摘要正文：context_summary 列的 JSON 四要素 {until_id, text, model, at}
    （Text 列手写 JSON——只有本文件与压缩闹钟读写，SQL 侧零 JSON 查询，零迁移）。
    坏数据当没摘要——教练宁可不记得旧账，也不把垃圾喂进提示词。"""
    raw = getattr(conv, "context_summary", None)
    if not raw:
        return None
    try:
        t = json.loads(raw).get("text")
        return t if isinstance(t, str) and t.strip() else None
    except Exception:
        return None


def with_summary(system_txt: str, conv) -> str:
    """前情摘要拼进 system 尾巴（有摘要才拼）——三条轨（answer_turn/流式事务轨/
    教学轨）共用这一处真源，抄三份必漂移（D41 兑现刀的接法）。"""
    summ = summary_of(conv)
    if not summ:
        return system_txt
    return system_txt + f"\n\n【前情摘要（系统滚动压缩，非原话）】\n{summ}"
