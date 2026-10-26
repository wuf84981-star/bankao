/* ============================================================
 * 记忆页 v3（S7 九刀 · D47 甲：整页接真账，INITIAL 道具全摘）
 * 数据源：GET /api/memories 聚合五本账（档案/知识点/错误/事件/待确认推测）
 * id 是带表前缀的字符串（p/m/k/x/e）——只有 m 前缀行带确认/删除按钮，
 *   动写面时剥掉前缀拿真 fact id 交票。
 * Tab：滑动胶囊指示器（getBoundingClientRect 动态算宽位）
 * 卡片：Double-Bezel + 来源异形徽章岛（你说过方岛 / 我猜的菱岛）
 * 核心动效：点击 → 卡片飞出（0.48s）→ POST 真账 → 重拉列表 → Toast
 *   确认=BR-02 升格（inferred→user_stated + confirmed）；删除=BR-07 物理删
 * D85 F-13 页面门：m 行就地改（失焦落账）、kp 行五档药丸点档即换——与聊天指令等效落库
 * D86 遗忘臂：档案正式条目「✕ 忘了这条」两步确认物理删（与聊天 forget_memory 同腿，后端零改）
 * D87 档案门：p 行就地改名字/日期（pf 结构化票喂编辑框，不拆 text）；日期挪了回执报警、toast 指路重排
 * D88 管理弹窗制（用户拍板「点进去后可以修改和删除/遗忘」）：外面纯展示，卡片整张可点；
 *   弹窗内改/忘/换档/确认升格，档案删除腿接 DELETE /api/memories/profile（删主考库内自动晋主）
 * 时效事件：到期日用 mono 字体显示（BR-03）
 * Toast：fixed 顶部中央药丸入场/出场（GPU Safe backdrop-blur 允许）
 * BR-02/03/07 规则：中文胶囊 tag 底部
 * ============================================================ */

import { useEffect, useRef, useState } from "react";
import { api, apiDelete } from "../auth";

type Cat = "profile" | "kp" | "error" | "event" | "pending";
/** 后端 /api/memories 的展示行：id 带表前缀防五本账串号；
 *  ms=结构化进度票（D85，仅 kp 行带——页面换档按钮的票根是 mastery 真 id）；
 *  pf=结构化档案票（D87，仅 p 行带——编辑框填名字/日期用真值，不拆 text 拼串）。 */
type Mem = { id: string; cat: Cat; text: string; source: "明确" | "推测"; meta?: string | null;
             ms?: { mid: number; level: string; exam: string }[];
             pf?: { pid: number; name: string; date: string } };

/** 掌握度五档花名册——backend/tools.py MASTERY_LEVELS 的字面镜像：那边改档
 *  这边必须同步改（跨文件字面契约，四刀「两枚常量成对」教训）；后端的 422 才是真闸。 */
const LEVELS = ["未接触", "初步了解", "一般掌握", "熟练", "薄弱"];

const CATS: { key: Cat; label: string }[] = [
  { key: "profile", label: "档案" },
  { key: "kp",      label: "知识点" },
  { key: "error",   label: "错误模式" },
  { key: "event",   label: "时效事件" },
  { key: "pending", label: "待确认" },
];

/**
 * 顶部中央 Toast 药丸（与 Chat 同款：fixed → backdrop-blur GPU Safe）。
 * @param t 状态对象，含 closing 用于切换出场动画
 */
function Toast({ t }: { t: { id: number; text: string; closing?: boolean } }) {
  return (
    <div
      className="fixed left-1/2 top-6 z-50"
      style={{ transform: "translateX(-50%)" }}
    >
      <div
        className={`rounded-full p-1 ring-1 backdrop-blur-xl ${
          t.closing ? "animate-toast-out" : "animate-toast-in"
        }`}
        style={{
          backgroundColor: "rgba(98,117,122,0.10)",
          borderColor: "rgba(98,117,122,0.20)",
          boxShadow: "0 0 0 1px rgba(98,117,122,0.20)",
        }}
      >
        <div
          className="rounded-full px-5 py-2.5 text-[13px] font-bold"
          style={{
            backgroundColor: "rgba(255,251,243,0.92)",
            color: "var(--color-copper)",
            boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
          }}
        >
          {t.text}
        </div>
      </div>
    </div>
  );
}

