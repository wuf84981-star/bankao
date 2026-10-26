# ============================================================
# 埋点账共核（S8 四刀 · D55 甲 · PRD 13.7/24.1）
# 独立模块的理由：main 吊着 qq（导入方向单行），QQ 腿也要记账——
# 共核放 main 里 qq 反手 import 就成环，放 orchestrator 是拿大脑垫桌脚。
# 一条家规凌驾全部代码：记账是「只看不拦」——进门/改密/发消息的主流程
# 绝不因一笔账崩掉；所以自开独立事务、失败只自曝不抛。
# 隐私口径（PRD 24 章）在函数层执法：props 只收标量（str/int/bool/float），
# dict/list 一律丢弃留声——消息正文、资料内容「想误传进来」在形状上就进不来。
# ============================================================
from backend.db import SessionLocal
from backend.models import AnalyticsEvent

_ALLOWED = (str, int, bool, float)


def _track(user_id: int | None, event: str, **props) -> None:
    """记一笔行为（谁+事件名+标量小属性+时间），独立事务不进调用方账本——
    主流程回滚不追缴已发生的动作，记账腿炸不拖累主流程。"""
    clean = {k: v for k, v in props.items() if v is None or isinstance(v, _ALLOWED)}
    dropped = sorted(set(props) - set(clean))
    try:
        with SessionLocal() as s:
            s.add(AnalyticsEvent(user_id=user_id, event=event, props=clean or None))
            s.commit()
        if dropped:
            print(f"[track] 非属性标量被丢弃（隐私口径执法）：{event} → {dropped}")
    except Exception as e:
        print(f"[track] 记账失败（只看不拦，主流程无恙）：{event} → {str(e)[:120]}")
