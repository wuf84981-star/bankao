# ============================================================
# S9·W7 数学 MCP 离线回归（backend/mcp_math_server.py + mcp_client.py）
# 断言主线：服务器四手是纯函数可直调（幂边界/无实解过滤/注入白名单拒）、
# 客户端协议腿形状（initialize→initialized→tools/call、杂音行跳过、
# 只认自己 id）、超时=杀进程回人话、kill 后下句懒重起自愈、
# 60 秒 3 败=整腿熄火不再起、协议 error 不算腿故障不记账。
# 全假进程注入（FakeProc 剧本行），不 spawn 真 sympy 子进程。
# ============================================================
import json
import time

import pytest

import backend.mcp_client as mc
import backend.mcp_math_server as srv


# ── 服务器四手直调（纯函数层，零协议零进程）──

def test_server_solve_edges():
    assert "x = 3" in srv.solve_equation("2*x+3=9", "x")
    assert "x = -3" in srv.solve_equation("x^2=9", "x")       # 双根全列
    assert "无实数解" in srv.solve_equation("x^2+1=0", "x")    # 虚根过滤掉
    assert "x = 5" in srv.solve_equation("x-5")               # 无等号按=0


def test_server_injection_rejected():
    """白名单闸门：引号/点号进不来，sympify 注入面整片堵死。"""
    for bad in ("__import__('os')", "x.__class__", "[1,2]"):
        out = srv.solve_equation(bad, "x")
        assert "拒绝解析" in out or "算不了" in out


def test_server_simplify_stats_verify():
    assert "2*x + 1" in srv.simplify_expression("(x+1)^2-x^2")
    line = srv.compute_statistics([1, 2, 2, 4])
    assert "均值 2.25" in line and "众数 2" in line and "极差 3" in line
    assert "空" in srv.compute_statistics([])
    assert "满足" in srv.verify_answer("x^2=4", 2)
    assert "残差" in srv.verify_answer("x^2=4", 3)
    assert "算不了" in srv.verify_answer("x^2=4", 3, "y")      # 自由符号 x 没代掉，float() 炸→人话收场


# ── 客户端假进程腿（协议形状/超时/自愈/熄火）──

class FakeStdin:
    def __init__(self):
        self.lines = []

    def write(self, s):
        self.lines.append(s)

    def flush(self):
        pass


class FakeStdout:
    """剧本行队列（持引用，戏可中途续）；续完 block=True 就装死不回话，
    eof=True 则空队即回 ''（连接断）。"""
    def __init__(self, queued, eof=True, block=False):
        self.q = queued
        self.eof = eof
        self.block = block

    def readline(self):
        if self.q:
            return self.q.pop(0)
        if self.block:
            time.sleep(2)
            return "\n"
        return ""


class FakeProc:
    def __init__(self, stdin, stdout):
        self.stdin, self.stdout, self.stderr = stdin, stdout, []
        self.dead = False
        self.killed = False

    def poll(self):
        return 1 if self.dead else None

    def kill(self):
        self.killed = True
        self.dead = True


def _resp(i, payload):
    return json.dumps({"jsonrpc": "2.0", "id": i, **payload},
                      ensure_ascii=False) + "\n"


def _init_ok(i=1):
    return _resp(i, {"result": {"protocolVersion": "2024-11-05",
                                "capabilities": {}, "serverInfo": {"name": "s"}}})


@pytest.fixture()
def fresh():
    """模块级状态复位——熄火旗/失败账/进程引用都不许漏给下一条。"""
    mc._proc, mc._melted, mc._req_id = None, False, 0
    mc._fails.clear()
    yield mc
    mc._proc, mc._melted, mc._req_id = None, False, 0
    mc._fails.clear()


def test_call_handshake_shape(fresh, monkeypatch):
    stdin = FakeStdin()
    proc = FakeProc(stdin, FakeStdout([
        _init_ok(),
        '{"jsonrpc":"2.0","method":"notifications/message"}\n',   # 杂音行须跳过
        _resp(2, {"result": {"content": [{"type": "text", "text": "解为：x = 3"}]}}),
    ]))
    monkeypatch.setattr(mc.subprocess, "Popen", lambda *a, **k: proc)
    assert fresh.call("solve_equation", {"eq": "2*x+3=9"}) == "解为：x = 3"
    sent = [json.loads(s) for s in stdin.lines]
    assert sent[0]["method"] == "initialize" and sent[0]["id"] == 1
    assert sent[1]["method"] == "notifications/initialized" and "id" not in sent[1]
    assert sent[2]["method"] == "tools/call"
    assert sent[2]["params"] == {"name": "solve_equation",
                                 "arguments": {"eq": "2*x+3=9"}}
    assert not proc.killed                       # 正常调用不杀进程（常驻）