/**
 * 来源徽章：2 种异形岛（方岛 vs 菱岛）。
 * @param source "明确" → 方岛 文案"你说过"；"推测" → 菱岛 rotate-4 文案"我猜的"
 */
function SourceBadge({ source }: { source: Mem["source"] }) {
  if (source === "明确") {
    return (
      <span
        className="rounded-[0.5rem] px-3 py-1 text-[11px] font-bold tracking-wide"
        style={{
          backgroundColor: "rgba(28,35,41,0.10)",
          color: "var(--color-ink)",
        }}
      >
        你说过
      </span>
    );
  }
  // 推测：菱形斜切岛（容器 -4°，内容 +4°，文字回正）
  return (
    <span
      className="inline-block rounded-[0.4rem] px-3 py-1"
      style={{
        transform: "rotate(-4deg)",
        backgroundColor: "rgba(98,117,122,0.14)",
        color: "var(--color-copper-dk)",
      }}
    >
      <span
        className="inline-block text-[11px] font-bold tracking-wide"
        style={{ transform: "rotate(4deg)" }}
      >
        我猜的
      </span>
    </span>
  );
}

/**
 * meta 中若含日期，高亮显示到期日（mono 字体 + 铜绿）；
 * 其余 meta 正常显示。
 * @param meta 原 meta 字段
 */
function MetaLine({ meta }: { meta: string }) {
  // 匹配「到期 · YYYY-MM-DD」的模式
  const m = meta.match(/^(到期\s*[·．]\s*)(\d{4}-\d{2}-\d{2})(.*)$/);
  if (m) {
    return (
      <p className="mt-3 text-[12px] font-semibold text-ink/70">
        {m[1]}
        <span className="font-mono font-bold tabular-nums text-copper">{m[2]}</span>
        {m[3]}
      </p>
    );
  }
  return <p className="mt-3 text-[12px] text-ink/50">{meta}</p>;
}

/**
 * 空态卡：Double-Bezel + 手绘细线 SVG（抽屉或大脑图标）+ 温暖中文文案。
 */
function EmptyState({ tab }: { tab: Cat }) {
  const msg =
    tab === "pending"
      ? { title: "没有需要你确认的事", sub: "我没做任何猜测，目前我说的每一句都是你告诉我的。" }
      : { title: "这个抽屉还空着。", sub: "等攒够经历，我会悄悄把这里填满。" };

  return (
    <div
      className="rounded-[1.5rem] p-1.5 ring-1 ring-ink/5"
      style={{ backgroundColor: "var(--color-mist)" }}
    >
      <div
        className="rounded-[calc(1.5rem-0.375rem)] px-6 py-12 text-center"
        style={{
          backgroundColor: "var(--color-parchment)",
          boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)",
        }}
      >
        <svg
          width="64"
          height="64"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--color-copper-dk)"
          strokeWidth="1.25"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="mx-auto mb-5 opacity-80"
        >
          <path d="M4 8h16"/><path d="M6 8V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v3"/><path d="M3 8h18v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8z"/>
          <path d="M9 14h6M9 17h4"/>
        </svg>
        <p className="font-display text-xl leading-relaxed text-ink">{msg.title}</p>
        <p className="mt-2 text-[13px] font-semibold text-ink/70">{msg.sub}</p>
      </div>
    </div>
  );
}

