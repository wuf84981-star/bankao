# ============================================================
# 定时任务（S6 · PRD 16.3：APScheduler 进程内 · D21 甲案）
# 系统第一次「不等谁开口就自己干活」——这形状的住址就在这份文件。
# 编制表两单：
# ①每日 03:00 清理到期时效事件（首刀）——集合式删除天然幂等，双实例无锁可省。
# ②每 5 分钟提醒派发（二刀 · F-33/D24 甲）——谁的 remind_time 到点且未超
#   30 分钟补偿窗（PRD 15 章第 10 条「提醒类设 30 分钟补偿窗口」）且今天没发过，
#   给他拼一条当日提醒进会话账。D21 预告过的「不幂等 job 出生时再论」在此收口：
#   防重发先查送达账（messages.remind_on 等值判）再动笔——双实例/补窗重复档位
#   撞上来也只是查有即跳过，零新增状态位（账说话、嘴跟着）。
#   三刀扩编（D26 甲）：绑定户发后补推 OneBot，推败记 push_state='fail'，
#   同窗内后续档位只重试推送不再发消息——账永远先落，嘴慢半拍不违「必达」。
# ③每日 04:00 备份全家福（S8 五刀 · D50 甲 2026-09-11 拍）——pg_dump 整库 +
#   uploads 目录各拍一张进 /data/backups，轮转只留 7 份；异地人工拷（熟人期）。
#   可测形状与前两件同款：直喂日期+注入假 runner+tmp 目录，单测零真执行。
# ④每 10 分钟滚动摘要（S9·W6 · D41 兑现刀 2026-10-11）：把「装不进的旧话」
#   压进 conversations.context_summary（Text 列手写 JSON 四要素），教练靠
#   摘要+近窗保持连续性。不走同步满 N 轮触发——给流尾压 2-4s LLM 违反
#   8s 延迟预算；真源判据是 PG 行数不是 Redis 轮次（Redis 灭也照跑）；
#   幂等靠 until_id 乐观条件写回；全局票锁只是双实例礼貌，不是正确性闸。
# ============================================================
import json
import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from backend.db import SessionLocal
from backend.models import Conversation
from backend.short_memory import try_lock
from backend.tools import model_for

scheduler = AsyncIOScheduler()   # 住进 uvicorn 的事件循环：backend 箱活它就活


def clean_expired_events(today: date | None = None) -> int:
    """到期清理本体（函数独立成件：测试直喂日期验，不用装到 03:00）。
    「到期」= end_at 早于今天——最后一天过完就算过期，与 expire_at 列的语义
    完全等价（那列在表模型处裁掉留档）。"""
    d = today or date.today()
    with SessionLocal() as s:
        n = s.execute(text("DELETE FROM life_events WHERE end_at < :d"),
                      {"d": d}).rowcount
        s.commit()
    return n


def _job_clean_expired() -> None:
    n = clean_expired_events()
    if n:
        print(f"[jobs] 已清理到期时效事件 {n} 条")   # 日志留声（forget 轻版同款）


# ── 二刀：每日提醒派发（F-33 · D24 三甲：落会话账 / 30 分钟补偿窗 / 模板拼文案）──

DEFAULT_REMIND = "20:00"      # PRD F-33①：没设过时点的户按默认走
REMIND_WINDOW_MIN = 30        # PRD 15 章第 10 条：提醒类补偿窗口


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def build_reminder_text(s, uid: int, today: date) -> str:
    """当日提醒文案：有未打卡任务→具体清单（AC①「非空喊打卡」）；
    无任务（休整日/事件减空）→轻量关心不发任务单（AC②原文）。纯代码读账。"""
    items = s.execute(text(
        "SELECT task_desc, est_minutes FROM plan_items "
        "WHERE user_id = :u AND date = :d AND status = 'pending' ORDER BY id"),
        {"u": uid, "d": today}).all()
    if not items:
        return ("今天没排任务——是休息日就养足精神。想练两组题或查查薄弱点，"
                "随时喊我，我都在。")
    head = "、".join(f"{it.task_desc}({it.est_minutes}分)" for it in items[:5])
    more = f"……一共 {len(items)} 项" if len(items) > 5 else f"共 {len(items)} 项"
    days = s.scalar(text(
        "SELECT (exam_date - :d)::int FROM exam_profiles "
        "WHERE user_id = :u AND is_primary AND status = 'in-progress'"), {"u": uid, "d": today})
    cd = f"距考试 {days} 天。" if days is not None and days > 0 else ""
    return (f"⏰ 每日提醒：今天还要清 {head}，{more}。{cd}"
            "完成一项就回我一句，我帮你打卡记账。")


