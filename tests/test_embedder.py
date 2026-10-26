# ============================================================
# Embedding 电厂离线单测：不碰网（key 后置期只能验机械件）
# 真机断言（语义距离演示）挂账，等 .env 填入 DASHSCOPE_API_KEY 后清
# ============================================================
import types

import pytest

from backend import embedder


def test_missing_key_human_error(monkeypatch):
    """没配 key：要人话报错，不要 KeyError/ AttributeError 糊用户一脸"""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    embedder._client = None   # 单例复位，防别的测试先建了客户端
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        embedder.get_embed_client()


class Fake电厂:
    """假电厂：不联网，按入参回「文本长度」当指纹向量，并记录每批条数"""
    def __init__(self):
        self.calls = []
        self.embeddings = self

    def create(self, model, input):
        assert model == embedder.EMBED_MODEL
        self.calls.append(len(input))
        data = [types.SimpleNamespace(index=i, embedding=[float(len(t))])
                for i, t in enumerate(input)]
        # usage 也造假：运费账要能被离线测到（每批按条数×7 记，可核对）
        return types.SimpleNamespace(data=list(reversed(data)),
                                     usage=types.SimpleNamespace(total_tokens=len(input) * 7))


def test_batch_split_and_order(monkeypatch):
    """25 块 → 分批 10/10/5；电厂故意倒序返回，输出仍须与入参逐条对齐；运费汇总"""
    fake = Fake电厂()
    monkeypatch.setattr(embedder, "get_embed_client", lambda: fake)
    texts = ["甲" * (i + 1) for i in range(25)]     # 第 i 块长度 i+1，可定位
    out, tok = embedder.embed(texts)
    assert fake.calls == [10, 10, 5]                 # 分批形状
    assert len(out) == 25
    assert [v[0] for v in out] == [float(i + 1) for i in range(25)]   # 顺序分毫不差
    assert tok == 25 * 7                             # 三批 usage 汇总入账


def test_empty_input_no_call(monkeypatch):
    """空列表进：零趟请求，回空表零运费——别让电厂白点火"""
    fake = Fake电厂()
    monkeypatch.setattr(embedder, "get_embed_client", lambda: fake)
    assert embedder.embed([]) == ([], 0)
    assert fake.calls == []