export default function Memory() {
  const [mems, setMems] = useState<Mem[]>([]);
  const [tab, setTab] = useState<Cat>("pending");
  const [toast, setToast] = useState<{ id: number; text: string; closing?: boolean } | null>(null);
  /* D88 点卡开管理弹窗（用户拍板：外面是展示，管理进门做）：
     detail=开着的行 id（null=窗关）；draft/draftPf=窗内编辑草稿（失焦落账，D62 家法照旧）；
     armed=删除腿两步确认武装态（D84 家法；弹窗一次只开一个，bool 够用） */
  const [detail, setDetail] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [draftPf, setDraftPf] = useState<{ name: string; date: string }>({ name: "", date: "" });
  const [armed, setArmed] = useState(false);
  const toastIdRef = useRef(0);

  /** 拉真账整表回填（挂载一次 + 每次写面成功后重拉——不自算增量，账以库为准）。 */
  async function reload() {
    const r = (await api("/api/memories")) as { memories: Mem[] };
    setMems(r.memories);
  }
  useEffect(() => {
    // 拉取失败保持空页（宁空不假）；登录票失效由 api() 的 detail→人话管
    reload().catch(() => {});
  }, []);

  // Tab 滑动指示器尺寸
  const [indicator, setIndicator] = useState<{ left: number; width: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const btnsRef = useRef<Partial<Record<Cat, HTMLButtonElement | null>>>({});

  /** 每次 Tab 或 条目数变化，重新测量指示器尺寸（按钮宽度因计数 badge 而不同）。 */
  useEffect(() => {
    const c = containerRef.current;
    if (!c) return;
    const btn = btnsRef.current[tab];
    if (!btn) return;
    const cr = c.getBoundingClientRect();
    const br = btn.getBoundingClientRect();
    setIndicator({ left: br.left - cr.left, width: br.width });
  }, [tab, mems.length]);

  /** window resize 也更新一下。 */
  useEffect(() => {
    function onResize() {
      const c = containerRef.current;
      const btn = btnsRef.current[tab];
      if (!c || !btn) return;
      const cr = c.getBoundingClientRect();
      const br = btn.getBoundingClientRect();
      setIndicator({ left: br.left - cr.left, width: br.width });
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [tab]);

  /** 显示 Toast：2500ms 后 closing，350ms 后清空。 */
  function showToast(text: string) {
    const id = ++toastIdRef.current;
    setToast({ id, text });
    setTimeout(() => {
      setToast((cur) => (cur && cur.id === id ? { ...cur, closing: true } : cur));
      setTimeout(() => {
        setToast((cur) => (cur && cur.id === id ? null : cur));
      }, 400);
    }, 2500);
  }

  /** D88 弹窗动作公共骨架：落账 → 整表重拉 → 收窗报人话；失败不关窗——
   *  原账原窗，toast 说原因（keepOpen=换档类动作留在窗内连点，不闪窗）。 */
  async function run(action: () => Promise<unknown>, doneText: string,
                     keepOpen = false): Promise<void> {
    try {
      await action();
      await reload();
      if (!keepOpen) setDetail(null);
      showToast(doneText);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "操作失败，账未动");
    }
  }

  /** 点卡进门：装草稿、解除删除武装态——每次开窗都是生手，不误触上一轮的「确认」。 */
  function openDetail(m: Mem): void {
    setDetail(m.id);
    setDraft(m.text);
    if (m.pf) setDraftPf({ name: m.pf.name, date: m.pf.date });
    setArmed(false);
  }
  function closeDetail(): void {
    setDetail(null);
    setArmed(false);
  }

  /** BR-02 确认（pending 窗内一键）：升格翻列，重拉后这条自己搬进「档案」页签。 */
  function confirm(id: string) {
    void run(() => api("/api/memories/confirm", { id: Number(id.slice(1)) }),
      "已确认：这条升格为正式记忆，请到「档案」页签看它。");
  }

  /** 「猜错了，删掉」（pending 窗内一键、不武装）：删的是一句没被认领的猜测，
   *  不是既成事实——与档案遗忘的两步确认语义分家（D86 立场延续）。 */
  function reject(id: string) {
    void run(() => api("/api/memories/forget", { ids: [Number(id.slice(1))] }),
      "已删除：这条已从库里物理清除，永远不会被记住。");
  }

  /** 事实遗忘腿（正式 m 行）：两步确认（D84 家法）——一键武装、二击落刀、blur 解除。 */
  function forgetFact(id: string) {
    if (!armed) { setArmed(true); return; }
    void run(() => api("/api/memories/forget", { ids: [Number(id.slice(1))] }),
      "已遗忘：这条已从库里物理清除，教练不会再记得它。");
  }

  /** D88 档案删除腿：DELETE /api/memories/profile/{pid}（物理删；删主考时库内
   *  自动把剩余最小 id 晋主——页门不许制造全户无主的悬案）。 */
  function forgetProfile(pid: number) {
    if (!armed) { setArmed(true); return; }
    void run(() => apiDelete(`/api/memories/profile/${pid}`),
      "档案已删除。若删的是主考，剩余档案已自动顶上——计划要跟着新主考走，聊天里说「重排计划」。");
  }

  /**
   * D85 F-13 页面门·事实就地改：POST /api/memories/fact 落账（与聊天指令等效——
   *  亲手改即「明确+已确认」），成功整表重拉：升格旗随账翻，这条自己搬进「档案」。
   *  空草稿或没改内容不动账（不白跑一枪让后端 422 当裁判）。窗内失焦即存、窗不关。
   */
  async function editFact(id: string): Promise<void> {
    const content = draft.trim();
    const orig = mems.find((x) => x.id === id)?.text ?? "";
    if (!content || content === orig.trim()) return;
    try {
      await api("/api/memories/fact", { id: Number(id.slice(1)), content });
      await reload();
      showToast("已改好：教练下一句就用这本新账。");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "保存失败，原账未动");
    }
  }

  /**
   * D85 F-13 页面门·掌握度换档：票根用 ms 带的 mastery 真 id（m.id 是展示串号不能用），
   *  点档 POST /api/memories/mastery，置信钉 100（页面亲点=亲口满信），成功重拉以库收口。
   */
  async function setLevel(mid: number, level: string): Promise<void> {
    try {
      await api("/api/memories/mastery", { id: mid, level });
      await reload();
      showToast(`进度已改为「${level}」——这一档算你亲口说的。`);
    } catch (e) {
      showToast(e instanceof Error ? e.message : "换档失败，原档未动");
    }
  }

  /**
   * D87 档案落账：POST /api/memories/profile 带 {名字, 日期} 整对（焦点离开编辑区即存，
   *  容器级 onBlur 防两框之间跳焦误发）。日期挪没挪由服务器裁定（replan 回执）——
   *  挪了就必须指路：已排的计划不会自己跟着挪，去聊天里说「重排计划」。没改不动账。
   */
  async function savePf(idStr: string): Promise<void> {
    const orig = mems.find((x) => x.id === idStr)?.pf;
    if (!orig) return;
    const name = draftPf.name.trim();
    const dt = draftPf.date;
    if (!name || !dt || (name === orig.name && dt === orig.date)) return;
    try {
      const r = (await api("/api/memories/profile",
        { id: orig.pid, exam_type: name, exam_date: dt })) as { replan?: boolean };
      await reload();
      showToast(r.replan
        ? "档案已更新。注意：已排的计划不会自己挪——跟教练说「重排计划」按新日子重排。"
        : "档案已更新。");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "保存失败，原档案未动");
    }
  }

  const shown = mems.filter((m) => m.cat === tab);

  return (
    <section className="flex-1 overflow-y-auto px-5 py-6 md:px-8 md:py-8 mb-10">
      <div className="mx-auto max-w-3xl">
        {toast && <Toast t={toast} />}

        {/* ========== Tab 栏：滑动胶囊指示器 ========== */}
        <div className="mb-6">
          <p className="mb-3 text-[11px] font-bold tracking-[0.2em] text-ink/65">
            它记下的 · 关于你的
          </p>

          <div
            ref={containerRef}
            className="relative inline-flex flex-wrap items-center gap-2 rounded-full p-1 animate-float-up"
            style={{ backgroundColor: "var(--color-mist)" }}
            role="tablist"
            aria-label="记忆分类"
          >
            {/* 滑动指示器胶囊 */}
            {indicator && (
              <div
                aria-hidden
                className="absolute top-1 bottom-1 rounded-full"
                style={{
                  left: indicator.left,
                  width: indicator.width,
                  backgroundColor: "var(--color-ink)",
                  transition:
                    "left 500ms var(--ease-spring-out), width 500ms var(--ease-spring-out)",
                  boxShadow: "var(--shadow-float-sm)",
                }}
              />
            )}

            {CATS.map((c) => {
              const n = mems.filter((m) => m.cat === c.key).length;
              const active = tab === c.key;
              const pendingAccent = c.key === "pending" && n > 0;
              return (
                <button
                  key={c.key}
                  ref={(el) => {
                    btnsRef.current[c.key] = el;
                  }}
                  role="tab"
                  aria-selected={active}
                  onClick={() => setTab(c.key)}
                  className={`relative z-10 inline-flex items-center gap-1.5 rounded-full px-4 py-1.5 text-[13px] font-bold transition-colors duration-300 ${
                    active ? "" : "text-ink/80 hover:text-ink"
                  }`}
                  style={{ color: active ? "#FFFDF7" : undefined, transitionTimingFunction: "var(--ease-glide)" }}
                >
                  <span>{c.label}</span>
                  <span
                    className={`text-[11px] font-mono font-bold tabular-nums ${
                      !pendingAccent && !active ? "opacity-90" : ""
                    }`}
                    style={
                      pendingAccent && active
                        ? { color: "var(--color-wheat)" }
                        : pendingAccent
                        ? { color: "var(--color-copper)" }
                        : active
                        ? { color: "var(--color-parchment)" }
                        : undefined
                    }
                  >
                    {n}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* ========== 列表 / 空态 ========== */}
        {shown.length === 0 ? (
          <EmptyState tab={tab} />
        ) : (
          <ul className="space-y-4">
            {shown.map((m) => (
                <li
                  key={m.id}
                  onClick={() => openDetail(m)}
                  className="animate-float-up cursor-pointer rounded-[1.5rem] p-1.5 ring-1 ring-ink/5 transition-shadow duration-300 hover:ring-copper/40"
                  style={{
                    backgroundColor: "var(--color-mist)",
                    boxShadow: "var(--shadow-float-sm)",
                  }}
                >
                  <div
                    className="rounded-[calc(1.5rem-0.375rem)] px-4 py-4"
                    style={{
                      backgroundColor: "var(--color-parchment)",
                      boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)",
                    }}
                  >
                    {/* 顶部：来源徽章 + （若是时效事件，右上角到期日） */}
                    <div className="flex items-start justify-between gap-3">
                      <SourceBadge source={m.source} />
                      {m.cat === "event" && (
                        <span
                          className="shrink-0 rounded-full px-3 py-1 text-[11px] font-bold"
                          style={{
                            backgroundColor: "rgba(98,117,122,0.10)",
                            color: "var(--color-copper-dk)",
                          }}
                        >
                          时效事件
                        </span>
                      )}
                    </div>

                    {/* D88：外面纯展示——管理（改/忘/换档/升格）全进弹窗做 */}
                    <p className="mt-3 font-heading text-[15px] leading-[1.9] text-ink">
                      {m.text}
                    </p>

                    {/* meta / 到期日 */}
                    {m.meta && <MetaLine meta={m.meta} />}
                  </div>
                </li>
            ))}
          </ul>
        )}

        {/* ========== D88 管理弹窗：点卡进门，窗内管一切（改/忘/换档/升格） ========== */}
        {detail && (() => {
          const m = mems.find((x) => x.id === detail);
          if (!m) return null;   // 行没了（删掉/升格搬家换页签）→ 窗随账灭
          const isFact = m.id.startsWith("m");
          const label = m.cat === "kp" ? "知识点进度" : m.cat === "error" ? "错题账（只读）"
            : m.cat === "event" ? "时效事件（只读）" : m.pf ? "考试档案"
            : m.cat === "pending" ? "待确认的推测" : "记忆事实";
          const pf = m.pf;   // const 收窄：闭包里也认（属性收窄进回调会失效，TS18048 实锤）
          return (
            <div className="fixed inset-0 z-50 grid place-items-center p-4"
                 style={{ backgroundColor: "rgba(28,35,41,0.40)" }}
                 onMouseDown={closeDetail}>
              <div className="w-full max-w-lg rounded-[1.5rem] p-1.5 ring-1 ring-ink/10 animate-float-up"
                   style={{ backgroundColor: "var(--color-mist)", boxShadow: "var(--shadow-float-sm)" }}
                   onMouseDown={(e) => e.stopPropagation()}
                   onKeyDown={(e) => { if (e.key === "Escape") closeDetail(); }}>
                <div className="rounded-[calc(1.5rem-0.375rem)] px-5 py-5"
                     style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)" }}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <SourceBadge source={m.source} />
                      <span className="text-[11px] font-bold tracking-[0.2em] text-ink/50">{label}</span>
                    </div>
                    <button type="button" onClick={closeDetail} aria-label="关闭"
                            className="grid size-7 place-items-center rounded-full text-[13px] text-ink/50 transition-colors hover:bg-ink/5 hover:text-ink">✕</button>
                  </div>

                  {/* 窗内编辑：事实一个 textarea；档案名字+日期两框（容器级 onBlur 整对落账，
                      D87 家法——框间跳焦不误发）；其余行只读 */}
                  {isFact ? (
                    <textarea autoFocus
                              rows={Math.max(2, draft.split("\n").length)}
                              value={draft}
                              onChange={(e) => setDraft(e.target.value)}
                              onBlur={() => void editFact(m.id)}
                              className="mt-4 w-full resize-none rounded-[0.75rem] px-3 py-2 font-heading text-[15px] leading-[1.9] text-ink outline-none ring-1 ring-copper/40"
                              style={{ backgroundColor: "var(--color-cream)" }} />
                  ) : m.pf ? (
                    <div className="mt-4 flex flex-wrap items-center gap-2"
                         onBlur={() => void savePf(m.id)}>
                      <input type="text" autoFocus value={draftPf.name} placeholder="考试名字"
                             onChange={(e) => setDraftPf((p) => ({ ...p, name: e.target.value }))}
                             className="min-w-0 flex-1 rounded-[0.75rem] px-3 py-2 font-heading text-[15px] leading-[1.9] text-ink outline-none ring-1 ring-copper/40"
                             style={{ backgroundColor: "var(--color-cream)" }} />
                      <input type="date" value={draftPf.date}
                             onChange={(e) => setDraftPf((p) => ({ ...p, date: e.target.value }))}
                             className="rounded-[0.75rem] px-3 py-2 font-heading text-[13px] text-ink outline-none ring-1 ring-copper/40"
                             style={{ backgroundColor: "var(--color-cream)" }} />
                    </div>
                  ) : (
                    <p className="mt-4 font-heading text-[15px] leading-[1.9] text-ink">{m.text}</p>
                  )}

                  {m.meta && <MetaLine meta={m.meta} />}

                  {/* D85 档位药丸搬进窗内：kp 行按 ms 票逐条画五档，点档即落账 */}
                  {m.cat === "kp" && m.ms && m.ms.length > 0 && (
                    <div className="mt-4 space-y-2.5">
                      {m.ms.map((x) => (
                        <div key={x.mid} className="flex flex-wrap items-center gap-1.5">
                          <span className="mr-1 text-[11px] font-bold tracking-wide text-ink/55">{x.exam}</span>
                          {LEVELS.map((l) => {
                            const on = l === x.level;
                            return (
                              <button key={l} type="button" disabled={on}
                                      onClick={() => void setLevel(x.mid, l)}
                                      className="rounded-full px-3 py-1 text-[11px] font-bold transition-all duration-300 active:scale-[0.97]"
                                      style={on
                                        ? { backgroundColor: "var(--color-copper)", color: "#FFFDF7", boxShadow: "var(--shadow-copper)" }
                                        : { border: "1px solid rgba(28,35,41,0.15)", color: "rgba(28,35,41,0.6)" }}>
                                {l}
                              </button>
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="mt-5 flex flex-wrap items-center gap-3">
                    {/* pending：一键升格/一键拒绝（删的是未认领猜测，不武装——D86 语义分家） */}
                    {m.cat === "pending" && (<>
                      <button type="button" onClick={() => confirm(m.id)}
                              className="inline-flex items-center rounded-full px-5 py-2.5 text-[13px] font-bold transition-all duration-300 active:scale-[0.98]"
                              style={{ backgroundColor: "var(--color-copper)", color: "#FFFDF7", boxShadow: "var(--shadow-copper)" }}>✓ 确认记住</button>
                      <button type="button" onClick={() => reject(m.id)}
                              className="inline-flex items-center rounded-full border px-5 py-2.5 text-[13px] font-semibold"
                              style={{ borderColor: "rgba(28,35,41,0.18)", color: "rgba(28,35,41,0.65)" }}>✕ 猜错了，删掉</button>
                    </>)}
                    {/* 正式事实遗忘：两步确认（D84 家法）——一键武装、二击落刀、blur 解除 */}
                    {isFact && m.cat === "profile" && (
                      <button type="button" onClick={() => forgetFact(m.id)}
                              onBlur={() => setArmed(false)}
                              className="inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-[12px] font-bold transition-all duration-300"
                              style={armed
                                ? { backgroundColor: "var(--color-rust)", borderColor: "var(--color-rust)", color: "#FFFDF7" }
                                : { borderColor: "rgba(28,35,41,0.18)", color: "rgba(28,35,41,0.65)" }}>
                        {armed ? "确认遗忘？物理删除不可逆" : "✕ 忘了这条"}</button>
                    )}
                    {/* D88 档案删除腿：DELETE 真删行；删主考时库内自动晋主 */}
                    {pf && (
                      <button type="button" onClick={() => forgetProfile(pf.pid)}
                              onBlur={() => setArmed(false)}
                              className="inline-flex items-center gap-1.5 rounded-full border px-4 py-2 text-[12px] font-bold transition-all duration-300"
                              style={armed
                                ? { backgroundColor: "var(--color-rust)", borderColor: "var(--color-rust)", color: "#FFFDF7" }
                                : { borderColor: "rgba(28,35,41,0.18)", color: "rgba(28,35,41,0.65)" }}>
                        {armed ? "确认删除？主考会自动晋给剩下的档案" : "🗑 删除这份档案"}</button>
                    )}
                    {(m.cat === "error" || m.cat === "event" || m.cat === "kp") && (
                      <p className="text-[12px] font-semibold text-ink/55">
                        {m.cat === "kp" ? "档位可点换；节点本身不设删口——要动这本账，聊天里跟教练说。"
                         : m.cat === "error" ? "错题账是出题证据，窗内只读——销案或纠正，聊天里跟教练说。"
                         : "时效事件到期自动消失（BR-03）——要提前处理，聊天里跟教练说。"}</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })()}

        {/* ========== 规则胶囊 Tags（BR-02 / BR-03 / BR-07） ========== */}
        <div className="mt-10">
          <p className="mb-3 text-[11px] font-bold tracking-[0.2em] text-ink/65">
            规则在此页生效
          </p>
          <div className="flex flex-wrap gap-2">
            {[
              "BR-02 · 推测内容必须经你确认才正式入库",
              "BR-03 · 时效事件到期自动消失，不会赖着不走",
              "BR-07 · 遗忘 / 删除类指令任何情况都立即执行",
            ].map((t) => (
              <span
                key={t}
                className="rounded-full px-3.5 py-1.5 text-[12px] font-semibold"
                style={{
                  backgroundColor: "var(--color-mist)",
                  color: "rgba(28,35,41,0.82)",
                }}
              >
                {t}
              </span>
            ))}
          </div>
          <p className="mt-4 text-[12px] font-semibold text-ink/60">
            点任何一张卡片进门管理：事实可改可忘、档案可改名字/日期（日期挪了会提醒您找教练重排计划）可删除、
            待确认可升格可拒绝、知识点进度点档即换——F-13：页面编辑与聊天指令等效落库。
            错题账与事件进门只读——那两本账的写闸门在教练那里。
          </p>
        </div>
      </div>
    </section>
  );
}