def run_reminder_tick(now: datetime | None = None,
                      only: set[int] | None = None) -> int:
    """派头人扫一遍（函数可直喂时间验，不用等整点——clean 同款可测形状）。
    发三条件：到点、未超补偿窗、今天没盖过提醒戳。返回本次发出去几户。
    only 白名单（ignite 同款闸）：单测必传测试户 id——本函数扫全表，
    不掐白名单会拿开发真账号开刀（真数据污染血案预防）。生产 job 不传=全户。"""
    t = now or datetime.now()
    today = t.date()
    cur = t.hour * 60 + t.minute
    sent = 0
    with SessionLocal() as s:
        rows = s.execute(text(
            "SELECT u.id, a.remind_time FROM users u "
            "LEFT JOIN agent_settings a ON a.user_id = u.id "
            "WHERE u.status = 'normal'")).all()
        for uid, rt in rows:
            if only is not None and uid not in only:
                continue
            if not 0 <= cur - _mins(rt or DEFAULT_REMIND) <= REMIND_WINDOW_MIN:
                continue
            stamped = s.execute(text(
                "SELECT m.id, m.content, m.push_state FROM messages m JOIN conversations c "
                "ON m.conversation_id = c.id "
                "WHERE c.user_id = :u AND m.remind_on = :d LIMIT 1"),
                {"u": uid, "d": today}).first()
            if stamped:
                # D26 甲补推腿：账已落（本户今天有戳）但 QQ 嘴当时没张开
                # （push_state='fail'）→ 补偿窗内只重试推送、绝不再发消息。
                # 走到这必在窗内（上面窗闸拦过）——超窗翻篇，明天一条新的。
                # 函数内延迟 import：qq→orchestrator→jobs 会绕回本文件，顶层握手会死锁。
                if stamped.push_state == "fail":
                    from backend.qq import binding_for_user, push_via_onebot
                    b = binding_for_user(s, uid)
                    if b and push_via_onebot(b.qq_number, stamped.content):
                        s.execute(text("UPDATE messages SET push_state = 'ok' "
                                        "WHERE id = :i"), {"i": stamped.id})
                continue   # 送达账上今天已有戳——防重发查账不查状态位
            conv = s.scalar(text(
                "SELECT id FROM conversations WHERE user_id = :u AND channel = 'web' "
                "ORDER BY updated_at DESC LIMIT 1"), {"u": uid})
            if conv is None:   # 从没聊过的户：给他开个会话，提醒才有地方落
                conv = s.scalar(text(
                    "INSERT INTO conversations (user_id, channel, title, updated_at) "
                    "VALUES (:u, 'web', '每日提醒', now()) RETURNING id"), {"u": uid})
            # D26 甲「账是本、嘴是 QQ」：永远先备好落账的文案；绑定户顺手推
            # OneBot，推没推上写进 push_state（NULL=没绑不推/fail=窗内待重试/ok=嘴也到过）。
            from backend.qq import binding_for_user, push_via_onebot
            txt = build_reminder_text(s, uid, today)
            push = None
            b = binding_for_user(s, uid)
            if b:
                push = "ok" if push_via_onebot(b.qq_number, txt) else "fail"
            s.execute(text(
                "INSERT INTO messages (conversation_id, role, content, token_count, "
                "remind_on, push_state, created_at) "
                "VALUES (:c, 'assistant', :txt, 0, :d, :p, now())"),
                {"c": conv, "txt": txt, "d": today, "p": push})
            s.execute(text("UPDATE conversations SET updated_at = now() WHERE id = :c"),
                      {"c": conv})   # 浮到会话列表头部=送达可见
            sent += 1
        s.commit()
    return sent