def test_timeout_kills_then_next_call_resets(fresh, monkeypatch):
    """3 秒到点=杀进程换血（超时值 monkeypatch 成 0.2 免得真等），回人话。"""
    monkeypatch.setattr(fresh, "REQUEST_TIMEOUT", 0.2)
    proc = FakeProc(FakeStdin(), FakeStdout([_init_ok()], block=True))
    monkeypatch.setattr(mc.subprocess, "Popen", lambda *a, **k: proc)
    assert "超时" in fresh.call("solve_equation", {"eq": "x=1"})
    assert proc.killed is True                   # 死循环孩子只能外部杀
    assert fresh._proc is None and len(fresh._fails) == 1
def test_kill9_self_heals_next_call(fresh, monkeypatch):
    """kill -9 自愈形状：poll 见尸→下次 call 懒重起新进程，句照回。
    号序：第 n 任进程 initialize=id(2n+1)、tools/call=id(2n+2)（_req_id 全局续号）。"""
    spawned = []
    script = ["化简结果：2*x + 1", "解为：x = 1"]   # 每任进程一嘴戏
    def factory(*a, **k):
        i = len(spawned)
        q = [_init_ok(2 * i + 1),
             _resp(2 * i + 2, {"result": {"content": [
                 {"type": "text", "text": script[i]}]}})]
        p = FakeProc(FakeStdin(), FakeStdout(q))
        spawned.append(p)
        return p
    monkeypatch.setattr(mc.subprocess, "Popen", factory)
    assert "2*x + 1" in fresh.call("simplify_expression", {"expr": "(x+1)^2-x^2"})
    spawned[0].dead = True                       # 模拟外面 kill -9
    assert "x = 1" in fresh.call("solve_equation", {"eq": "x=1"})   # 下句自愈
    assert len(spawned) == 2


def test_three_failures_melt_leg(fresh, monkeypatch):
    """60 秒内 3 败=整腿熄火：不再起进程、恒回不可用（重启 backend 才接回）。
    每次失败含就地重试=2 次 spawn，3 次 call 共 6 次起程。"""
    n = [0]
    def factory(*a, **k):
        n[0] += 1
        return FakeProc(FakeStdin(), FakeStdout([], eof=True))   # 一开口就断
    monkeypatch.setattr(mc.subprocess, "Popen", factory)
    for _ in range(3):
        assert "不可验证" in fresh.call("solve_equation", {"eq": "x=1"})
    assert fresh._melted is True
    assert fresh.call("solve_equation", {"eq": "x=1"}) == fresh._UNAVAILABLE
    assert n[0] == 6                             # 熄火后一次都不再白起


def test_kill_race_retries_in_place(fresh, monkeypatch):
    """kill -9 落地异步：poll() 未见尸（返回 None）但管道已 EOF=写向垂死孩子。
    call 须就地换血重试一次当句自愈，且不记腿故障。"""
    zombie = FakeProc(FakeStdin(), FakeStdout([], eof=True))
    zombie.poll = lambda: None                   # 尸体未收——poll 撒谎说活着
    script = [_init_ok(2), _resp(3, {"result": {"content": [
        {"type": "text", "text": "解为：x = -1"}]}})]
    healthy = FakeProc(FakeStdin(), FakeStdout(script))
    # zombie 是「上一句留下的旧孩子」直接挂 _proc，不经 Popen——
    # 所以 Popen 只需供应重试那一任健康进程
    monkeypatch.setattr(mc.subprocess, "Popen", lambda *a, **k: healthy)
    fresh._proc = zombie                         # 假装上一句刚用完这只孩子
    assert "x = -1" in fresh.call("solve_equation", {"eq": "x+1=0"})
    assert zombie.killed is True                 # 垂死孩子被收尸
    assert fresh._proc is healthy
    assert len(fresh._fails) == 0                # 自愈不算故障，不吃熄火账


def test_protocol_error_is_not_leg_failure(fresh, monkeypatch):
    """孩子答了但答歪（未知工具）=回报错文本，不记腿故障——锅在参数不在腿。"""
    proc = FakeProc(FakeStdin(), FakeStdout([
        _init_ok(),
        _resp(2, {"error": {"code": -32601, "message": "Unknown tool: no_such"}}),
    ]))
    monkeypatch.setattr(mc.subprocess, "Popen", lambda *a, **k: proc)
    out = fresh.call("no_such", {})
    assert "数学工具报错" in out and "no_such" in out
    assert len(fresh._fails) == 0 and fresh._melted is False
