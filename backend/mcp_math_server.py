# ============================================================
# S9·W7 伴考数学 MCP 服务器（backend/mcp_math_server.py）—— 2026-10-11
# sympy 四只手（解方程/化简/统计/验根）装进一个独立子进程：
# mcp 2.x SDK 的 MCPServer 走 stdio 传输——注意 mcp 2.x 已把 v1 的
# FastMCP 改名 MCPServer（from mcp.server.mcpserver import MCPServer）。
# 主进程永不 import sympy：死循环、内存爆炸都是「这孩子自己的事」，
# mcp_client 侧超时即杀换血，答题腿毫发无伤（隔离是本体，协议是形式）。
# 返回一律人话中文、不是异常栈——模型读了直接转述；手抖不死人。
# ============================================================
import re
import statistics as st

import sympy as sp
from mcp.server.mcpserver import MCPServer
from sympy.parsing.sympy_parser import parse_expr

server = MCPServer("bankao-math")

# 输入白名单：只放数学符号、字母、数字、空格、逗号、等号。
# 引号/点号进不来 → `__import__('os')`、`a.__class__` 这类 sympify
# 注入面整片堵死（本进程只配算术，模型传来的串按不可信处理）。
_SAFE = re.compile(r"^[\w+\-*/().^ ,=]+$")


def _parse(s: str):
    """字符串→sympy 表达式；`^` 按人的习惯当幂（sympy 原生认 **）。"""
    if not _SAFE.match(str(s or "")):
        raise ValueError("表达式含非数学符号，拒绝解析")
    return parse_expr(str(s).replace("^", "**"))


def _fail(e: Exception) -> str:
    return f"算不了：{type(e).__name__} {str(e)[:120]}"


@server.tool()
def solve_equation(eq: str, variable: str = "x") -> str:
    """解方程：如 2*x+3=9；没有等号按「=0」处理。只回实解前 5 个。"""
    try:
        parts = str(eq).split("=", 1)
        lhs = _parse(parts[0])
        rhs = _parse(parts[1]) if len(parts) > 1 else sp.Integer(0)
        var = sp.Symbol(variable)
        sols = [s for s in sp.solve(sp.Eq(lhs, rhs), var) if s.is_real is not False]
        if not sols:
            return "无实数解（或超出代数求解能力），请人工复核。"
        tail = "（仅列前 5 个）" if len(sols) > 5 else ""
        return "解为：" + ", ".join(f"{variable} = {s}" for s in sols[:5]) + tail
    except Exception as e:
        return _fail(e)


@server.tool()
def simplify_expression(expr: str) -> str:
    """代数式化简：如 (x+1)^2-x^2 化到最简形。"""
    try:
        return f"化简结果：{sp.simplify(_parse(expr))}"
    except Exception as e:
        return _fail(e)


@server.tool()
def compute_statistics(numbers: list[float]) -> str:
    """一组数的精确统计量：个数/均值/中位数/众数/极差/样本标准差。
    对账分数、核对平均数用——比心算可信，比口算便宜。"""
    try:
        if not numbers:
            return "数字列表为空，无从统计。"
        nums = [float(v) for v in numbers]
        mean, med = st.mean(nums), st.median(nums)
        rng = max(nums) - min(nums)
        try:
            mode = f"{st.mode(nums):g}"
        except st.StatisticsError:
            mode = "无（每个只出现一次）"
        sd = f"{st.stdev(nums):.4g}" if len(nums) > 1 else "0（单个数）"
        return (f"个数 {len(nums)}，均值 {mean:.4g}，中位数 {med:g}，"
                f"众数 {mode}，极差 {rng:g}，样本标准差 {sd}")
    except Exception as e:
        return _fail(e)


@server.tool()
def verify_answer(eq: str, value: float, variable: str = "x") -> str:
    """验根：把 value 代回方程 eq 的左边减右边，残差≈0 即满足。
    出题验算的主用腿——模型算的答案先过这只手再出口。"""
    try:
        parts = str(eq).split("=", 1)
        lhs = _parse(parts[0])
        rhs = _parse(parts[1]) if len(parts) > 1 else sp.Integer(0)
        resid = float((lhs - rhs).subs(sp.Symbol(variable), float(value)))
        if abs(resid) < 1e-9:
            return f"满足：{variable}={value} 代入残差为 0。"
        return f"不满足：{variable}={value} 代入残差为 {resid:.6g}。"
    except Exception as e:
        return _fail(e)


if __name__ == "__main__":
    server.run()   # 默认 stdio 传输：stdin 收指令、stdout 回话、stderr 留声