def _job_reminder_tick() -> None:
    n = run_reminder_tick()
    if n:
        print(f"[jobs] 每日提醒已发放 {n} 户")


# ── S8 五刀：每日备份（D50 甲 · 2026-09-11 拍：调度器 04:00 全家福+轮转7份+异地人工）──
# 为什么 04:00：03:00 清完到期事件、凌晨没人聊天，是自家日程表上的空档。
# 为什么留 7：够回看一整周；再多会自己吃满磁盘——备份反噬正主是经典事故。
# 为什么 -Fp 纯文本不 -Fc：演练首跑血案——backend 箱 pg_dump 17 产的 custom 归档
# （版本头 1.16），db 箱的 pg_restore 16 直接拒读「unsupported version」。备份能拍
# 不能复原叫没备份。纯 SQL 文本跨版本稳，--clean --if-exists 前置在 dump 文件头
# （先拆后装，同口令可反复演）。
# 恢复口令（演练实证版 · 两道血案都踩过）：pg_dump 17 固定头里有 PG17 专属参数
# SET transaction_timeout，PG16 服务器不识——ON_ERROR_STOP 会当场拦停。那行语义
# 无损（16 本就无事务超时），sed 滤掉再进 psql：
#   sed '/transaction_timeout/d' 宿主data/backups/bankao_<日期>.sql \
#     | docker compose exec -T db psql -U bankao -d bankao -v ON_ERROR_STOP=1
# 保险闸 ON_ERROR_STOP 必带：没它错误刷屏不知哪条是真fatal；有它拦在灾变现场。

BACKUP_DIR = "/data/backups"   # backend 箱挂载点（compose ./data/backups 同块地）
KEEP = 7                        # 轮转份数


def _db_conn(url: str) -> dict:
    """DATABASE_URL → pg_dump 需要的五件套。密码只进子进程 env（PGPASSWORD），
    绝不进 argv——命令行参数会被 docker top / ps 看光，密码上 argv 等于贴告示。"""
    p = urlparse(url)
    return {"host": p.hostname, "port": str(p.port or 5432),
            "user": unquote(p.username or ""), "password": unquote(p.password or ""),
            "db": (p.path or "").lstrip("/")}


def _rotate(dir: str) -> list[Path]:
    """每个系列按文件名留最新 KEEP 份（文件名带 ISO 日期，零填充——字典序即时间序）。"""
    gone: list[Path] = []
    for pat in ("bankao_*.sql", "uploads_*.tar.gz"):
        files = sorted(Path(dir).glob(pat))
        for old in files[:-KEEP]:
            old.unlink()
            gone.append(old)
    return gone


def run_daily_backup(now: datetime | None = None, *,
                     dir: str = BACKUP_DIR,
                     runner=subprocess.run,
                     url: str | None = None) -> list[Path]:
    """拍两张全家福（整库纯 SQL 文本 + uploads 打包），各腿独立成败——
    一张砸了不连坐另一张（try/except 各自兜）；成功后轮转留 7。
    返回成功产物清单（调度器直喂时间可测；runner/dir 注入假件后单测零真执行）。
    恢复语义提醒：--clean --if-exists 已随 dump 前置，配 db 箱本地 psql 免密重放，见上方口令。"""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    conf = _db_conn(url or os.environ["DATABASE_URL"])
    Path(dir).mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    dump = Path(dir) / f"bankao_{stamp}.sql"
    try:
        runner(["pg_dump", "-h", conf["host"], "-p", conf["port"],
                "-U", conf["user"], "-d", conf["db"],
                "-Fp", "--clean", "--if-exists", "-f", str(dump)],
               env={**os.environ, "PGPASSWORD": conf["password"]}, check=True)
        made.append(dump)
    except Exception as e:
        print(f"[jobs] 库全家福没拍成（不连坐 uploads 腿，明天再拍）：{str(e)[:120]}")
    up = Path(dir) / f"uploads_{stamp}.tar.gz"
    try:
        runner(["tar", "-czf", str(up), "-C", str(Path(dir).parent), "uploads"],
               check=True)
        made.append(up)
    except Exception as e:
        print(f"[jobs] uploads 全家福没拍成：{str(e)[:120]}")
    _rotate(dir)
    return made


