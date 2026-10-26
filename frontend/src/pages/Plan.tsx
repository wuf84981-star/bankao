/* ============================================================
 * 计划页 v3（D83 换真 · 2026-10-18 用户拍板「乙」）
 * v2→v3：道具全拆——「今天」用真时钟、考试日读主考档案真账
 * （治侧栏 42 与日历 87 打架案）、格子色块按 active 计划 done/total
 * 真比例、打卡走 /api/plan/item/{id}/check（乐观改勾→服务器落账→回拉两本账）。
 * 视觉件一字不动：Double-Bezel 月历 / 沉铜绿色阶 / 麦黄便利贴（BR-06）/
 * 勾选画勾动画 / Kind 异形徽章 / 空态艺术卡 / Segmented 滑动胶囊。
 * 无 active 计划时横幅指路（草案待激活去「对话」说一句），格子全白不撒谎。
 * 样式偏好存本浏览器 localStorage（丙案砍掉：不值一次迁移）。
 * ============================================================ */

import { useEffect, useState, type ReactElement } from "react";
import { api } from "../auth";

type Kind = "new" | "exercise" | "review" | "mock" | "sprint";
type Item = {
  id: number;
  subject: string | null;
  task: string;
  est_minutes: number;
  kind: Kind | null;
  status: string;   // pending/done/partial（页面门只翻 done↔pending，partial 口述账不动）
};
type DayAgg = { total: number; done: number };
type Summary = {
  exam: { name: string; date: string } | null;
  active: { id: number; version: number; start_date: string } | null;
  draft: { id: number; version: number; items: number } | null;
};

/* 真今天（本地日历日，一次定终身：跨零点挂着不刷新属可接受误差） */
const TODAY = (() => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
})();
const THIS_MONTH = TODAY.slice(0, 7);

/**
 * 5 种 Kind 异形徽章组件（视觉各不相同，非统一形状改色）。
 * ① 新知识：圆角绿色岛
 * ② 刷题：圆角 ink/10 方岛
 * ③ 复习：虚线边框 方岛
 * ④ 模考：菱形斜角（rotate-1 → 文字反斜回来）
 * ⑤ 冲刺：全沉铜绿药丸 parchment 白字
 * @param kind kind 枚举
 * @returns 徽章 JSX 元素
 */
function KindBadge({ kind }: { kind: Kind }) {
  switch (kind) {
    case "new":
      return (
        <span
          className="rounded-full px-3 py-1 text-[11px] font-bold tracking-wide"
          style={{
            backgroundColor: "rgba(91,115,120,0.12)",
            color: "var(--color-copper)",
          }}
        >
          新知识
        </span>
      );
    case "exercise":
      return (
        <span
          className="rounded-[0.5rem] px-3 py-1 text-[11px] font-bold tracking-wide"
          style={{
            backgroundColor: "rgba(28,35,41,0.08)",
            color: "var(--color-ink)",
          }}
        >
          刷题
        </span>
      );
    case "review":
      return (
        <span
          className="rounded-[0.5rem] border border-dashed px-3 py-1 text-[11px] font-bold tracking-wide"
          style={{ borderColor: "rgba(28,35,41,0.25)", color: "var(--color-ink-soft)" }}
        >
          复习
        </span>
      );
    case "mock":
      return (
        <span
          className="inline-block rounded-md px-3 py-1"
          style={{
            transform: "rotate(1deg)",
            backgroundColor: "rgba(91,115,120,0.10)",
            color: "var(--color-copper-dk)",
          }}
        >
          <span
            className="text-[11px] font-bold tracking-wide inline-block"
            style={{ transform: "rotate(-1deg)" }}
          >
            模考
          </span>
        </span>
      );
    case "sprint":
      return (
        <span
          className="rounded-full px-3 py-1 text-[11px] font-bold tracking-wide"
          style={{
            backgroundColor: "var(--color-copper)",
            color: "var(--color-parchment)",
          }}
        >
          冲刺
        </span>
      );
  }
}

/**
 * SVG 自定义勾选框：圆形外环 + 勾边 draw 动画。
 * @param checked 是否勾选
 * @param onChange 切换回调
 * @param ariaLabel 无障碍标签
 */
