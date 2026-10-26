# ============================================================
# 安全规则库（backend/safety.py）—— S9 · W4 刀（2026-10-11）
# 教学图第一闸：关键词/正则的确定性拦截，**零 token 零延迟**
# （外部方案 §3.4 钉死第一版纯规则，模型审核是后续增强不进本版）。
# 四类判据按「生命 > 违法 > 破防 > 代写」的优先级排——
# 一条消息同时踩几类时，报最重的那类（自伤话术绝不能被注入拦截盖掉）。
# 返回 None = 放行；返回 {"kind", "reply"} = 拦下且给固定话术（不走模型）。
# ============================================================

# 注入特征串：想劫持系统角色的英文/中文话头（英文比对前先 lower）
_INJECTION = (
    "ignore previous", "ignore all previous", "disregard previous",
    "忽略以上", "忽略之前", "无视上面", "新的指令", "从现在开始你是",
    "你不再是", "系统提示词", "system prompt", "开发者模式", "越狱",
    "jailbreak", "dan模式",
)

# 自伤信号：优先级最高。话术只求两件事——接住情绪、给出真出口。
# 12355 是共青团青少年服务热线（备考年龄段适用），写死在话术里。
_SELF_HARM = ("自杀", "不想活", "活不下去", "结束生命", "割腕", "轻生", "服毒自")

# 违法请求：与备考无关的制造类/逃避制裁类要请
_ILLEGAL = ("制毒", "造炸弹", "炸药配方", "合成毒品", "枪支制造",
            "逃避法律制裁", "洗钱")

# 申论代写（PRD 底线：引导可以，代笔不行）：
# 「写」类动作 + 申论文体 两个词族同时命中才算要代笔
_WRITE_VERBS = ("帮我写", "写一篇", "写篇", "写一份", "直接给我写", "全文", "范文")
_ESSAY_FORMS = ("申论", "大作文", "小作文", "材料作文", "策论文", "公文")

_SELF_HARM_REPLY = ("先停一停——我听见你现在很不好受。考试很重要，但你比考试重要。"
                    "这样的时刻请找真人聊聊：全国青少年心理热线 12355（24 小时），"
                    "或者告诉你身边任何一个人。今天的学习计划我可以帮你先放着，"
                    "什么时候想继续我都在。")
_ILLEGAL_REPLY = ("这个忙我不能帮——它不是考试范围，也超出我能做的。"
                  "备考上的问题随时回来找我。")
_INJECTION_REPLY = ("我是伴考，只聊备考这一摊。咱们回到你的学习上吧——"
                    "刚才那道题讲到哪了？")
_GHOSTWRITE_REPLY = ("申论我不代笔——写出来的分不是你的，练出来的才是。"
                     "换个做法：你把提纲或写了一半的初稿发来，我逐段给你批，"
                     "或者我先出一道真题带你拆材料、搭骨架？")


def screen(text: str) -> dict | None:
    """安全闸纯函数：放行 None；拦下带 kind+固定话术。零模型调用。"""
    t = text or ""
    low = t.lower()
    if any(w in t for w in _SELF_HARM):
        return {"kind": "self_harm", "reply": _SELF_HARM_REPLY}
    if any(w in t for w in _ILLEGAL):
        return {"kind": "illegal", "reply": _ILLEGAL_REPLY}
    if any(w in low for w in _INJECTION):   # 英文词小写化后比对，中文原样
        return {"kind": "injection", "reply": _INJECTION_REPLY}
    if any(w in t for w in _WRITE_VERBS) and any(w in t for w in _ESSAY_FORMS):
        return {"kind": "ghostwrite", "reply": _GHOSTWRITE_REPLY}
    return None