def _job_backup() -> None:
    made = run_daily_backup()
    print(f"[jobs] 备份出品：{', '.join(p.name for p in made) or '两张都没拍成'}")


# ── 四单：滚动摘要（S9·W6 · D41 兑现刀）──

SUMMARY_KEEP = 20         # 最近 20 条永不进摘要——与会话窗（window_get）同口径
SUMMARY_MIN_MSGS = 24     # 起算闸：窗满 + 4 条新鲜余量，刚开的线不打搅
SUMMARY_PER_LINE = 200    # 每条截进提示词的字数——摘要是记大事，不是存原话
SUMMARY_MAX_LINES = 120   # 单次喂模型的条数上限（超长旧线首次压缩只滚旧尾，
                          # 更早的账凭旧摘要续传，传不到的部分依法割舍）
SUMMARY_BATCH = 8         # 一个 tick 最多压几条会话——运费摊开，不一次清仓

_SUMM_SYS = """把下面的对话压缩成一份简明的前情提要（简体中文、第三人称「学生/教练」、200 字以内）。
保留：学生的考试类型与薄弱环节、聊过哪些知识点与结论、立过的约定与未办完的事、判过的对错。
丢弃：寒暄、题目全文、已被后来内容覆盖的旧说法。
只输出摘要正文本身，不要标题、不要客套开头结尾。"""


def summarize_conv(s, conv_id: int, chat_fn=None) -> bool:
    """把一条会话线的旧部分滚进 context_summary（JSON 四要素 until_id/text/model/at，
    Text 列手写——SQL 侧零 JSON 查询，零迁移）。返回 True 仅当真写了一笔。
    幂等=乐观锁写回：UPDATE WHERE context_summary=<刚读的原文>，并发双写必输一把；
    until_id 记「滚到哪一行」，下轮只压增量旧行——同一条历史永不压两遍。
    模型运费不进 usage_logs：系统家务不占户主日账——三本账口径留给对话行。"""
    conv = s.get(Conversation, conv_id)
    if conv is None:
        return False
    n = s.scalar(text("SELECT count(*) FROM messages WHERE conversation_id=:c"),
                 {"c": conv_id})
    if n < SUMMARY_MIN_MSGS:
        return False
    # 边界=倒数第 21 行：id ≤ boundary 的都不许再进提示词窗口，该滚进摘要
    boundary = s.scalar(text(
        "SELECT id FROM messages WHERE conversation_id=:c "
        "ORDER BY id DESC OFFSET :k LIMIT 1"), {"c": conv_id, "k": SUMMARY_KEEP})
    old_raw = conv.context_summary
    until_id, old_text = 0, ""
    if old_raw:
        try:
            d = json.loads(old_raw)
            until_id = int(d.get("until_id") or 0)
            old_text = d.get("text") or ""
        except Exception:
            until_id, old_text = 0, ""     # 坏数据=从头重做，写回覆盖即修复
    if boundary is None or boundary <= until_id:
        return False                        # 没有新旧行=没得说，电厂一次不烧
    m = s.scalar(text(
        "SELECT count(*) FROM messages WHERE conversation_id=:c "
        "AND id > :u AND id <= :b"), {"c": conv_id, "u": until_id, "b": boundary})
    off = max(0, m - SUMMARY_MAX_LINES)     # 只取最新的上限条（超长的头等旧摘要续传）
    rows = s.execute(text(
        "SELECT role, content FROM messages WHERE conversation_id=:c "
        "AND id > :u AND id <= :b ORDER BY id LIMIT :lim OFFSET :off"),
        {"c": conv_id, "u": until_id, "b": boundary,
         "lim": SUMMARY_MAX_LINES, "off": off}).fetchall()
    body = "\n".join(f"{r[0]}: {str(r[1])[:SUMMARY_PER_LINE]}" for r in rows)
    prompt = (f"【前情摘要】\n{old_text}\n\n【续聊对话】\n{body}" if old_text
              else f"【对话】\n{body}")
    model = model_for(s, conv.user_id)       # 用本户选脑压——摘要腿与对话腿同脑
                                             # （D60 真源一处：账在 agent_settings，不抄原始列名）
    from backend.llm import chat_once          # 延迟 import：jobs 家常编制不带电厂
    fn = chat_fn or (lambda msgs, model=None: chat_once(msgs, tools=None, model=model))
    try:
        call, _, _ = fn([{"role": "system", "content": _SUMM_SYS},
                         {"role": "user", "content": prompt}], model=model)
    except Exception as e:
        print(f"[jobs] 摘要腿故障 conv={conv_id}："
              f"{type(e).__name__}: {str(e)[:160]}", flush=True)
        return False
    text_ = (call.get("content") or "").strip()
    if not text_:
        return False
    new_raw = json.dumps({"until_id": boundary, "text": text_[:600],
                          "model": model,
                          "at": datetime.now().isoformat(timespec="seconds")},
                         ensure_ascii=False)
    if old_raw is None:   # 乐观锁两种形（首写认 NULL / 增量认原串）
        hit = s.execute(text("UPDATE conversations SET context_summary=:v "
                             "WHERE id=:c AND context_summary IS NULL"),
                        {"v": new_raw, "c": conv_id})
    else:
        hit = s.execute(text("UPDATE conversations SET context_summary=:v "
                             "WHERE id=:c AND context_summary=:o"),
                        {"v": new_raw, "c": conv_id, "o": old_raw})
    s.commit()
    return hit.rowcount == 1


