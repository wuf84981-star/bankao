/* ============================================================
 * 管理页（D49 甲户主钥匙在岗 · D54 2026-09-10 邀请码全拆后留守件）——
 * 两块：用量面板（D55 甲埋点账，只给数不给事）+ 全体注册用户清单。
 * 钥匙形状不变：入口在 App 侧栏按 /api/me 的 is_admin 显隐；
 * 后端每端点还有第二道闸（_require_admin 403）——前端藏门是礼貌，
 * 后端验票才是法律（S4 控制权同款双闸思想）。
 * ============================================================ */
import { useCallback, useEffect, useState } from "react";
import { api } from "../auth";

/* 用户清单行（/api/admin/users 的 items 形状；来源列已随邀请码退役；
 * balance=D64 积分余额，后端从流水加总，页面不自己算） */
type UserRow = {
  id: number;
  username: string;
  email: string | null;
  is_admin: boolean;
  balance: number;
  created_at: string | null;
};

/* 用量面板账目（/api/admin/stats——D55 甲 · PRD 十一章） */
type EventStat = { event: string; count: number; last_at: string | null };
type Stats = { events: EventStat[]; weekly_active: number; total_users: number };

/* S9·W3 知识缺口行（/api/admin/gaps）：kind=zero 讲义没有（top_score 空）、
 * weak 擦边命中（向量最高分低于登记线）——户主补弹药的本子 */
type GapRow = {
  id: number;
  user_id: number;
  username: string | null;
  question: string;
  top_score: number | null;
  channel: string;
  kind: string;
  created_at: string | null;
};

/* 事件名→人话：账本里存英文真名（给机器查），页面上说人话（给户主看）。
 * 没登记的新事件原样上屏——宁可生僻也不编造翻译。 */
const EVENT_CN: Record<string, string> = {
  sign_up_completed: "注册成功",
  login_completed: "登录成功",
  password_reset_completed: "找回密码",
  chat_message_sent: "开口发消息",
  checkin_done: "每日签到",
};