function CheckCircle({
  checked,
  onChange,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  ariaLabel: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={() => onChange(!checked)}
      className={`grid size-6 shrink-0 place-items-center rounded-full ring-1.5 transition-all duration-300 ${
        checked ? "ring-copper" : "ring-ink/20 hover:ring-copper"
      }`}
      style={{
        backgroundColor: checked ? "var(--color-copper)" : "transparent",
        transitionTimingFunction: "var(--ease-glide)",
      }}
    >
      {checked ? (
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--color-parchment)"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="animate-draw-check"
        >
          <path d="M20 6 9 17l-5-5" pathLength="1" />
        </svg>
      ) : null}
    </button>
  );
}

/* ===== 样式偏好：存本浏览器（丙案砍掉的落库，localStorage 顶用） ===== */
const PREF_KEY = "bankao.plan.……";
type Accent = "copper" | "wheat" | "ink";
const readPref = <T,>(k: string, dft: T): T => {
  try {
    const raw = JSON.parse(localStorage.getItem(PREF_KEY) ?? "{}") as Record<string, unknown>;
    return (raw[k] as T) ?? dft;
  } catch {
    return dft;
  }
};

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

export default function Plan() {
  const [view, setView] = useState<"month" | "day">("month");
  const [selected, setSelected] = useState(TODAY);

  /* 三本真账：summary（页头+横幅）/ days（月格聚合）/ items（当日明细） */
  const [summary, setSummary] = useState<Summary | null>(null);
  const [month, setMonth] = useState(THIS_MONTH);
  const [days, setDays] = useState<Record<string, DayAgg>>({});
  const [items, setItems] = useState<Item[]>([]);

  /* 日历样式壳：3 switch + 色选（localStorage 持久，D83 从纯摆饰升级） */
  const [showBlocks,     setShowBlocks]     = useState(() => readPref("showBlocks", true));
  const [showDots,       setShowDots]       = useState(() => readPref("showDots", true));
  const [highlightToday, setHighlightToday] = useState(() => readPref("highlightToday", true));
  const [accent, setAccent] = useState<Accent>(() => readPref("accent", "copper"));
  useEffect(() => {
    localStorage.setItem(PREF_KEY, JSON.stringify({ showBlocks, showDots, highlightToday, accent }));
  }, [showBlocks, showDots, highlightToday, accent]);

  const loadCal = (m: string) =>
    api(`/api/plan/calendar?month=${m}`)
      .then((d) => {
        const rows = (d as { days: { date: string; total: number; done: number }[] }).days;
        setDays(Object.fromEntries(rows.map((r) => [r.date, { total: r.total, done: r.done }])));
      })
      .catch(() => {});   // 拉不到就维持现账，页面不炸（后端的 403/5xx 才是法律）
  const loadDay = (dt: string) =>
    api(`/api/plan/day?date=${dt}`)
      .then((d) => setItems((d as { items: Item[] }).items))
      .catch(() => {});

  useEffect(() => {
    api("/api/plan/summary")
      .then((d) => setSummary(d as Summary))
      .catch(() => {});
  }, []);
  useEffect(() => { loadCal(month); }, [month]);
  useEffect(() => { loadDay(selected); }, [selected]);

  /**
   * 打卡（页面门）：乐观改勾 → POST → 成功回拉两本账（服务器为真）；
   * 失败回弹原 status（D62 即改即 POST 家法，账不骗人）。
   */
  function tick(it: Item, v: boolean) {
    const back = it.status;
    setItems((l) => l.map((x) => (x.id === it.id ? { ...x, status: v ? "done" : "pending" } : x)));
    api(`/api/plan/item/${it.id}/check`, { done: v })
      .then(() => { loadDay(selected); loadCal(month); })
      .catch(() =>
        setItems((l) => l.map((x) => (x.id === it.id ? { ...x, status: back } : x))));
  }

  /* ===== 派生账 ===== */
  const examName = summary?.exam?.name ?? null;
  const examDate = summary?.exam?.date ?? null;
  function daysToExam(dateStr: string): number | null {
    if (!examDate) return null;
    const a = new Date(`${dateStr}T00:00:00`).getTime();
    const b = new Date(`${examDate}T00:00:00`).getTime();
    return Math.round((b - a) / 86_400_000);
  }
  /** 完成度（真账）：done/total 百分比；partial 不算完成（诚实口径）。 */
  const completion = (dateStr: string): number => {
    const a = days[dateStr];
    return a && a.total ? Math.round((a.done * 100) / a.total) : 0;
  };

  const tasks = items;
  const doneCount = tasks.filter((t) => t.status === "done").length;

  /* 月格：按真月份铺（首月由「月」状态定，含 ‹ › 翻月） */
  const [my, mm] = month.split("-").map(Number);
  const lead = (new Date(my, mm - 1, 1).getDay() + 6) % 7;
  const nDays = new Date(my, mm, 0).getDate();
  const cells: (string | null)[] = [
    ...Array.from({ length: lead }, () => null),
    ...Array.from({ length: nDays }, (_, i) => `${month}-${String(i + 1).padStart(2, "0")}`),
  ];
  function shiftMonth(delta: number) {
    const t = new Date(my, mm - 1 + delta, 1);
    setMonth(`${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}`);
  }

  /**
   * accent 颜色映射定义。
   * wheat 本身是极浅的奶油黄（#F5EAD3），无法表达完成度深浅，
   * 故「麦黄主题」的主色使用同色系的 rust 赭石（#A0522D）。
   * @property var  — CSS 变量，用于 color-mix / 描边 / 圆点
   * @property rgb  — 纯 RGB 三元组字符串，用于 rgba() 阴影
   */
  const accentDef = (() => {
    switch (accent) {
      case "copper": return { var: "var(--color-copper)", rgb: "94,133,119"  };
      case "wheat":  return { var: "var(--color-rust)",   rgb: "160,82,45"   };
      case "ink":    return { var: "var(--color-ink)",    rgb: "31,42,51"    };
    }
  })();

  /** SwitchRow：样式卡内开关行 */
  function SwitchRow({ label, sub, on, set }: { label:string; sub?: string; on: boolean; set:(b:boolean)=>void; }): ReactElement {
    return (
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-bold text-ink">{label}</p>
          {sub && <p className="mt-0.5 text-[11px] font-semibold text-ink/65">{sub}</p>}
        </div>
        <button type="button" onClick={()=>set(!on)}
                className="inline-flex h-6 w-11 shrink-0 items-center rounded-full p-[2px] transition-all duration-300 active:scale-[0.97]"
                style={{backgroundColor: on ? "var(--color-copper)" : "var(--color-mist)", transitionTimingFunction:"var(--ease-spring-in)"}}>
          <span className={`h-5 size-5 rounded-full transition-all duration-300 ${on ? "translate-x-5" : "translate-x-0"}`}
                style={{backgroundColor:"#FFFDF7", boxShadow:"0 1px 3px rgba(28,35,41,0.25)", transitionTimingFunction:"var(--ease-spring-in)"}}/>
        </button>
      </div>
    );
  }

  const segOpts = [
    ["month", "日历总览"],
    ["day", selected === TODAY ? "今日视图" : "当日视图"],
  ] as const;

  const leftSel = daysToExam(selected);

  return (
    <section className="flex-1 overflow-y-auto px-5 py-6 md:px-8 md:py-8 md:flex md:items-start md:gap-8">
      <div className="w-full flex-1 min-w-0">
        {/* ====== D83 横幅：active 计划不在账上时如实指路（格子全白，不摆假日历） ====== */}
        {summary && !summary.active && (
          <div
            className="mb-5 max-w-4xl rounded-[1.25rem] px-5 py-4 ring-1 ring-ink/5 animate-float-up"
            style={{
              backgroundColor: "var(--color-wheat)",
              boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
            }}
          >
            <p className="text-[13px] font-bold text-ink">
              {summary.draft
                ? `计划 v${summary.draft.version}（${summary.draft.items} 条任务）还是草案，没生效。`
                : "还没有排过计划。"}
            </p>
            <p className="mt-1 text-[12px] font-semibold text-ink/70">
              去「对话」里跟教练说一声{summary.draft ? "「激活计划」" : "「帮我排个计划」"}，这页就点亮。
            </p>
          </div>
        )}

        {/* ====== Segmented Control 滑动胶囊（视图切换） ====== */}
        <div className="relative mb-6 inline-flex w-full max-w-[22rem] items-stretch rounded-full bg-mist p-1">
          <div
            aria-hidden
            className="absolute top-1 bottom-1 w-1/2 rounded-full"
            style={{
              backgroundColor: "var(--color-ink)",
              transform: view === "month" ? "translateX(0%)" : "translateX(100%)",
              transition: "transform 500ms var(--ease-spring-out)",
              boxShadow: "var(--shadow-float-sm)",
            }}
          />
          {segOpts.map(([k, label]) => {
            const active = view === k;
            return (
              <button
                key={k}
                type="button"
                onClick={() => setView(k)}
                className={`relative z-10 flex-1 rounded-full px-4 py-2.5 text-[13px] font-bold transition-colors duration-300 ${
                  active ? "" : "text-ink/80 hover:text-ink"
                }`}
                style={{ color: active ? "#FFFDF7" : undefined, transitionTimingFunction: "var(--ease-glide)" }}
              >
                {label}
              </button>
            );
          })}
        </div>

        {view === "month" ? (
          /* ==================== 月历视图 ==================== */
          <div
            className="max-w-4xl rounded-[2rem] p-4 ring-1 ring-ink/5 animate-float-up"
            style={{ backgroundColor: "var(--color-mist)", boxShadow: "var(--shadow-float-sm)" }}
          >
            <div
              className="rounded-[calc(2rem-0.5rem)] px-5 py-5 md:px-5 md:py-5"
              style={{
                backgroundColor: "var(--color-parchment)",
                boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)",
              }}
            >
              {/* 头部：真月份 display 大字 + ‹ › 翻月 + 说明 + 倒计时胶囊（档案真值） */}
              <div className="mb-5 flex items-end justify-between">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label="上一月"
                    onClick={() => shiftMonth(-1)}
                    className="grid size-8 place-items-center rounded-full ring-1 ring-ink/10 text-ink/70 transition hover:ring-copper hover:text-copper"
                  >
                    ‹
                  </button>
                  <h3 className="font-display text-2xl text-ink tabular-nums">
                    {my} 年 {mm} 月
                  </h3>
                  <button
                    type="button"
                    aria-label="下一月"
                    onClick={() => shiftMonth(1)}
                    className="grid size-8 place-items-center rounded-full ring-1 ring-ink/10 text-ink/70 transition hover:ring-copper hover:text-copper"
                  >
                    ›
                  </button>
                </div>
                <p className="hidden sm:block text-[12px] font-semibold text-ink/70">
                  格子越深 = 完成度越高 · 今日框高亮
                </p>
                {examName && leftSel !== null && summary?.active && (
                  <div
                    className="rounded-full px-4 py-1.5 text-[11px] font-bold tracking-[0.2em]"
                    style={{
                      backgroundColor: "rgba(91,115,120,0.10)",
                      color: "var(--color-copper-dk)",
                    }}
                  >
                    距 {examName} {daysToExam(TODAY)} 天
                  </div>
                )}
              </div>

              {/* 星期栏 */}
              <div className="mb-2 grid grid-cols-7 gap-1.5 md:gap-2">
                {WEEKDAYS.map((w) => (
                  <div
                    key={w}
                    className="pb-1 text-center text-[11px] font-bold tracking-[0.15em] text-ink/65"
                  >
                    周{w}
                  </div>
                ))}
              </div>

              {/* 日期格 */}
              <div className="grid grid-cols-7 gap-1.5 md:gap-2">
                {cells.map((d, i) =>
                  d === null ? (
                    <div key={`x${i}`} />
                  ) : (
                    <button
                      key={d}
                      type="button"
                      onClick={() => {
                        setSelected(d);
                        setView("day");
                      }}
                      aria-label={`${d}，完成度 ${completion(d)}%`}
                      className={`group relative aspect-square rounded-[0.85rem] tabular-nums transition-all duration-300 ${
                        d === TODAY ? "font-bold" : "font-semibold"
                      }`}
                      style={{
                        /* 真今天：accent 实底白字最跳（盖过完成度色块）；过去：整体降透明成「记录」；未来：原样 */
                        background:
                          d === TODAY && highlightToday
                            ? accentDef.var
                            : showBlocks
                            ? `color-mix(in srgb, ${accentDef.var} ${completion(d) * 0.55}%, var(--color-cream))`
                            : "var(--color-cream)",
                        color:
                          d === TODAY && highlightToday
                            ? "#FFFDF7"
                            : !showBlocks
                            ? "var(--color-ink)"
                            : completion(d) > 60 ? "#FFFDF7" : "var(--color-ink)",
                        opacity: d < TODAY ? 0.5 : 1,
                        transitionTimingFunction: "var(--ease-spring-out)",
                        boxShadow:
                          d === TODAY && highlightToday
                            ? `0 6px 16px rgba(${accentDef.rgb},0.30)`
                            : undefined,
                        ...(d === TODAY && highlightToday
                          ? {
                              outline: `2px solid ${accentDef.var}`,
                              outlineOffset: "2px",
                              transform: "translateY(-2px)",
                            }
                          : {}),
                      }}
                      onMouseEnter={(e) => {
                        const isPinnedToday = d === TODAY && highlightToday;
                        if (!isPinnedToday) {
                          e.currentTarget.style.transform = "translateY(-2px)";
                          e.currentTarget.style.boxShadow =
                            "0 4px 12px rgba(28,35,41,0.08)";
                        }
                      }}
                      onMouseLeave={(e) => {
                        const isPinnedToday = d === TODAY && highlightToday;
                        if (!isPinnedToday) {
                          e.currentTarget.style.transform = "";
                          e.currentTarget.style.boxShadow = "";
                        }
                      }}
                    >
                      <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-[13px] md:text-sm">
                        {Number(d.slice(-2))}
                      </span>
                      {showDots && days[d]?.total ? (
                        <span
                          className="absolute bottom-1.5 left-1/2 size-1.5 -translate-x-1/2"
                          style={{
                            borderRadius: "2px",
                            backgroundColor:
                              d === TODAY && highlightToday
                                ? "var(--color-parchment)"   // 实底上 accent 点会隐身，翻白
                                : completion(d) > 60
                                ? "var(--color-parchment)"
                                : accentDef.var,
                            opacity: 0.85,
                          }}
                        />
                      ) : null}
                    </button>
                  )
                )}
              </div>

              {/* 图例 */}
              <div className="mt-5 flex flex-wrap items-center gap-4 text-[11px] font-semibold text-ink/70">
                <span className="inline-flex items-center gap-2">
                  <span
                    className="size-4 rounded-[0.35rem]"
                    style={{ backgroundColor: "var(--color-cream)", border: "1px solid var(--color-sand)" }}
                  />
                  未开始
                </span>
                <span className="inline-flex items-center gap-2">
                  <span
                    className="size-4 rounded-[0.35rem]"
                    style={{
                      background: showBlocks
                        ? `color-mix(in srgb, ${accentDef.var} 30%, var(--color-cream))`
                        : "var(--color-cream)",
                      border: showBlocks ? undefined : "1px solid var(--color-sand)",
                    }}
                  />
                  进行中
                </span>
                <span className="inline-flex items-center gap-2">
                  <span
                    className="size-4 rounded-[0.35rem]"
                    style={{
                      background: showBlocks
                        ? `color-mix(in srgb, ${accentDef.var} 55%, var(--color-cream))`
                        : "var(--color-cream)",
                      border: showBlocks ? undefined : "1px solid var(--color-sand)",
                    }}
                  />
                  已完成
                </span>
                <span className="inline-flex items-center gap-2">
                  <span className="size-1.5 rounded-[2px]" style={{ backgroundColor: accentDef.var }} />
                  有任务
                </span>
              </div>
            </div>
          </div>
        ) : (
          /* ==================== 当日视图 ==================== */
          <div className="max-w-4xl animate-float-up">
            {/* 顶部：日期 + 便利贴倒计时（主考档案真值） */}
            <div className="mb-6 flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] font-bold tracking-[0.2em] text-ink/65">
                  {(() => {
                    const [y, m, d] = selected.split("-");
                    return `${y} 年 ${Number(m)} 月 ${Number(d)} 日`;
                  })()}
                </p>
                <h2 className="mt-1 font-display text-3xl leading-tight text-ink">
                  {selected === TODAY ? "今天，也要一步一步来。" : selected < TODAY ? "之前走过的那天。" : "还没到来的那一天。"}
                </h2>
                {examName && leftSel !== null && (
                  <p className="mt-2 text-[13px] font-semibold text-ink/70">
                    距 {examName} 开考{" "}
                    <span className="font-mono font-bold tabular-nums text-copper">
                      {leftSel}
                    </span>{" "}
                    天（BR-06 · 所有计划语境都带天数）
                  </p>
                )}
              </div>
              {/* 麦黄便利贴倒计时签名件（BR-06 复用） */}
              {examName && leftSel !== null && (
                <div className="shrink-0 hidden sm:block">
                  <div
                    className="rounded-[1rem] p-1"
                    style={{
                      backgroundColor: "rgba(239,230,210,0.7)",
                      transform: "rotate(-1deg)",
                      boxShadow: "var(--shadow-wheat)",
                    }}
                  >
                    <div
                      className="rounded-[calc(1rem-0.25rem)] px-4 py-3 text-center"
                      style={{
                        backgroundColor: "var(--color-wheat)",
                        boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
                        color: "var(--color-ink)",
                      }}
                    >
                      <div className="text-[10px] font-bold tracking-[0.15em] text-ink/70">
                        距 {examName}
                      </div>
                      <div
                        className="mt-0.5 font-mono text-3xl font-black leading-none tabular-nums"
                        style={{ color: "var(--color-copper-dk)" }}
                      >
                        {leftSel}
                      </div>
                      <div className="mt-0.5 text-[10px] font-bold tracking-[0.15em] text-ink/70">天</div>
                    </div>
                  </div>
                </div>
              )}
            </div>

            {/* 任务列表 / 空态 */}
            {tasks.length === 0 ? (
              // 空态：Double-Bezel 艺术卡
              <div
                className="rounded-[1.75rem] p-2 ring-1 ring-ink/5"
                style={{ backgroundColor: "rgba(239,230,210,0.55)" }}
              >
                <div
                  className="rounded-[calc(1.75rem-0.5rem)] px-8 py-14 text-center"
                  style={{
                    backgroundColor: "var(--color-wheat)",
                    boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
                  }}
                >
                  <svg
                    width="56"
                    height="56"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="var(--color-copper-dk)"
                    strokeWidth="1.25"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="mx-auto mb-4 opacity-80"
                  >
                    <path d="M18 10a6 6 0 0 0-12 0c0 7-6 7-6 12h24c0-5-6-5-6-12z"/>
                    <circle cx="12" cy="13" r="1.75"/>
                  </svg>
                  <p className="font-display text-2xl leading-relaxed text-ink">
                    {selected === TODAY && summary?.active
                      ? "休整也是计划的一部分。"
                      : "这一天还没有安排。"}
                  </p>
                  <p className="mt-3 text-[13px] font-semibold text-ink/75">
                    {summary?.active
                      ? selected === TODAY
                        ? "放轻松，我明天再催你。"
                        : (summary.draft ? "想补排去「对话」找教练商量。" : "过去的日子记账，未来的日子排账。")
                      : "去「对话」里跟教练说一声，先排一份计划。"}
                  </p>
                </div>
              </div>
            ) : (
              <>
                <ul className="space-y-4">
                  {tasks.map((t) => {
                    const on = t.status === "done";
                    return (
                      <li
                        key={t.id}
                        className="rounded-[1.5rem] p-1.5 ring-1 ring-ink/5 transition-all duration-500"
                        style={{
                          backgroundColor: "var(--color-mist)",
                          transitionTimingFunction: "var(--ease-spring-out)",
                          boxShadow: "var(--shadow-float-sm)",
                          opacity: on ? 0.6 : 1,
                        }}
                      >
                        <div
                          className="flex items-start gap-4 rounded-[calc(1.5rem-0.375rem)] px-5 py-5"
                          style={{
                            backgroundColor: "var(--color-parchment)",
                            boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)",
                          }}
                        >
                          <CheckCircle
                            checked={on}
                            onChange={(v) => tick(t, v)}
                            ariaLabel={`完成：${t.task}`}
                          />
                          <div className="min-w-0 flex-1">
                            <p
                              className={`font-heading text-[15px] font-semibold leading-snug ${
                                on ? "line-through decoration-copper/60 decoration-2" : ""
                              }`}
                              style={{ color: "var(--color-ink)" }}
                            >
                              {t.task}
                              {t.status === "partial" && (
                                <span className="ml-2 text-[11px] font-bold text-copper">（部分完成）</span>
                              )}
                            </p>
                            <p className="mt-1.5 text-[13px] font-semibold text-ink/70">
                              {t.subject ?? "综合"}
                              <span className="mx-2 text-sand">·</span>
                              约{" "}
                              <span
                                className="font-mono font-bold tabular-nums"
                                style={{ color: "var(--color-copper)" }}
                              >
                                {t.est_minutes}
                              </span>{" "}
                              分钟
                            </p>
                          </div>
                          {t.kind && (
                            <div className="shrink-0">
                              <KindBadge kind={t.kind} />
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
                {/* 完成计数 */}
                <p className="mt-5 text-right font-mono text-[12px] font-semibold tabular-nums text-ink/70">
                  已完成{" "}
                  <span className="font-bold text-copper">{doneCount}</span>
                  <span className="mx-1">/</span>
                  {tasks.length}
                  <span className="mx-2 text-sand">·</span>
                  <span>勾选实时落计划账，格子深浅跟着动</span>
                </p>
              </>
            )}
          </div>
        )}
      </div>

      {/* ====== 右侧：日历样式设置壳卡（桌面 md+ 显示 · 偏好存本浏览器） ====== */}
      <aside className="hidden md:block w-[290px] shrink-0 animate-float-up">
        <div className="sticky top-8 space-y-6">
          <div className="rounded-[1.5rem] p-1.5 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)", boxShadow:"var(--shadow-float-sm)"}}>
            <div className="rounded-[calc(1.5rem-0.375rem)] px-5 py-6" style={{backgroundColor:"var(--color-parchment)", boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
              <p className="text-[10px] font-bold tracking-[0.25em] text-copper">日历 · 样式</p>
              <h3 className="mt-1 font-display text-[20px] leading-tight text-ink">显示的样子，你说了算。</h3>
              <p className="mt-1 text-[12px] font-semibold text-ink/65">偏好存本浏览器，换设备需重调。</p>

              <div className="mt-5 space-y-4">
                <SwitchRow label="显示完成度色块" sub="月视图每个格子的深浅" on={showBlocks} set={setShowBlocks}/>
                <SwitchRow label="显示任务小圆点" sub="有任务的日子底部会亮" on={showDots} set={setShowDots}/>
                <SwitchRow label="高亮今日"     sub="铜绿光晕 + 描边浮起" on={highlightToday} set={setHighlightToday}/>
              </div>

              <div className="my-5 h-px w-full" style={{backgroundColor:"var(--color-mist)"}}/>

              <p className="text-[11px] font-bold tracking-[0.2em] text-ink/65">日历主题色</p>
              <div className="mt-3 flex items-center gap-3">
                {([
                  {k:"copper", label:"铜绿", bg:"var(--color-copper)"},
                  {k:"wheat",  label:"麦黄", bg:"var(--color-wheat)"},
                  {k:"ink",    label:"墨青", bg:"var(--color-ink)"},
                ] as const).map((c)=>(
                  <button key={c.k} type="button" onClick={()=>setAccent(c.k)}
                          className="group relative inline-flex items-center gap-2 rounded-full px-3 py-1.5 transition-all duration-300"
                          style={{
                            backgroundColor: c.k === "wheat" ? "rgba(239,230,210,0.5)" : c.k === "ink" ? "rgba(28,35,41,0.08)" : "rgba(91,115,120,0.12)",
                            border: accent===c.k ? "2px solid var(--color-copper)" : "1px solid rgba(28,35,41,0.05)",
                            boxShadow: accent===c.k ? "var(--shadow-copper)" : undefined,
                            transitionTimingFunction:"var(--ease-glide)",
                          }}>
                    <span className="size-4 rounded-full" style={{backgroundColor: c.bg}}/>
                    <span className="text-[12px] font-bold" style={{color:"rgba(28,35,41,0.85)"}}>{c.label}</span>
                    {accent===c.k && (
                      <span className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full text-parchment" style={{backgroundColor:"var(--color-copper)", boxShadow:"var(--shadow-copper)"}}>
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#FFFDF7" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                      </span>
                    )}
                  </button>
                ))}
              </div>

              <button type="button"
                      onClick={()=>{ setShowBlocks(true); setShowDots(true); setHighlightToday(true); setAccent("copper"); }}
                      className="mt-6 inline-flex w-full items-center justify-center rounded-full px-4 py-2 text-[12px] font-bold transition duration-300"
                      style={{backgroundColor:"var(--color-mist)", color:"rgba(28,35,41,0.82)", transitionTimingFunction:"var(--ease-glide)"}}>
                重置为默认
              </button>
            </div>
          </div>
        </div>
      </aside>
    </section>
  );
}
