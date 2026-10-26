# ============================================================
# SMTP 邮件腿（S8 首刀 · D52 甲案：QQ 邮箱真寄件）
# SMTP_USER=发件邮箱，SMTP_PASS=QQ 邮箱设置里生成的「授权码」（不是登录密码）。
# 同步 smtplib 即可：路由是 def（FastAPI 丢线程池跑），不冻事件循环。
# 单测一律 monkeypatch 掉 send_mail——真网络一毛钱不烧（电厂/OCR 假腿同款纪律）。
# ============================================================
import os
import smtplib
from email.message import EmailMessage


def build_message(frm: str, to: str, subject: str, body: str) -> EmailMessage:
    """组一封信（信封+信纸分开验，2026-09-09 真机案换来的）：
    EmailMessage 的 .body 只是个内存字段，上网走的是 payload——
    只赋 .body 寄出去的信有主题没正文。必须用 set_content，
    它把正文真正写进信封，并自动挂 text/plain + UTF-8 编码声明。"""
    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def send_mail(to: str, subject: str, body: str) -> None:
    """寄一封信。配置缺失/网络故障如实抛，不吞——调用方负责转人话。"""
    user = os.environ.get("SMTP_USER", "")
    pwd = os.environ.get("SMTP_PASS", "")
    if not user or not pwd:
        raise RuntimeError("SMTP 邮件腿未配置：.env 里填 SMTP_USER 与 SMTP_PASS（授权码）")
    host = os.environ.get("SMTP_HOST", "smtp.qq.com")
    port = int(os.environ.get("SMTP_PORT", "465"))
    msg = build_message(user, to, subject, body)
    with smtplib.SMTP_SSL(host, port, timeout=15) as s:
        s.login(user, pwd)
        s.send_message(msg)