export default function Admin() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [gaps, setGaps] = useState<GapRow[]>([]);
  const [err, setErr] = useState("");

  /* 拉账：进页一次（账以库为准，不自算增量——八刀同款纪律） */
  const refresh = useCallback(async () => {
    try {
      const [userList, usage, gapList] = await Promise.all([
        api("/api/admin/users") as Promise<{ items: UserRow[] }>,
        api("/api/admin/stats") as Promise<Stats>,
        api("/api/admin/gaps") as Promise<{ items: GapRow[] }>,
      ]);
      setUsers(userList.items);
      setStats(usage);
      setGaps(gapList.items);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "管理页的账没拉回来");
    }
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);

  /* D64 户主手动发放/扣减：一次只掀一户的输入条；提交走 /api/admin/points/adjust
     （后端 kind=adjust 流水行——发放留痕可审计，没有直改数字的第二扇门） */
  const [adjId, setAdjId] = useState<number | null>(null);
  const [adjVal, setAdjVal] = useState("");
  async function submitAdjust(id: number): Promise<void> {
    const n = parseInt(adjVal, 10);
    if (!Number.isFinite(n) || n === 0) { setErr("调整数填非零整数：正数加、负数减"); return; }
    try {
      await api("/api/admin/points/adjust", { user_id: id, amount: n });
      setAdjId(null); setAdjVal(""); setErr("");
      await refresh();   // 拉账以库为准，不自算增量
    } catch (e) {
      setErr(e instanceof Error ? e.message : "调整没落账");
    }
  }

  return (
    <section className="flex-1 overflow-y-auto px-5 md:px-8 py-6 md:py-8 mb-20">
      <div className="max-w-5xl space-y-8 mx-auto">
        <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{ backgroundColor: "var(--color-mist)" }}>
          <div className="rounded-[calc(1.75rem-0.5rem)] p-5" style={{ backgroundColor: "var(--color-parchment)" }}>
            <p className="mb-3 text-[10px] font-bold tracking-[0.25em] text-copper">用量面板</p>
            {err && <p className="mb-3 text-[13px] text-red-700">{err}</p>}
            {!stats && !err && (
              <p className="text-[13px] text-ink/45">正在对账…</p>
            )}
            {stats && (
              <>
                <p className="mb-4 text-[14px] text-ink">
                  近 7 天开口的：
                  <span className="mx-1 text-[20px] font-bold text-copper">{stats.weekly_active}</span>
                  / {stats.total_users} 户
                </p>
                {stats.events.length === 0 && (
                  <p className="text-[13px] text-ink/45">埋点账还是空的——等第一路人进门。</p>
                )}
                <ul className="space-y-2">
                  {stats.events.map((ev) => (
                    <li key={ev.event}
                        className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-2xl px-4 py-3 ring-1 ring-ink/5"
                        style={{ backgroundColor: "var(--color-mist)" }}>
                      <span className="text-[14px] font-bold text-ink">{EVENT_CN[ev.event] ?? ev.event}</span>
                      <span className="text-[16px] font-bold text-copper">{ev.count}</span>
                      <span className="ml-auto text-[11px] text-ink/40">
                        最近 {ev.last_at ? new Date(ev.last_at).toLocaleString("zh-CN") : "—"}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
        <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{ backgroundColor: "var(--color-mist)" }}>
          <div className="rounded-[calc(1.75rem-0.5rem)] p-5" style={{ backgroundColor: "var(--color-parchment)" }}>
            <p className="mb-3 text-[10px] font-bold tracking-[0.25em] text-copper">注册用户（{users.length} 户）</p>
            <ul className="space-y-2">
              {users.map((u) => (
                <li key={u.id}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-2xl px-4 py-3 ring-1 ring-ink/5"
                    style={{ backgroundColor: "var(--color-mist)" }}>
                  <span className="text-[14px] font-bold text-ink">{u.username}
                    {u.is_admin && <span className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold text-white"
                                           style={{ backgroundColor: "var(--color-copper)" }}>户主</span>}
                  </span>
                  <span className="text-[12px] text-ink/55">{u.email ?? "邮箱列空（老户）"}</span>
                  <span className={`text-[13px] font-bold ${u.balance <= 50 ? "text-red-700" : "text-copper"}`}>
                    {u.balance.toLocaleString("en-US")} 分
                  </span>
                  <span className="ml-auto flex items-center gap-2">
                    {adjId === u.id ? (<>
                      <input value={adjVal} onChange={(e) => setAdjVal(e.target.value)}
                             onKeyDown={(e) => { if (e.key === "Enter") void submitAdjust(u.id); }}
                             placeholder="±分数" aria-label={`给 ${u.username} 调整积分`}
                             className="w-20 rounded-lg px-2 py-1 text-[12px] ring-1 ring-ink/10 outline-none"
                             style={{ backgroundColor: "var(--color-parchment)" }}/>
                      <button type="button" onClick={() => void submitAdjust(u.id)}
                              className="rounded-full px-2.5 py-1 text-[11px] font-bold text-parchment"
                              style={{ backgroundColor: "var(--color-copper)" }}>确认</button>
                      <button type="button" onClick={() => { setAdjId(null); setAdjVal(""); }}
                              className="rounded-full px-2.5 py-1 text-[11px] text-ink/50 ring-1 ring-ink/10">取消</button>
                    </>) : (
                      <button type="button" onClick={() => { setAdjId(u.id); setAdjVal(""); }}
                              className="rounded-full px-2.5 py-1 text-[11px] font-semibold text-copper ring-1 ring-copper/30 transition hover:bg-copper/10">调整</button>
                    )}
                    <span className="text-[11px] text-ink/40">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString("zh-CN") : ""}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{ backgroundColor: "var(--color-mist)" }}>
          <div className="rounded-[calc(1.75rem-0.5rem)] p-5" style={{ backgroundColor: "var(--color-parchment)" }}>
            <p className="mb-3 text-[10px] font-bold tracking-[0.25em] text-copper">知识缺口（最近 {gaps.length} 笔）</p>
            <ul className="space-y-2">
              {gaps.length === 0 && (
                <li className="text-[13px] text-ink/45">账还是空的——要么讲义都答得上，要么还没人来提问。</li>
              )}
              {gaps.map((g) => (
                <li key={g.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-2xl px-4 py-3 ring-1 ring-ink/5"
                    style={{ backgroundColor: "var(--color-mist)" }}>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold ${
                    g.kind === "zero" ? "bg-copper text-white" : "text-copper ring-1 ring-copper/40"}`}>
                    {g.kind === "zero" ? "讲义没有" : "擦边命中"}
                  </span>
                  <span className="min-w-0 flex-1 text-[13px] text-ink break-words">{g.question}</span>
                  <span className="text-[11px] text-ink/50">{g.username ?? "已注销户"}</span>
                  <span className="text-[11px] text-ink/40">{g.channel === "qq" ? "QQ" : "网页"}</span>
                  {g.top_score !== null && (
                    <span className="text-[11px] text-ink/40">向量 {g.top_score.toFixed(2)}</span>
                  )}
                  <span className="ml-auto text-[11px] text-ink/40">
                    {g.created_at ? new Date(g.created_at).toLocaleString("zh-CN") : ""}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
