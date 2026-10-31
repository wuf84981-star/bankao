/* ============================================================
 * 伴考 · 应用壳 v2
 * 桌面：浮动墨青岛侧栏 + 浮动胶囊页头
 * 移动：底部安全区栏 + min-h-[100dvh] 防 iOS 跳
 * 签名件：麦黄便利贴倒计时（-rotate 物理感）
 * 导航：rounded-full 铜绿药丸
 * ============================================================ */

import { useEffect, useState } from "react";
import { api, clearAuth, getToken, getUsername } from "./auth";
import Admin from "./pages/Admin";
import Chat from "./pages/Chat";
import Intro from "./pages/Intro";
import Login from "./pages/Login";
import Materials from "./pages/Materials";
import Memory from "./pages/Memory";
import Plan from "./pages/Plan";
import Settings from "./pages/Settings";

/* 倒计时换真日期（D83，2026-10-18）：写死的 EXAM_NAME/EXAM_DATE 已拆——
   原先侧栏「还剩42天」与计划页「距国考87天」打架的案底就在这两行道具上。
   现在统一读 /api/plan/summary 的主考档案真账，无档案则便利贴与页头计数整体收起。 */
type ExamInfo = { name: string; date: string };

/**
 * 计算距开考的剩余天数（以自然日为单位，不足 1 天按 0 计）。
 * @param examDate 主考档案真值「YYYY-MM-DD」
 * @returns 非负整数天数
 */
function daysLeft(examDate: string): number {
  const target = new Date(`${examDate}T00:00:00`);
  return Math.max(0, Math.ceil((target.getTime() - Date.now()) / 86_400_000));
}

/* 五页定义（PRD 21.1 信息架构 · Chat 默认落地页） */
const PAGES = [
  { key: "chat",     label: "对话", desc: "和教练聊聊今天要干什么" },
  { key: "plan",     label: "计划", desc: "日历总览与今日任务" },
  { key: "material", label: "资料", desc: "上传讲义，让它读给你听" },
  { key: "memory",   label: "记忆", desc: "它记下的关于你的一切" },
  { key: "settings", label: "设置", desc: "人设、提醒与账号" },
] as const;

/* 户主专属入口（S8 第二刀 · D49 甲）：侧栏按 /api/me 的 is_admin 显隐——
   前端藏门是礼貌，后端 _require_admin 403 才是法律 */
const ADMIN_PAGE = { key: "admin", label: "管理", desc: "用户清单：谁进了门、何时进的" } as const;

type PageKey = (typeof PAGES)[number]["key"] | typeof ADMIN_PAGE["key"];

/**
 * 主导航 SVG 细线图标集合（1.25px stroke，禁 Lucide/FontAwesome 粗线）。
 * @param name 图标名（chat/plan/material/memory/settings）
 * @returns SVG 元素
 */
function NavIcon({ name }: { name: PageKey }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.25,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  switch (name) {
    case "chat":
      return (
        <svg {...common}>
          <path d="M21 15a2 2 0 0 1-2 2H8l-5 4V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          <path d="M8 10h8M8 13h5" />
        </svg>
      );
    case "plan":
      return (
        <svg {...common}>
          <rect x="3" y="5" width="18" height="16" rx="2.5" />
          <path d="M8 3v4M16 3v4M3 10h18" />
          <path d="M8 14h.01M12 14h.01M16 14h.01M8 17h.01M12 17h.01" />
        </svg>
      );
    case "material":
      return (
        <svg {...common}>
          <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z" />
          <path d="M14 3v6h6" />
          <path d="M9 14h6M9 17h4" />
        </svg>
      );
    case "memory":
      return (
        <svg {...common}>
          <path d="M12 3a6 6 0 0 1 6 6c0 2-1 3.5-2 4.5L15 15a2 2 0 0 0 0 2.8V21H9v-3.2a2 2 0 0 0 0-2.8L8 13.5C7 12.5 6 11 6 9a6 6 0 0 1 6-6z" />
          <circle cx="10" cy="10" r=".75" />
          <circle cx="14" cy="10" r=".75" />
        </svg>
      );
    case "settings":
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
        </svg>
      );
    case "admin":
      /* 门票形：一码一人的账，用票根当图标 */
      return (
        <svg {...common}>
          <path d="M3 9a2 2 0 0 0 0 6v3a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-3a2 2 0 0 0 0-6V6a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1z" />
          <path d="M13 5v2M13 11v2M13 17v2" strokeDasharray="2 2" />
        </svg>
      );
  }
}

/* （D65 续刀）侧栏 QQ 绑定小卡与加好友指路段整体搬往设置页 QqBindPanel——
 * 侧栏太窄塞不下好友码；发码这只手仍只长在网页，只是网页里换了房间。 */

