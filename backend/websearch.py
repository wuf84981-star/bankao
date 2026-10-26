# ============================================================
# 联网搜索腿（S8 · D58 甲 2026-09-11 拍：Tavily，用户开了开关才准走这条腿）
# 家规三条：①密钥只在被调用那一刻从 env 读（TAVILY_API_KEY 值不进对话/git）；
# ②post 可注入——单测喂假传输（httpx.MockTransport 或哑函数），零真网络零真烧钱；
# ③一切外联故障（超时/DNS/配额尽）在这条腿里接住转人话，绝不外包炸主流程——
#   联网是兜底，兜底腿不许把主腿拖下水。
# ============================================================
import os

import httpx

TAVILY_URL = "https://api.tavily.com/search"


def tavily_search(query: str, *, max_results: int = 5, post=None) -> dict:
    """查一次网络，回 {"answer": 引擎侧摘要, "results": [{title,url,content,score}…]}。
    search_depth=basic：熟人期够用（advanced 双倍计费，先不烧）。
    post 注入位：测试塞假传输；生产默认 httpx.post，20 秒死刑（兜底腿不拖长对话）。"""
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("联网腿没配钥匙：.env 里放 TAVILY_API_KEY 后需重建容器生效")
    payload = {"query": query, "max_results": max_results,
               "search_depth": "basic", "include_answer": True}
    do = post or httpx.post
    r = do(TAVILY_URL, json=payload,
           headers={"Authorization": f"Bearer {key}"}, timeout=20)
    r.raise_for_status()
    data = r.json()
    data.setdefault("results", [])
    return data