def _job_compress_tick() -> None:
    """每 10 分钟：挑几条「装不下」的会话线滚前情摘要。真源判据是 PG 行数
    不是 Redis 轮次；全局票锁 540s 防双实例同拍重活，幂等靠 until_id 乐观条件——
    锁可以丢，账不许双压（try_lock 在 Redis 灭时一律放行，压缩照跑）。"""
    if not try_lock("compress_tick", 540):
        return
    with SessionLocal() as s:
        ids = [r[0] for r in s.execute(text(
            "SELECT c.id FROM conversations c JOIN messages m "
            "ON m.conversation_id = c.id "
            "GROUP BY c.id HAVING count(*) > :n "
            "ORDER BY max(m.id) DESC LIMIT :lim"),
            {"n": SUMMARY_MIN_MSGS, "lim": SUMMARY_BATCH}).fetchall()]
        done = 0
        for cid in ids:
            try:
                if summarize_conv(s, cid):
                    done += 1
            except Exception as e:
                print(f"[jobs] 摘要压缩炸 conv={cid}："
                      f"{type(e).__name__}: {str(e)[:160]}", flush=True)
    if done:
        print(f"[jobs] 本轮滚动摘要压了 {done} 条会话线", flush=True)


def start_jobs() -> None:
    """startup 钩子调它：03:00 清账 + 每 5 分钟提醒派发（服务器本地时——
    与计划账/工具层同一天钟口径）。replace_existing + running 双闸：
    dev 重载/误重调都不叠 job 不炸第二次。"""
    scheduler.add_job(_job_clean_expired, "cron", hour=3, minute=0,
                      id="clean_life_events", replace_existing=True)
    scheduler.add_job(_job_reminder_tick, "cron", minute="*/5",
                      id="daily_reminder_tick", replace_existing=True)
    scheduler.add_job(_job_backup, "cron", hour=4, minute=0,
                      id="daily_backup", replace_existing=True)
    scheduler.add_job(_job_compress_tick, "cron", minute="*/10",
                      id="compress_tick", replace_existing=True)
    if not scheduler.running:
        scheduler.start()