export default function App() {
  /* 登录态由口袋里的票决定：有票即进门（刷新不丢）——惰性初始化只读一次 */
  const [authed, setAuthed] = useState(() => !!getToken());
  /* 介绍页落地闸（2026-10-31 接入刀 · 用户拍板 B）：没票的新面孔先见介绍页读懂再进门，
     持票老客直进主界面不挡广告；退出登录属"还要再进"落登录页，不重放介绍页 */
  const [landing, setLanding] = useState<"intro" | "login">("intro");
  const [page, setPage] = useState<PageKey>("chat");
  const [isAdmin, setIsAdmin] = useState(false);   // 户主旗号位（D49 甲），驱动侧栏「管理」显隐
  useEffect(() => {
    if (!authed) { setIsAdmin(false); return; }
    api("/api/me")
      .then((d) => setIsAdmin(!!(d as { is_admin?: boolean }).is_admin))
      .catch(() => setIsAdmin(false));             // 拉票失败按平民对待——后端的 403 才是法律
  }, [authed]);
  const nav = isAdmin ? [...PAGES, ADMIN_PAGE] : PAGES;
  const meta = nav.find((p) => p.key === page) ?? PAGES[0];

  /* 主考档案真账（D83）：与计划页共用 /api/plan/summary 一个真源 */
  const [exam, setExam] = useState<ExamInfo | null>(null);
  useEffect(() => {
    if (!authed) { setExam(null); return; }
    api("/api/plan/summary")
      .then((d) => setExam((d as { exam: ExamInfo | null }).exam))
      .catch(() => setExam(null));   // 拉不到当无档案——便利贴不摆假天数
  }, [authed]);
  const left = exam ? daysLeft(exam.date) : 0;

  if (!authed) {
    return landing === "intro" ? (
      <Intro onEnter={() => setLanding("login")} onLogin={() => setLanding("login")} />
    ) : (
      <Login onEnter={() => setAuthed(true)} onBack={() => setLanding("intro")} />
    );
  }

  return (
    /* h-[100dvh] 钳死视口高（min-h 会被长内容撑破、滚动泄漏到整页——
       侧栏跟着滚走的病根）；滚动责任全部内收：Chat 页消息区自滚，
       其余页由 main 的 overflow-y-auto 接管 */
    <div className="relative flex h-[100dvh] w-full overflow-hidden">
      {/* z-2 保证内容在噪点叠层（z-1）之上 */}
      <div className="relative z-[2] flex h-full w-full">
        {/* ========== 桌面侧栏：浮动墨青岛（Double-Bezel，不贴边） ========== */}
        <aside
          className="hidden md:flex md:w-72 md:shrink-0 md:ml-6 md:my-6 md:self-start"
          style={{ height: "calc(100dvh - 3rem)" }}
          aria-label="主导航"
        >
          {/* 外框 shell */}
          <div className="w-full rounded-[1.75rem] p-2 ring-1 ring-ink/5"
               style={{ backgroundColor: "rgba(28,35,41,0.04)" }}>
            {/* 内核 core：墨青深色区 */}
            <div
              className="flex h-full w-full flex-col px-5 py-7"
              style={{
                backgroundColor: "var(--color-ink)",
                borderRadius: "calc(1.75rem - 0.375rem)",
                boxShadow: "inset 0 1px 1px rgba(255,255,255,0.08)",
              }}
            >
              {/* 品牌 */}
              <div className="px-1">
                <div className="font-display text-4xl leading-none tracking-[0.25em] text-parchment">
                  伴考
                </div>
                <p className="mt-2 text-[12px] leading-relaxed text-parchment/80">
                  长期陪伴式备考教练
                </p>
              </div>

              {/* ====== 签名件：麦黄便利贴倒计时（主考档案真值，无档案不摆） ====== */}
              {exam && (
              <div className="mx-auto mt-8 w-44">
                {/* 外框 shell：微倾斜 */}
                <div
                  className="rounded-[1.25rem] p-1.5"
                  style={{
                    backgroundColor: "rgba(239,230,210,0.7)",
                    transform: "rotate(-1.5deg)",
                    boxShadow: "var(--shadow-wheat)",
                  }}
                >
                  {/* 内核 core：麦黄纸 */}
                  <div
                    className="px-3 py-4 text-center"
                    style={{
                      backgroundColor: "var(--color-wheat)",
                      borderRadius: "calc(1.25rem - 0.375rem)",
                      boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
                      color: "var(--color-ink)",
                    }}
                  >
                    <div className="text-[10px] font-bold tracking-[0.18em] text-ink/70">
                      {exam.name}
                    </div>
                    <div
                      className="mt-1 font-mono text-6xl font-black leading-none tabular-nums"
                      style={{ color: "var(--color-copper-dk)" }}
                    >
                      {left}
                    </div>
                    <div className="mt-1 text-[10px] font-bold tracking-[0.15em] text-ink/70">
                      天 · 距开考
                    </div>
                  </div>
                </div>
              </div>
              )}

              {/* 导航按钮：rounded-full 药丸 */}
              <nav className="mt-10 flex flex-1 min-h-0 flex-col gap-1.5 overflow-y-auto pr-1" aria-label="主导航项">
                {nav.map((p) => {
                  const active = p.key === page;
                  return (
                    <button
                      key={p.key}
                      onClick={() => setPage(p.key)}
                      aria-current={active ? "page" : undefined}
                      className={`group flex items-center gap-3 rounded-full px-4 py-2.5 text-[14px] font-semibold transition-all duration-300 hover:bg-white/10`}
                      style={{
                        color: active ? "var(--color-parchment)" : "#FFFFFF",
                        backgroundColor: active ? "var(--color-copper)" : "transparent",
                        transitionTimingFunction: "var(--ease-glide)",
                        boxShadow: active ? "var(--shadow-copper)" : undefined,
                        fontWeight: active ? 700 : 600,
                      }}
                    >
                      <span className="grid size-5 shrink-0 place-items-center">
                        <NavIcon name={p.key} />
                      </span>
                      <span>{p.label}</span>
                    </button>
                  );
                })}
              </nav>

              {/* （D65 续刀）QQ 绑定小卡已整体搬往设置页——侧栏窄，塞不下好友码 */}

              {/* 页脚：谁在屋里 + 摘票走人 */}
              <div className="mt-auto pt-8">
                <p className="truncate text-[11px] font-semibold tracking-wide"
                   style={{ color: "rgba(255,255,255,0.72)" }} title={getUsername() ?? ""}>
                  已登录 · {getUsername()}
                </p>
                <button type="button"
                        onClick={() => { clearAuth(); setLanding("login"); setAuthed(false); }}
                        className="mt-1 text-[11px] font-semibold underline-offset-2 transition-opacity duration-300 hover:underline"
                        style={{ color: "rgba(255,253,247,0.5)" }}>
                  退出登录
                </button>
              </div>
            </div>
          </div>
        </aside>

        {/* ========== 主内容区 ========== */}
        <main className="flex min-w-0 min-h-0 flex-1 flex-col overflow-y-auto pb-24 md:pb-0">
          {/* 浮动胶囊页头（不贴边） */}
          <header
            className="mx-5 mt-5 shrink-0"
            aria-label="页面标题栏"
          >
            {/* 外框 shell */}
            <div
              className="rounded-[1.5rem] p-1.5 ring-1 ring-ink/5"
              style={{ backgroundColor: "var(--color-mist)" }}
            >
              {/* 内核 core */}
              <div
                className="flex items-center justify-between px-6 py-4"
                style={{
                  backgroundColor: "var(--color-parchment)",
                  borderRadius: "calc(1.5rem - 0.375rem)",
                  boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)",
                }}
              >
                <div className="min-w-0">
                  <h1 className="truncate font-heading text-xl font-semibold text-ink">
                    {meta.label}
                  </h1>
                  <p className="mt-0.5 truncate text-[13px] text-ink/60">
                    {meta.desc}
                    {exam && (
                      <>
                        <span className="mx-2 text-sand">·</span>
                        {exam.name}还剩{" "}
                        <span className="font-mono font-bold tabular-nums text-copper">
                          {left}
                        </span>{" "}
                        天
                      </>
                    )}
                  </p>
                </div>
                {/* 假「打卡」按钮已拆（2026-09-09）：后端打卡链 S5 就通了，缺的是这个
                    按钮到不了它——打卡请对教练说「我完成了××」；专用按钮接线归答题 UI 欠账。 */}
              </div>
            </div>
          </header>

          {/* 内容挂载点：flex-col 才有 definite 高度可分——Chat 根的 flex-1
              （消息滚、输入岛钉底）此前是 block 子项 flex-1 无效，长对话把
              输入框顶出屏幕；其余页超长时滚动上抛给 main 兜底 */}
          <div className="flex min-h-0 flex-1 flex-col">
            {page === "chat"     && <Chat />}
            {page === "plan"     && <Plan />}
            {page === "material" && <Materials />}
            {page === "memory"   && <Memory />}
            {page === "settings"  && <Settings />}
            {page === "admin"     && <Admin />}
          </div>
        </main>

        {/* ========== 移动端底部导航（safe-area 适配） ========== */}
        <nav
          className="fixed inset-x-0 bottom-0 z-40 flex md:hidden"
          aria-label="移动端主导航"
          style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
        >
          <div
            className="flex w-full border-t border-white/10"
            style={{ backgroundColor: "var(--color-ink)" }}
          >
            {nav.map((p) => {
              const active = p.key === page;
              return (
                <button
                  key={p.key}
                  onClick={() => setPage(p.key)}
                  aria-current={active ? "page" : undefined}
                  className={`relative flex flex-1 flex-col items-center justify-center gap-1 py-3 transition-all duration-300 ${
                    active ? "text-wheat" : "text-parchment/45"
                  }`}
                  style={{ transitionTimingFunction: "var(--ease-glide)" }}
                >
                  {active && (
                    <span
                      className="absolute top-1 size-1 rounded-full"
                      style={{ backgroundColor: "var(--color-copper)" }}
                    />
                  )}
                  <NavIcon name={p.key} />
                  <span className="text-[11px] font-semibold">{p.label}</span>
                </button>
              );
            })}
          </div>
        </nav>
      </div>
    </div>
  );
}
