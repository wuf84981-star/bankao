# ============================================================
# 全局测试底座（S9·W6 时新建）：把 Redis 钉在门外。
# 家法「单测全假件、零真网络」——本机 redis 箱虽就在箱边，但让回归测试
# 读写真箱=窗口残留互相污染（用例 A 的缓存会瞒住用例 B 的 PG 真相）。
# REDIS_URL 设成不可达后 get_client 置 _dead 永久静默 → 所有 W6 读写点
# 走 PG 原路降级，「Redis 全灭=逐字等于生产行为」同时被每条用例白验。
# test_short_memory 自己的假箱用例走 monkeypatch get_client，不受本闸影响。
# ============================================================
import pytest


@pytest.fixture(autouse=True)
def _redis_off(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "bogus://测试钉住在门外")
    import backend.short_memory as sm
    monkeypatch.setattr(sm, "_client", None)
    monkeypatch.setattr(sm, "_dead", False)
