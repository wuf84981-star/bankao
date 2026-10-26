# ============================================================
# S9·W7 MCP 数学薄客户端（backend/mcp_client.py）—— 2026-10-11
# 懒起一个常驻子进程（sys.executable -m backend.mcp_math_server，
# 同镜像同解释器），手写 JSON-RPC（换行分隔）对话——SDK 的 client 腿
# 长在 asyncio 上，本后端全同步路由，为一只计算器拖事件循环不值。
# 铁律：
# - 失败不灾难：任何故障都回人话（此项不可验证），答题腿照常走；
# - 3 秒超时=杀子进程换血（sympy 死循环外部无法中断，只有杀），
#   下次调用懒重起自愈——蓝图里的「看门狗 5s poll」由此代替：
#   不碰数学的系统不必白养一个进程，自愈语义（下句即好）不变；
# - stderr 必须有泵：管道塞满子进程会卡死（经典坑），泵线程转 print；
# - 60 秒内 3 次失败=整腿熄火（_melted，重启 backend 才接回）——
#   与 short_memory._dead 同药方，防对门外的电厂重试风暴。
# 本模块自身不 import mcp/sympy——那些是孩子进程的事，主进程零依赖。
# ============================================================
import json
import subprocess
import sys
import threading
import time

REQUEST_TIMEOUT = 3.0      # 单次工具调用上限（秒）——sympy 硬算一般 <0.1
HANDSHAKE_TIMEOUT = 5.0    # initialize 握手等得起（孩子进程要冷启动 import sympy）
MELT_LIMIT = 3             # 60 秒内失败次数到数=熄火

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_req_id = 0
_fails: list[float] = []
_melted = False
_UNAVAILABLE = "数学验证服务暂时不可用，此项不可验证。"


def _pump_stderr() -> None:
    """把子进程 stderr 逐行转印到 backend 日志——不读管道它会塞死孩子。"""
    for line in _proc.stderr or []:
        print(f"[mcp-math] {line.rstrip()}", flush=True)


def _write(msg: dict) -> None:
    _proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
    _proc.stdin.flush()


def _read_line(timeout: float):
    """带超时读一行：短命线程持 readline，join 超时=这行没来。
    子进程被杀后管道关闭，旧线程自然收尾（daemon，不用回收）。"""
    box: list = []
    t = threading.Thread(target=lambda: box.append(_proc.stdout.readline()),
                         daemon=True)
    t.start()
    t.join(timeout)
    return box[0] if box else None


def _request(method: str, params: dict, timeout: float) -> dict:
    """发一条请求，只认同 id 的回话；途中撞见通知/杂音行一律跳过。"""
    global _req_id
    _req_id += 1
    _write({"jsonrpc": "2.0", "id": _req_id, "method": method, "params": params})
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError(method)
        line = _read_line(left)
        if line is None:
            raise TimeoutError(method)
        if line == "":
            raise ConnectionError("子进程输出已结束")
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("id") == _req_id:
            return msg


def _spawn() -> None:
    """起孩子 + 握手（initialize → initialized 通知），之后只发 tools/call。"""
    global _proc
    _proc = subprocess.Popen(
        [sys.executable, "-m", "backend.mcp_math_server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", bufsize=1)
    threading.Thread(target=_pump_stderr, daemon=True).start()
    _request("initialize", {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "bankao-backend", "version": "1"}},
        HANDSHAKE_TIMEOUT)
    _write({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _kill_quiet() -> None:
    global _proc
    if _proc:
        try:
            _proc.kill()
        except Exception:
            pass
        _proc = None


def _note_failure() -> None:
    """记一笔失败；60 秒滑窗到 3 次=整腿熄火（幂等于 _dead，不再重试）。"""
    global _melted
    now = time.monotonic()
    _fails.append(now)
    while _fails and now - _fails[0] > 60:
        _fails.pop(0)
    if len(_fails) >= MELT_LIMIT:
        _melted = True
        print("[mcp_client] 连续失败到限，数学腿熄火（重启 backend 才接回）",
              flush=True)


def call(tool: str, arguments: dict) -> str:
    """唯一门面：调一只数学工具，永远回一句人话（不抛异常）。
    孩子侧故障就地重试一次的设计：SIGKILL 落地是异步的——poll() 可能
    还没见尸、请求就写向垂死孩子（EOF）。纯数学调用无状态幂等，
    重起一次再试不产生任何副作用；「kill 后下句自愈」由此不怕竞态。
    超时不重试（表达式本身是锅，重来还是超）。"""
    with _lock:
        if _melted:
            return _UNAVAILABLE
        for attempt in (1, 2):
            try:
                if _proc is None or _proc.poll() is not None:
                    _spawn()   # 懒起/见尸重起都在这一个口
                resp = _request("tools/call",
                                {"name": tool, "arguments": arguments},
                                REQUEST_TIMEOUT)
                break
            except TimeoutError:
                _kill_quiet()
                _note_failure()
                return "这道题计算超时（表达式可能过于复杂），此项不可验证。"
            except Exception as e:
                _kill_quiet()
                if attempt == 2:
                    _note_failure()
                    print(f"[mcp_client] 调用故障 {type(e).__name__}: "
                          f"{str(e)[:200]}", flush=True)
                    return _UNAVAILABLE
                # 第 1 次失手：换血重来（上面 _proc is None 分支会重起）
        if "error" in resp:
            # 协议层报错（工具名不存在之类）=孩子答了但答歪，不算腿故障不记失败
            return f"数学工具报错：{str(resp['error'].get('message', ''))[:120]}"
        parts = resp.get("result", {}).get("content") or []
        text = " ".join(p.get("text", "") for p in parts
                        if isinstance(p, dict) and p.get("type") == "text")
        return text or "（工具返回为空）"
