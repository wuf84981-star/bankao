# ============================================================
# Embedding 电厂（embedder.py）：一块文字 → 一串 1024 维意思坐标
# 供应商 = 千问 text-embedding-v3（D1 拍板，PRD 517 行原案）：
# 百炼提供 OpenAI 兼容接口，复用船上现成 openai SDK——零新依赖。
# key 从 .env 的 DASHSCOPE_API_KEY 读；未配置时回人话不炸现场
# （key 后置配置期：代码先搭好，填上即通电）。
# ============================================================
import os

from openai import OpenAI

EMBED_MODEL = "text-embedding-v3"
EMBED_DIM = 1024        # PRD 729：维度绑库行列宽，换模型=全库重嵌，别乱改
BATCH = 10              # 千问 embeddings 接口单次条数上限，超了分批喂

_client: OpenAI | None = None


def get_embed_client() -> OpenAI:
    """懒加载单例（llm.py 同款形状第二家）：import 不碰网，首用才建客户端"""
    global _client
    if _client is None:
        key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not key:
            raise RuntimeError(
                "DASHSCOPE_API_KEY 还没配置——千问电厂未通电，请把 .env 里那行填上")
        _client = OpenAI(
            api_key=key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    return _client


def embed(texts: list[str]) -> tuple[list[list[float]], int]:
    """进块列表，出 (向量列表, 本次消耗 tokens)——全局顺序与入参对齐。
    单批 ≤BATCH 分趟请求；返回按 index 字段对号入座，不赌自然顺序。
    tokens 汇总每批 usage.total_tokens（PRD 625：调用要记账，货币从这递出去；
    个别端点 usage 缺席时按 0 保守入账，不虚报也不漏报结构）。"""
    client = get_embed_client()
    vectors: list[list[float]] = []
    tokens = 0
    for i in range(0, len(texts), BATCH):
        resp = client.embeddings.create(model=EMBED_MODEL, input=texts[i:i + BATCH])
        batch = sorted(resp.data, key=lambda d: d.index)   # 显式对号
        vectors.extend(d.embedding for d in batch)
        tokens += getattr(resp.usage, "total_tokens", 0) or 0
    return vectors, tokens
