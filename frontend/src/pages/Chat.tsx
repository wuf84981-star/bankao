/* ============================================================
 * 对话页 v2 · 默认落地页
 * 教练气泡：Double-Bezel 羊皮纸 + 左下缺角
 * 用户气泡：沉铜绿渐变药丸 + 右下缺角
 * 消息入场：float-up 只给本次新出现的消息（六刀起历史行零动画——秒出）
 * 会话懒加载（六刀）：进线只拉最近 6 轮，滚到顶续拉更早一页，到头提示「没有更早消息」
 * 开场：2~3 张快捷建议卡（可点击自动发送）
 * 底部：浮动药丸输入岛（四入口：图片 / 语音 / 新会话 / 发送）
 * 思考态：三点相位差波浪动画
 * Toast：顶部中央药丸反馈（图片 / 语音 / 新会话）
 * A：桌面 md+ 左侧 260px 会话侧栏（配额卡 + 真会话列表：新建/点入/删除——S7 五刀 F-08）
 * B：Onboarding 首会话 6 步引导卡（身份→考试→基础→时间→资料→取舍）+ 进度环
 * ============================================================ */

import { useEffect, useRef, useState, type ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import { api, apiChatImage, apiDelete, apiStream } from "../auth";

/* 引用小票（S3 引用刀）：本轮 search_materials 捞回的块出处——
   结构化账由后端记账随响应/回显下发，不靠解析教练正文里的 [N] */
type Cit = { chunk_id: number; material_id: number; title: string; seq: number; ref?: number };
/* id：库里行有真 id（稳定 key+翻页游标）；本次新发/新回的话只有负数临时 id */
type Msg = { id?: number; role: "coach" | "me"; text: string; citations?: Cit[]; photo?: boolean };
type ToastState = { id: number; text: string; kind: "ok" | "warn" | "err"; closing?: boolean } | null;

/* 六刀（用户真机反馈「切会话等太久」→ 豆包式懒加载）：进线只拉最近 6 轮，
   一轮=user+教练各一条 → 一页 12 条消息；滚到顶再往回续一页 */
const PAGE_MSGS = 12;
/* history 接口的行形状（后端六刀起带 id/has_more） */
type HistRow = { id: number; role: string; text: string; citations?: Cit[] | null };

/* 会话侧栏旧道具（S1 时代的 6 条假会话 Mock 与假开场白）已于 2026-09-09 拆除——
   假账比没账伤信任；同日五刀（F-08）换上真列表：账从 GET /api/conversations 来，
   新建/点入/删除每一步都落在服务器真账上。 */

/* 会话行（侧栏）：后端吐本户全部线（web+QQ），时间倒序；preview=该线最后一条用户消息。
   D56 甲：QQ 线上架——带徽标、点进去只读可删（用户拍「记着却看不见」的洞） */
type Conv = { id: number; title: string; channel: string; last_at: string | null; preview: string };

/** 侧栏时间的人话：今天=时:分，昨天=「昨天」，本年=月日，跨年=年-月 */
function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const now = new Date();
  const day0 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (d >= day0) return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d >= new Date(day0.getTime() - 864e5)) return "昨天";
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月`;
}

const QUICK_SUGGESTIONS = [
  { icon: "plan", text: "今天学什么" },
  { icon: "err",  text: "过一下昨天的错题" },
  { icon: "mock", text: "来一份模考" },
] as const;

/** 顶部中央 Toast 药丸：入场 fly-in，2.5s 后 fly-out。 */
function Toast({ t }: { t: NonNullable<ToastState> }): ReactElement {
  const bg = t.kind === "ok" ? "var(--color-copper)" : t.kind === "warn" ? "rgba(28,35,41,0.88)" : "var(--color-rust)";
  return (
    <div
      className={`pointer-events-none fixed left-1/2 top-5 z-50 -translate-x-1/2 ${t.closing ? "animate-toast-out" : "animate-toast-in"}`}
    >
      <div
        className="rounded-full px-5 py-2.5 text-[13px] font-semibold shadow-lg"
        style={{ backgroundColor: bg, color: "#FFFDF7", boxShadow: "0 10px 30px rgba(28,35,41,0.22)" }}
      >
        <span className="tabular-nums tracking-wide">{t.text}</span>
      </div>
    </div>
  );
}

/** 教练头像：细边铜绿圆 + 衬线考字徽 */
function CoachAvatar(): ReactElement {
  return (
    <span
      className="grid size-10 shrink-0 place-items-center rounded-full ring-1"
      style={{ backgroundColor: "var(--color-cream)", border: "1.5px solid var(--color-copper)", boxShadow: "var(--shadow-float-sm)" }}
    >
      <span
        className="font-display text-[16px] font-bold"
        style={{ color: "var(--color-copper)" }}
      >考</span>
    </span>
  );
}

/** 快捷建议卡图标：细线 SVG 手写 1.6px */
function QuickIcon({ name }: { name: string }): ReactElement {
  const sw = 1.6;
  const common = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", strokeWidth: sw, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (name) {
    case "plan":
      return (<svg {...common} stroke="currentColor"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M8 2v4M16 2v4M3 10h18"/><path d="m9 15 2 2 4-4"/></svg>);
    case "err":
      return (<svg {...common} stroke="currentColor"><path d="M12 9v4M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>);
    case "mock":
      return (<svg {...common} stroke="currentColor"><path d="M7 3h10l4 4v14H3V3h4Z"/><path d="M17 3v4h4"/><path d="m9 15 2 2 4-4"/></svg>);
    default:
      return (<svg {...common}><circle cx="12" cy="12" r="3" stroke="currentColor"/></svg>);
  }
}

/** 浮动工具按钮图标：1.6~2px stroke */
function Icon({ n, size = 16 }: { n: string; size?: number }): ReactElement {
  const p = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  switch (n) {
    case "image": return (<svg {...p} stroke="currentColor"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>);
    case "mic":   return (<svg {...p} stroke="currentColor"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/></svg>);
    case "reset": return (<svg {...p} stroke="currentColor"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>);
    case "send":  return (<svg {...p} stroke="currentColor"><path d="M22 2 11 13"/><path d="m22 2-7 20-4-9-9-4 20-7Z"/></svg>);
    case "globe": return (<svg {...p} stroke="currentColor"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c-3.6 3.1-5.4 6.1-5.4 9s1.8 5.9 5.4 9c3.6-3.1 5.4-6.1 5.4-9s-1.8-5.9-5.4-9Z"/></svg>);
    case "chip":  return (<svg {...p} stroke="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>);
    case "chevron": return (<svg {...p} stroke="currentColor"><path d="m6 9 6 6 6-6"/></svg>);
    default:      return (<svg {...p} stroke="currentColor"><circle cx="12" cy="12" r="9"/></svg>);
  }
}

/* ============================================================
 * D67 二刀 · 在飞流（fly）——模块级独苗
 * 案底（2026-09-12 断线案）：流式中教练的字只活在组件记忆里——切页卸载
 * 记忆即蒸发，切回来账未落库，整对在眼前失踪。现在改由模块级 fly 存
 * 在飞轮的实况：fetch 闭包写 fly 不管组件死活，任何在场实例都是观众，
 * 挂载就续播；收尾/断轮由在场实例统一「着陆」（内容以服务器账为准）。
 * 刷新仍救不了字面（浏览器重启一切）——那半截由后端一刀兜底：
 * 用户行进门先落库、教练行跑完照落，账永远比屏幕诚实。
 * ============================================================ */
type Fly = {
  convId: number | null;          // 发起时所在线（新线=null，done 帧回填）
  acc: string;                    // 教练至今打出的全字
  thinking: boolean;              // 首字还没落地=「正在翻计划」
  done: boolean;                  // 流已终（成功或报错），等在场实例着陆
  result?: { notice?: string | null; conv_id?: number };  // done 尾包
  err?: string;                   // 报错人话（整句直接上气泡）
};
let fly: Fly | null = null;
const flyWatchers = new Set<() => void>();
function flyChanged(): void { for (const f of [...flyWatchers]) f(); }

/* ============================================================
 * 主组件 Chat
 * ============================================================ */
export default function Chat(): ReactElement {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [toast, setToast] = useState<ToastState>(null);
  /* 甲案·引用小票溯源（真机反馈「第几块，哪里的第几块」）：点票展开那块原文。
     全局独苗——同时只展开一张；懒取：点开才打 GET /api/chunks/{id}，缓存进 state */
  const [citOpen, setCitOpen] = useState<{ key: string; title?: string; seq?: number;
    content?: string; err?: string } | null>(null);
  const [apologizeOpen, setApologizeOpen] = useState(false);
  /* B. Onboarding 引导（S1 道具屏：入口已拆、永不可达——真首登引导归 S8 照聊天链重做） */
  const [isFirstSession, setIsFirstSession] = useState(false);
  const [onboardingStep, setOnboardingStep] = useState<1|2|3|4|5|6>(1);
  const endRef = useRef<HTMLDivElement>(null);
  const toastIdRef = useRef(0);
  /* 拍照汇报（S7 四刀 · F-09）：发送前最多攥一张图——后端端点一次一图，
     「≤4 张/24h」的闸在 image_turn 统一执法（QQ 腿同口），前端不设第二本账 */
  const fileRef = useRef<HTMLInputElement>(null);
  const [pendingImg, setPendingImg] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!pendingImg) { setPreviewUrl(null); return; }
    const u = URL.createObjectURL(pendingImg);
    setPreviewUrl(u);
    return () => URL.revokeObjectURL(u);   // 换图/卸载即回收，不漏 object URL
  }, [pendingImg]);

  /* 联网兜底开关（S8 · D58 甲）：账在本户 agent_settings，默认关。
     开=讲义零命中时后端才准调 Tavily 查网络；关=web_search 不进模型工具箱。
     开关随户不随会话——网页和 QQ 两条线共用同一本账（装配点在 tools_for）。 */
  const [webOn, setWebOn] = useState(false);
  useEffect(() => {
    api("/api/settings/websearch")
      .then((d) => setWebOn(Boolean((d as { enabled?: boolean }).enabled)))
      .catch(() => {});   // 读失败维持默认关——宁可少联网，不可假开灯
  }, []);
  const toggleWeb = () => {
    const next = !webOn;
    api("/api/settings/websearch", { enabled: next })
      .then(() => setWebOn(next))
      .catch((e) => showToast(e instanceof Error ? e.message : "开关没落账，重试一下", "err"));
  };

  /* 模型切换（S8 · D60 甲）：花名册和可用性都听后端 GET /api/settings/model——
     前端不抄第二份名单（真源在 llm.py 一处）。没钥匙的平台灰显，配好 key 重建容器自动点亮。
     OCR/向量点火等专用腿不随此切换，换的只是"跟你对话的脑子"。 */
  type ModelRow = { id: string; platform: string; available: boolean; multiplier?: number; byo?: boolean };
  const [modelRows, setModelRows] = useState<ModelRow[]>([]);
  const [curModel, setCurModel] = useState("");
  const [modelMenu, setModelMenu] = useState(false);
  useEffect(() => {
    api("/api/settings/model")
      .then((d) => {
        const r = d as { current?: string; models?: ModelRow[] };
        setCurModel(r.current ?? "");
        setModelRows(r.models ?? []);
      })
      .catch(() => {});   // 读失败只是菜单空，不打扰当前对话
  }, []);
  const pickModel = (m: ModelRow) => {
    setModelMenu(false);
    if (!m.available || m.id === curModel) return;
    api("/api/settings/model", { model: m.id })
      .then(() => { setCurModel(m.id); showToast(`已切换：下次开口就用 ${m.id}`, "ok"); })
      .catch((e) => showToast(e instanceof Error ? e.message : "选模没落账，重试一下", "err"));
  };

  /* 会话列表（S7 五刀 · F-08）：activeConv=null 表示"随后端最近线"——
     与挂页初始、后端无行自动开线三个场景同形，前端不设第二本账。 */
  const [convs, setConvs] = useState<Conv[]>([]);
  const [activeConv, setActiveConv] = useState<number | null>(null);
  /* D67 二刀：线号的镜像 ref——landFly 隔着 fetch await 摸当下实况，防闭包攥旧值 */
  const activeConvRef = useRef<number | null>(null);
  useEffect(() => { activeConvRef.current = activeConv; }, [activeConv]);
  /* 挂载即当 fly 的观众：字逐帧续播靠 bump；fly 终了没人着陆就一直悬着，
     下一次挂载（或下一次 flyChanged）由在场实例补着陆，账不流浪 */
  const [, flyBump] = useState(0);
  const landingRef = useRef(false);
  useEffect(() => {
    const w = () => {
      flyBump((n) => n + 1);
      if (fly?.done && !landingRef.current) {
        landingRef.current = true;
        void landFly(fly).finally(() => { landingRef.current = false; });
      }
    };
    flyWatchers.add(w);
    return () => { flyWatchers.delete(w); };
  }, []);
  /* 六刀懒加载家当：游标分页三态 + 视口钉位 + 动画白名单 + 临时 id */
  const chatRef = useRef<HTMLElement>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const restoreRef = useRef<{ h: number; t: number } | null>(null);
  // 换线整屏=同步硬跳到底（smooth 会被浏览器滚动锚定半路抵消，停在历史位）
  const jumpBottomRef = useRef(false);
  const seenIds = useRef<Set<number>>(new Set());   // 已露过面的消息不再演入场动画
  const tempIdRef = useRef(0);                      // 本次会话新话的负数临时 id（不与库撞）
  /** 历史行→气泡：登记进 seenIds，整批静默显形（秒出的关键） */
  const toMsg = (r: HistRow): Msg => {
    seenIds.current.add(r.id);
    return {
      id: r.id,
      role: (r.role === "assistant" ? "coach" : "me") as Msg["role"],
      text: r.text,
      citations: r.citations ?? undefined,
    };
  };
  function refreshConvs(): void {
    void (async () => {
      try {
        const c = (await api("/api/conversations")) as { conversations: Conv[] };
        setConvs(c.conversations);
      } catch { /* 列表拉不到不拦聊天，侧栏保持旧影 */ }
    })();
  }

  /* 滚动策略（六刀并一只效果，防两个 effect 抢方向盘）：
     往列表上方插旧消息时——视口钉在原来看着的位置（高度差补偿），不跳底；
     换线整屏（挂页/openConv 换账）——同步硬跳到底，不走 smooth（七刀续刀）；
     其余情况（新发言/流式出字/思考态变化）——照旧滚到底。 */
  useEffect(() => {
    const el = chatRef.current;
    if (restoreRef.current && el) {
      const { h, t } = restoreRef.current;
      restoreRef.current = null;
      el.scrollTop = el.scrollHeight - h + t;
      return;
    }
    if (jumpBottomRef.current && el) {
      jumpBottomRef.current = false;
      el.scrollTop = el.scrollHeight;   // 同步赋值：不给滚动锚定留反制窗口
      requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });  // Markdown 排版稳定后补瞄
      return;
    }
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, thinking]);

  /* D64 积分钱包（替换旧「今日额度」卡）：余额/今日已耗/签到态全听 GET /api/points——
     数以库为准、前端不做算术：每发完一句话整包重拉（Admin 八刀同款纪律，零第二真源）。 */
  type Wallet = { balance: number; todaySpent: number; streak: number;
                  checkedIn: boolean; warn: boolean };
  const [wallet, setWallet] = useState<Wallet | null>(null);
  async function refreshWallet(): Promise<void> {
    try {
      const w = (await api("/api/points")) as
        { balance: number; today_spent: number; streak: number;
          checked_in_today: boolean; warn: boolean };
      setWallet({ balance: w.balance, todaySpent: w.today_spent, streak: w.streak,
                  checkedIn: w.checked_in_today, warn: w.warn });
    } catch {
      /* 拉不到钱包不拦聊天，卡片保持"…"占位 */
    }
  }
  useEffect(() => { void refreshWallet(); }, []);
  /* 签端：POST /api/checkin——幂等闸在后端（连点两次也只领一份），409 的 detail 直接上 toast */
  const [checking, setChecking] = useState(false);
  function doCheckin(): void {
    if (checking || wallet?.checkedIn) return;
    setChecking(true);
    void (async () => {
      try {
        const r = (await api("/api/checkin", {})) as { granted: number; streak: number };
        showToast(`签到成功：+${r.granted} 分，连签 ${r.streak} 天`, "ok");
      } catch (e) {
        showToast(e instanceof Error ? e.message : "签到没落账，重试一下", "err");
      } finally {
        setChecking(false);
        void refreshWallet();
      }
    })();
  }

  /* 挂页回显（S3 插曲）：拉最近会话的消息顶上屏——修"刷新丢对话"。
     五刀顺带：同一次挂页把侧栏真列表也拉起来（两条 GET 互不依赖，各静默各的）。
     六刀改懒加载：只拉最近一页（12 条），更早的滚到顶再续。
     有历史就别让道具开场白占位；拉不到不拦聊天，安静用开场白。 */
  useEffect(() => {
    refreshConvs();
    void (async () => {
      try {
        const h = (await api(`/api/history?limit=${PAGE_MSGS}`)) as
          { messages: HistRow[]; has_more?: boolean; conv_id?: number | null };
        // 七刀：后端告诉我们落在了哪条线，回填线号——之后发送就落在这条显示中的线，不串道
        if (h.conv_id != null) setActiveConv(h.conv_id);
        if (h.messages.length) {
          jumpBottomRef.current = true;   // 挂页进线=整屏换账，硬跳到底
          setMessages(h.messages.map(toMsg));
          setHasMore(h.has_more ?? true);
        }
      } catch { /* 静默 */ }
    })();
  }, []);

  /** 滚到顶续拉更早一页（六刀）：游标=当前首条的库 id（负数临时 id 不配当游标）。
   *  失败不关 has_more 的门（网络一抽不该把旧账判成没有），下次上滚自会再试。 */
  function loadMore(): void {
    const el = chatRef.current;
    const first = messages[0];
    if (loadingOlder || !hasMore || !el || !first || first.id === undefined || first.id < 0) return;
    setLoadingOlder(true);
    restoreRef.current = { h: el.scrollHeight, t: el.scrollTop };   // 插页前记位，插完钉回
    void (async () => {
      try {
        const q = `/api/history?limit=${PAGE_MSGS}&before_id=${first.id}` +
          (activeConv != null ? `&conv_id=${activeConv}` : "");
        const h = (await api(q)) as { messages: HistRow[]; has_more?: boolean };
        setMessages((old) => [...h.messages.map(toMsg), ...old]);
        setHasMore(h.has_more ?? false);
      } catch {
        restoreRef.current = null;   // 没插进东西，别拿空页的高度差去挪视口
      } finally {
        setLoadingOlder(false);
      }
    })();
  }

  /** Toast 显示：2.5s 后自动加 closing，再 400ms 清 state */
  function showToast(text: string, kind: NonNullable<ToastState>["kind"] = "ok"): void {
    const id = ++toastIdRef.current;
    setToast({ id, text, kind });
    setTimeout(() => {
      setToast((cur) => (cur && cur.id === id ? { ...cur, closing: true } : cur));
      setTimeout(() => { setToast((cur) => (cur && cur.id === id ? null : cur)); }, 400);
    }, 2500);
  }

  /** 真发送（第四刀·流式，D67 二刀改账）：教练在飞的整句写进模块级 fly，
   *  不再住组件记忆——切页再回来续播；收尾由在场实例 landFly 统一着陆，数听服务器。
   *  单飞规矩：fly 在飞时任何线都不发第二句（防双流串尾）——「查资料这事不该演给用户看」
   *  的静默期由心跳与大门 300s 耐心保线（2026-09-12 三件套），在飞时请等它落地。 */
  async function sendText(text: string): Promise<void> {
    if (fly) return;
    const mid = --tempIdRef.current;      // 负数临时 id：动画白名单与稳定 key 都用它
    setMessages((m) => [...m, { id: mid, role: "me", text }]);
    setDraft("");
    fly = { convId: activeConv, acc: "", thinking: true, done: false };
    flyChanged();
    try {
      /* 相对地址"隔壁房间"不变：vite 代理/Nginx 大门转发照旧；apiStream 揣票验 ok。
         conv_id=null 时不带上（undefined 被 JSON 丢弃）——后端自动随后端最近线 */
      const done = await apiStream("/api/chat/stream",
        { message: text, conv_id: activeConv ?? undefined }, (piece) => {
        if (!fly) return;               // 已着陆后的迟到帧：没人认领，丢
        fly.thinking = false;           // 头一个字落地，"正在翻计划"的点点就收
        fly.acc += piece;
        flyChanged();
      });
      if (fly) { fly.result = done; fly.thinking = false; fly.done = true; }
    } catch (err) {
      /* TypeError=网络断（电厂停/大门掐/代理坏）；Error=后端有理有据的拒绝（401/429…）或流中 error 帧 */
      if (fly) {
        fly.thinking = false;
        fly.err = err instanceof TypeError
          ? "（连不上后端——8000 端口的电厂停着吗？）"
          : `（后端回话：${err instanceof Error ? err.message : String(err)}）`;
        fly.done = true;
      }
    }
    flyChanged();   // 终字/断流都要敲钟：唤醒在场实例着陆
  }

  /** 在飞流着陆（D67 二刀）：fly 终了且本屏还认得这条线——整屏以服务器账重拉
   *  （成功轮教练行已流尾落库、引用小票随账回来；报错轮补半句+人话气泡）；
   *  用户中途已切线则安静退役不抢屏——账在库里，切回去自然见全文。 */
  async function landFly(f: Fly): Promise<void> {
    const done = f.result;
    let pin = done?.conv_id ?? f.convId;
    let rows: HistRow[] = [];
    let more = true;
    try {
      const h = (await api(`/api/history?limit=${PAGE_MSGS}` +
                           (pin != null ? `&conv_id=${pin}` : ""))) as
        { messages: HistRow[]; has_more?: boolean; conv_id?: number | null };
      rows = h.messages;
      more = h.has_more ?? true;
      if (pin == null && h.conv_id != null) pin = h.conv_id;   // 首轮开新线：后端报落点
    } catch { /* 账拉不到也退役，别让半截 fly 卡住单飞闸 */ }
    const cur = activeConvRef.current;
    if (cur == null || pin == null || cur === pin) {
      if (pin != null) setActiveConv(pin);
      const tail: Msg[] = rows.map(toMsg);
      if (f.err) {
        // 后端没记账的半句白看——照旧留证再报错（BR-11：没扣钱，看着不心疼）
        if (f.acc) tail.push({ id: --tempIdRef.current, role: "coach", text: f.acc });
        tail.push({ id: --tempIdRef.current, role: "coach", text: f.err });
      }
      if (done?.notice) tail.push({ id: --tempIdRef.current, role: "coach", text: `⚠️ ${done.notice}` });
      setMessages(tail);
      setHasMore(more);
    }
    refreshConvs();
    void refreshWallet();
    fly = null;
    flyChanged();
  }

  /** 发送按钮/回车入口：有字或有图且不在等待中就发；攥着图就走拍照汇报腿。
   *  D67 二刀：fly 在飞也算等待——单飞闸，一条线在飞时全场不发第二句 */
  function send(): void {
    if (thinking || fly !== null) return;
    if (pendingImg) { void sendImage(); return; }
    const text = draft.trim();
    if (!text) return;
    void sendText(text);
  }

  /** 带图真发送（S7 四刀 · F-09）：不走流式——OCR 转写加 brain 循环动辄几十秒，
   *  整包等回话比半截打字体面；apiChatImage 进 /api/chat/image，回话顶进空教练气泡。
   *  张数闸拒收也回 200（saved:false + reply 人话），同一条路上屏，不另开报错支。 */
  async function sendImage(): Promise<void> {
    const file = pendingImg;
    if (!file) return;
    const text = draft.trim();
    const mid = --tempIdRef.current;
    const coachId = --tempIdRef.current;
    setPendingImg(null);
    setDraft("");
    setMessages((m) => [...m,
      { id: mid, role: "me", text: text || "拍照汇报", photo: true },
      { id: coachId, role: "coach", text: "" }]);
    setThinking(true);
    try {
      const done = await apiChatImage(file, text, activeConv);
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = {
          id: coachId, role: "coach", text: done.reply,
          citations: done.citations?.length ? done.citations : undefined,
        };
        return copy;
      });
      void refreshWallet();   // D64：发完重拉钱包（后端尾账已 commit，余额是权威数）
      if (typeof done.conv_id === "number") setActiveConv(done.conv_id);   // 五刀回填
      refreshConvs();
      if (done.notice) setMessages((m) => [...m, { id: --tempIdRef.current, role: "coach", text: `⚠️ ${done.notice}` }]);
    } catch (err) {
      /* TypeError=网络断；Error=后端人话拒绝（413 太大/415 假图/429 配额/502 OCR 故障…） */
      const msg = err instanceof TypeError
        ? "（连不上后端——8000 端口的电厂停着吗？）"
        : `（后端回话：${err instanceof Error ? err.message : String(err)}）`;
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { id: coachId, role: "coach", text: msg };
        return copy;
      });
    } finally {
      setThinking(false);
    }
  }

  /* 旧「切换会话/新会话」两函数曾随假列表同拆（幽灵操作）；五刀（F-08）真做回归——
     三个动作全落服务器真账：POST 开线、GET history 定点加载、DELETE 删展示记录。 */

  /** 新对话：插一行即切新线、清屏等发言——老线原地封存，点列表可回看。
   *  api() 认 body 猜方法：递 {} 就是 POST（后端不读入参，FastAPI 自动忽略） */
  function newSession(): void {
    void (async () => {
      try {
        const r = (await api("/api/conversations", {})) as { id: number };
        setActiveConv(r.id);
        seenIds.current.clear();   // 清屏开新线：动画白名单作废（下批历史全新静默进场）
        setMessages([]);
        setHasMore(true);
        refreshConvs();
      } catch (err) {
        showToast(err instanceof Error ? err.message : "新对话没开成", "err");
      }
    })();
  }

  /** 点入某条线：定点拉该线**最近一页**顶上屏（F-08 流程「点击进入加载」+
   *  六刀懒加载——切换瞬间见 6 轮，更早的往上翻续；整批历史零动画静默显形） */
  function openConv(id: number): void {
    if (id === activeConv) return;
    setActiveConv(id);
    void (async () => {
      try {
        const h = (await api(`/api/history?conv_id=${id}&limit=${PAGE_MSGS}`)) as
          { messages: HistRow[]; has_more?: boolean };
        seenIds.current.clear();   // 换屏清册：新线历史全部登记为"已露面"→不演动画
        jumpBottomRef.current = true;   // 切线整屏换账=硬跳到底（七刀续刀）
        setMessages(h.messages.map(toMsg));
        setHasMore(h.has_more ?? true);
      } catch { /* 拉不到保持现屏，不炸 */ }
    })();
  }

  /** 删一条线（F-08 AC②）：只清展示记录（消息行 CASCADE 跟走），记忆与题目账原样在——
   *  确认文案就说这个，用户不用猜删了什么。删的若是当前线，清屏归"随后端最近线"。 */
  function delConv(id: number): void {
    if (!window.confirm("删除这条对话只清掉聊天展示记录，教练的记忆和你的题目账本都不动。确定删除？")) return;
    void (async () => {
      try {
        await apiDelete(`/api/conversations/${id}`);
        if (id === activeConv) { setActiveConv(null); setMessages([]); }
        refreshConvs();
        showToast("已删除（记忆与题目账都保留）", "ok");
      } catch (err) {
        showToast(err instanceof Error ? err.message : "删除失败", "err");
      }
    })();
  }

  /** 点击快捷建议卡：直接走同一个真发送 */
  function clickSuggestion(text: string): void {
    void sendText(text);
  }

  /* D67 二刀：fly 是这条屏的在飞流就续播——谁发起的不重要，在场即观众 */
  const flyHere = fly !== null && fly.convId === activeConv;
  const showSuggestions = messages.length === 0 && !thinking && !flyHere;

  /* D56 甲：当前线若是 QQ 线 → 本页只读（能看能删,不能替它发言——
   * 网页发送永远落 web 线,串道之防原样;activeConv=null 时随后端缺省线,必是 web,不中 */
  const activeIsQQ = convs.find((c) => c.id === activeConv)?.channel === "qq";
  /* D56 顺带：activeConv=null 时的后端缺省活跃线=第一条 web 线（QQ 线不参与抢高亮） */
  const webTopId = convs.find((c) => c.channel !== "qq")?.id;

  return (
    <div className="flex min-h-0 w-full flex-1 overflow-hidden">
      {toast && <Toast t={toast} />}

      {/* A. 会话侧栏（md+ 桌面显示，260px 宽） */}
      <aside className="hidden md:flex w-[260px] shrink-0 flex-col border-r border-ink/5 px-5 py-8 gap-6">
        {/* A1. 积分 Double-Bezel 小卡（D64 顶替「今日额度」卡——token 硬顶转后端双保险（D66 提至 200 万/日），
            页面上钱的事只讲积分：余额/今日已耗/签到钮；真源 GET /api/points） */}
        <div className="rounded-[1.25rem] p-1 ring-1 ring-wheat" style={{backgroundColor:"var(--color-wheat)"}}>
          <div className="rounded-[calc(1.25rem-0.375rem)] bg-parchment px-4 py-3.5" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.8)"}}>
            <p className="text-[10px] font-bold tracking-[0.2em] text-copper">积分</p>
            <div className="mt-2 flex items-end justify-between">
              <span className={`font-mono text-[20px] font-bold leading-none ${wallet && wallet.warn ? "text-red-700" : "text-ink"}`}>{wallet ? wallet.balance.toLocaleString("en-US") : "…"}</span>
              <span className="text-[11px] font-semibold text-ink/55">今日已耗 {wallet ? wallet.todaySpent : "…"} 分</span>
            </div>
            <button type="button" onClick={doCheckin} disabled={wallet?.checkedIn || checking}
                    className="mt-3 w-full rounded-full px-3 py-1.5 text-[12px] font-bold transition active:scale-[0.98] disabled:cursor-default"
                    style={wallet?.checkedIn
                      ? {backgroundColor:"var(--color-mist)", color:"rgba(28,35,41,0.45)"}
                      : {backgroundColor:"var(--color-copper)", color:"var(--color-parchment)", boxShadow:"var(--shadow-copper)"}}>
              {wallet?.checkedIn ? `✓ 今日已签到 · 连签 ${wallet.streak} 天` : checking ? "领取中…" : "每日签到 +200"}
            </button>
          </div>
        </div>

        {/* A2. 「＋新对话」（F-08 五刀真做）：POST 开线即切新屏——上一刀拆它是因为它假，
            今天它背后有了真账，请回来 */}
        <button type="button" onClick={newSession}
                className="inline-flex items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-[13px] font-bold text-parchment transition active:scale-[0.98]"
                style={{backgroundColor:"var(--color-copper)", boxShadow:"var(--shadow-copper)"}}>
          ＋ 新对话
        </button>

        {/* A3. 会话列表（F-08）：时间倒序、点入加载、悬停出删除叉。
            activeConv=null 时后端投递的活跃线=列表里**第一条 web 线**（D56 后列表混排
            QQ 线，不能再拿 convs[0] 当兜底高亮——后端缺省落线只认 web） */}
        <div className="flex-1 min-h-0 space-y-1.5 overflow-y-auto">
          {convs.length === 0 && (
            <div className="rounded-[0.9rem] px-3 py-2.5"
                 style={{backgroundColor:"color-mix(in srgb, var(--color-copper) 12%, transparent)",
                         boxShadow:"inset 3px 0 0 var(--color-copper)"}}>
              <p className="text-[13px] font-bold" style={{color:"var(--color-copper-dk)"}}>还没有会话</p>
              <p className="mt-1 text-[11px] text-ink/50">说一句，这里就会开出第一条线。</p>
            </div>
          )}
          {convs.map((c) => {
            const active = c.id === activeConv || (activeConv === null && webTopId === c.id);
            return (
              <div key={c.id} role="button" tabIndex={0} onClick={() => openConv(c.id)}
                   onKeyDown={(e) => { if (e.key === "Enter") openConv(c.id); }}
                   className={`group relative cursor-pointer rounded-[0.9rem] px-3 py-2.5 transition ${active ? "" : "hover:bg-ink/5"}`}
                   style={active ? {backgroundColor:"color-mix(in srgb, var(--color-copper) 12%, transparent)",
                                    boxShadow:"inset 3px 0 0 var(--color-copper)"} : undefined}>
                <div className="flex items-baseline justify-between gap-2 pr-6">
                  <p className="truncate text-[13px] font-bold"
                     style={{color: active ? "var(--color-copper-dk)" : "var(--color-ink)"}}>
                    {c.channel === "qq" && (
                      <span className="mr-1.5 inline-block rounded-full px-1.5 py-px align-[1px] text-[9px] font-bold text-white"
                            style={{backgroundColor:"var(--color-ink)"}}>QQ</span>)}
                    {c.title === "新会话" && c.preview ? c.preview.slice(0, 12) : c.title}
                  </p>
                  <span className="shrink-0 text-[10px] font-semibold tabular-nums text-ink/40">{fmtTime(c.last_at)}</span>
                </div>
                {c.preview && <p className="mt-0.5 truncate pr-6 text-[11px] text-ink/50">{c.preview}</p>}
                {/* 删除叉：悬停才现身，免得侧栏看着像一排地雷 */}
                <button type="button" title="删除这条对话（只清展示记录，记忆与题目账保留）"
                        onClick={(e) => { e.stopPropagation(); delConv(c.id); }}
                        className="absolute right-2 top-1/2 hidden size-6 -translate-y-1/2 place-items-center rounded-full text-ink/45 transition hover:text-rust group-hover:grid"
                        style={{backgroundColor:"var(--color-parchment)"}}>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
                </button>
              </div>
            );
          })}
        </div>
      </aside>

      {/* 对话区 wrapper */}
      <div className="flex min-w-0 flex-1 flex-col">
        <section ref={chatRef}
                 onScroll={(e) => { if (e.currentTarget.scrollTop < 60) loadMore(); }}   // 六刀：到顶续页
                 className="flex-1 space-y-6 overflow-y-auto px-5 py-8 md:px-10 md:py-12">
          {/* B. Onboarding 首会话 6 步引导 / 正常对话消息流（二选一） */}
          {isFirstSession ? (
            <div className="mx-auto max-w-[720px] animate-float-up">
              {/* B1. 顶环进度 Double-Bezel 大卡 */}
              <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-6" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                  <div className="flex items-center gap-6">
                    <svg width="72" height="72" viewBox="0 0 48 48">
                      <circle cx="24" cy="24" r="20" fill="none" stroke="var(--color-mist)" strokeWidth="3.5"/>
                      <circle cx="24" cy="24" r="20" fill="none" stroke="var(--color-copper)" strokeWidth="3.5" strokeLinecap="round"
                              strokeDasharray={2 * Math.PI * 20}
                              strokeDashoffset={2 * Math.PI * 20 * (1 - onboardingStep / 6)}
                              style={{transition:"stroke-dashoffset 500ms var(--ease-spring-out)", transform:"rotate(-90deg)", transformOrigin:"center"}}/>
                      <text x="24" y="23" textAnchor="middle" dominantBaseline="middle" fontFamily="var(--font-mono)" fontSize="16" fontWeight="700" fill="var(--color-ink)">{onboardingStep}<tspan fontSize="10" fill="rgba(28,35,41,0.4)">/6</tspan></text>
                    </svg>
                    <div className="flex-1">
                      <p className="text-[11px] font-bold tracking-[0.2em] text-copper">ONBOARDING · 初始见面</p>
                      <h2 className="mt-1 font-display text-[26px] leading-tight text-ink">第一次见面，问你六个问题。</h2>
                      <p className="mt-1 text-[13px] text-ink/60">都可以之后改，凭直觉先选，1 分钟填完。</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* B2. 6 步条件切换容器 */}
              <div className="mt-8 animate-float-up" style={{animationDelay:"100ms"}}>
                {onboardingStep === 1 && (
                  <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                    <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-7" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第一步 · 身份</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">你是哪种备考状态？</h3>
                      <div className="mt-7 flex flex-wrap gap-3">
                        {[
                          {k:"full", label:"全职备考", tag:"风险+时间充裕"},
                          {k:"work", label:"在职备考", tag:"最常见 · 时间紧张", active:true},
                          {k:"fresh", label:"应届生", tag:"时间灵活"},
                          {k:"grad", label:"已毕业在职", tag:"二战/三战常客"},
                        ].map((c)=>(
                          <button key={c.k} className="group rounded-full px-5 py-2.5 text-[14px] font-bold transition-all duration-300"
                                  style={{backgroundColor:c.active?"var(--color-copper)":"var(--color-mist)", color:c.active?"#FFFDF7":"var(--color-ink)", boxShadow:c.active?"var(--shadow-copper)":undefined, transitionTimingFunction:"var(--ease-glide)"}}>
                            <span>{c.label}</span>
                            {c.tag && <span className={`ml-2 text-[10px] font-semibold ${c.active?"text-parchment/80":"text-ink/45"}`}>· {c.tag}</span>}
                          </button>
                        ))}
                      </div>
                      <p className="mt-8 text-[12px] text-ink/50">选了不锁死，之后随时改。在职 = 默认每天可用时间 2h。</p>
                    </div>
                  </div>
                )}

                {onboardingStep === 2 && (
                  <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                    <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-7" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第二步 · 考试</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">你要考的是什么？</h3>
                      <div className="mt-7 grid grid-cols-1 gap-4 md:grid-cols-2">
                        {["考试类型（如：2027国考）","考试日期（如：2027-11-30）"].map((ph, idx)=>(
                          <div key={ph} className="relative">
                            <div className="rounded-[1.25rem] p-1 ring-1 ring-ink/10" style={{backgroundColor:"var(--color-mist)"}}>
                              <div className="rounded-[calc(1.25rem-0.375rem)] bg-parchment px-4 pt-[14px] pb-3">
                                <label className="absolute left-6 top-2 text-[11px] font-bold text-copper pointer-events-none">{ph}</label>
                                <input defaultValue={idx===0?"2027国考":idx===1?"2027-11-30":""} className="w-full bg-transparent pt-1 text-[15px] font-semibold text-ink outline-none"/>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                      <button className="mt-5 inline-flex rounded-full px-4 py-2 text-[12px] font-semibold text-copper ring-1 ring-copper/25 transition hover:bg-copper/5" style={{transitionTimingFunction:"var(--ease-glide)"}}>
                        ⚡ 帮我自动填：国考 2027-11-30（最多人选）
                      </button>
                    </div>
                  </div>
                )}

                {onboardingStep === 3 && (
                  <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                    <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-7" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第三步 · 基础</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">基础怎么样？</h3>
                      <div className="mt-7 grid grid-cols-2 gap-4">
                        {[
                          {k:"zero", label:"零基础", desc:"还没开始看书"},
                          {k:"some", label:"有基础", desc:"看过书/刷过部分题", active:true},
                          {k:"war", label:"二战 / 三战", desc:"有实战经验"},
                          {k:"idk", label:"说不清", desc:"你判断下？"},
                        ].map((c)=>(
                          <div key={c.k} className="relative rounded-[1.25rem] p-1 ring-1 transition-all duration-300"
                               style={{backgroundColor:"var(--color-mist)", border:c.active?"2px solid var(--color-copper)":undefined, transitionTimingFunction:"var(--ease-glide)"}}>
                            <div className="rounded-[calc(1.25rem-0.375rem)] bg-parchment px-5 py-5" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                              {c.active && (
                                <span className="absolute right-3 top-3 grid size-6 place-items-center rounded-full text-parchment" style={{backgroundColor:"var(--color-copper)"}}>
                                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                                </span>
                              )}
                              <p className="font-heading text-[16px] font-bold text-ink">{c.label}</p>
                              <p className="mt-1 text-[12px] text-ink/55">{c.desc}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {onboardingStep === 4 && (
                  <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                    <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-7" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第四步 · 时间</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">每天能投入多少？</h3>
                      <p className="mt-1 text-[13px] text-ink/60">诚实填，排计划时我会按这个节奏来，绝不强行塞内容。</p>
                      <div className="mt-7 grid grid-cols-1 gap-4 md:grid-cols-3">
                        {[["工作日每天几小时？","2 小时"],["周末每天几小时？","4 小时"],["偏好学习时段？","19:30 左右"]].map(([ph, def])=>(
                          <div key={ph} className="relative">
                            <div className="rounded-[1.25rem] p-1 ring-1 ring-ink/10" style={{backgroundColor:"var(--color-mist)"}}>
                              <div className="rounded-[calc(1.25rem-0.375rem)] bg-parchment px-4 pt-[14px] pb-3">
                                <label className="absolute left-6 top-2 text-[11px] font-bold text-copper pointer-events-none">{ph}</label>
                                <input defaultValue={def} className="w-full bg-transparent pt-1 text-[15px] font-semibold text-ink outline-none"/>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {onboardingStep === 5 && (
                  <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                    <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-7" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第五步 · 资料</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">手头有备考资料吗？</h3>
                      <div className="mt-7 grid grid-cols-1 gap-4 md:grid-cols-2">
                        <div className="rounded-[1.25rem] p-1 ring-2 transition-all duration-300" style={{borderColor:"var(--color-copper)", transitionTimingFunction:"var(--ease-glide)"}}>
                          <div className="rounded-[calc(1.25rem-0.375rem)] px-5 py-6" style={{backgroundColor:"var(--color-wheat)"}}>
                            <p className="font-heading text-[18px] font-bold text-ink">有，我带了讲义和真题</p>
                            <p className="mt-1 text-[12px] text-ink/65">上传后我自动拆科目/章节/知识点，按你的资料排计划。</p>
                            <button className="mt-5 inline-flex rounded-full px-4 py-2 text-[12px] font-bold text-parchment" style={{backgroundColor:"var(--color-copper)"}}>
                              📎 切到「资料」页上传
                            </button>
                          </div>
                        </div>
                        <div className="rounded-[1.25rem] p-1 ring-1 ring-ink/10 transition-all duration-300" style={{transitionTimingFunction:"var(--ease-glide)"}}>
                          <div className="rounded-[calc(1.25rem-0.375rem)] bg-parchment px-5 py-6" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.7)"}}>
                            <p className="font-heading text-[18px] font-bold text-ink">暂时没有，先用考纲排</p>
                            <p className="mt-1 text-[12px] text-ink/55">我按国考/考研通用考纲生成占位计划，资料到了再一键重排。</p>
                            <p className="mt-5 text-[12px] font-semibold text-copper">✓ 演示：选这一步，直接生成计划。</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {onboardingStep === 6 && (
                  <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{backgroundColor:"var(--color-mist)"}}>
                    <div className="rounded-[calc(1.75rem-0.375rem)] bg-parchment px-7 py-7" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第六步 · 取舍</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">模块优先级，点击切换档位</h3>
                      <p className="mt-1 text-[13px] text-ink/60">高 = 优先给时间；中 = 正常排；低 = 时间不够先砍。</p>
                      <div className="mt-7 space-y-3">
                        {[
                          {m:"行测 · 资料分析", lvl:"high"},
                          {m:"行测 · 言语理解", lvl:"mid"},
                          {m:"行测 · 判断推理", lvl:"high"},
                          {m:"行测 · 数量关系", lvl:"low"},
                          {m:"行测 · 常识判断", lvl:"low"},
                          {m:"申论", lvl:"mid"},
                        ].map((row)=>(
                          <div key={row.m} className="grid grid-cols-[1fr_auto] items-center gap-4 rounded-[1rem] px-4 py-3" style={{backgroundColor:"var(--color-mist)"}}>
                            <span className="font-heading text-[14px] font-semibold text-ink">{row.m}</span>
                            <div className="inline-flex gap-1 rounded-full p-1" style={{backgroundColor:"var(--color-parchment)"}}>
                              {[["低","low","rgba(168,84,62,0.85)"],["中","mid","rgba(28,35,41,0.78)"],["高","high","var(--color-copper)"]].map(([label,key,bg])=>(
                                <span key={key} className="rounded-full px-3.5 py-1.5 text-[12px] font-bold text-parchment"
                                      style={{backgroundColor: row.lvl===key ? bg : "transparent", color: row.lvl===key ? "#FFFDF7" : "var(--color-ink-soft)"}}>
                                  {label}
                                </span>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* B3. 底部操作栏：上一步 / 下一步 Nested CTA */}
              <div className="mt-10 flex items-center justify-between">
                <button
                  type="button"
                  onClick={()=>setOnboardingStep((s)=>Math.max(1, s-1) as 1|2|3|4|5|6)}
                  disabled={onboardingStep===1}
                  className="inline-flex items-center gap-1.5 rounded-full px-5 py-2.5 text-[13px] font-semibold text-ink/60 transition hover:text-ink disabled:cursor-not-allowed disabled:opacity-30"
                  style={{transitionTimingFunction:"var(--ease-glide)"}}
                >← 上一步</button>
                <button
                  type="button"
                  className="group inline-flex items-center justify-between gap-2 rounded-full px-5 py-3 text-[14px] font-bold transition-all duration-400 active:scale-[0.98]"
                  style={{
                    backgroundColor: onboardingStep===6 ? "var(--color-ink)" : "var(--color-copper)",
                    color: "#FFFDF7",
                    transitionTimingFunction: "var(--ease-spring-in)",
                    boxShadow: onboardingStep===6 ? "0 4px 14px rgba(28,35,41,0.28)" : "var(--shadow-copper)",
                  }}
                  onClick={()=>{
                    if (onboardingStep < 6) setOnboardingStep((s)=>(s+1) as 1|2|3|4|5|6);
                    else { showToast("Onboarding 完成！首份计划生成中（3 秒）…","ok"); setTimeout(()=>{setIsFirstSession(false);}, 1500); }
                  }}
                >
                  <span className="ml-2 tracking-wide">{onboardingStep===6 ? "✨ 好，开始备考！" : "下一步"}</span>
                  <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-0.5 group-hover:scale-105" style={{backgroundColor:"rgba(255,253,247,0.13)"}}>
                    {onboardingStep===6 ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFDF7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                    ) : (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFDF7" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>
                    )}
                  </span>
                </button>
              </div>
            </div>
          ) : (
            <>
              {/* 六刀懒加载状态行（顶部）：拉页显「加载更早…」；到头钉「没有更早消息」 */}
              {loadingOlder && (
                <p className="text-center text-[11px] font-semibold text-ink/40">加载更早…</p>
              )}
              {!hasMore && !loadingOlder && messages.length > 0 && (
                <p className="text-center text-[11px] font-semibold text-ink/40">没有更早消息</p>
              )}
              {messages.map((m, i) => {
                /* 六刀动画治理：float-up 只给"本次才露面"的消息——
                   历史行（toMsg 登记过 / 换屏重登记）全部静默显形，秒出不演 6 秒排队 */
                const fresh = m.id === undefined || !seenIds.current.has(m.id);
                if (m.id !== undefined) seenIds.current.add(m.id);
                return (
                <div key={m.id ?? `t${i}`} className={`flex items-end gap-3 ${m.role==="me"?"justify-end":""} ${fresh ? "animate-float-up" : ""}`}>
                  {m.role==="coach" && <CoachAvatar />}
                  {m.role==="coach" ? (
                    <div className="p-1 rounded-[1.5rem] ring-1 ring-ink/5 max-w-[80%] md:max-w-[65%]" style={{backgroundColor:"var(--color-mist)", boxShadow:"var(--shadow-float-sm)"}}>
                      <div className="px-5 py-3.5" style={{backgroundColor:"var(--color-parchment)", borderRadius:"calc(1.5rem - 0.25rem)", borderBottomLeftRadius:"0.4rem", boxShadow:"inset 0 1px 1px rgba(255,255,255,0.8)"}}>
                        {/* 教练气泡走 Markdown 渲染：模型吐的星号加粗、列表符号终于变形状。
                            不渲原始 HTML（react-markdown 默认），只当排版语法读；用户气泡维持纯文本 */}
                        <div className="md-body font-heading text-[15px] leading-[1.85] text-ink">
                          <ReactMarkdown>{m.text}</ReactMarkdown>
                        </div>
                        {m.citations?.length ? (
                          /* 引用小票：编号对应正文 [N]；甲案起票根可点——
                             点开就地展开那块讲义原文（懒取+缓存），再点收起 */
                          <div className="mt-2.5 border-t border-ink/5 pt-2.5">
                            <div className="flex flex-wrap gap-1.5">
                              {m.citations.map((c, n) => {
                                const key = `${m.id}-${n}-${c.chunk_id}`;
                                const open = citOpen?.key === key;
                                return (
                                  <button type="button" key={key} title="点开看这块原文"
                                    className="inline-flex cursor-pointer items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold text-ink/60 transition hover:brightness-95"
                                    style={{backgroundColor:"var(--color-mist)", ...(open ? {outline:"1px solid var(--color-copper)"} : {})}}
                                    onClick={() => {
                                      if (open) { setCitOpen(null); return; }
                                      setCitOpen({ key });
                                      api(`/api/chunks/${c.chunk_id}`).then(d => {
                                        const r = d as { title: string; seq: number; content: string };
                                        setCitOpen(cur => cur?.key === key ? { key, ...r } : cur);
                                      }).catch(e => {
                                        setCitOpen(cur => cur?.key === key ? { key, err: (e as Error).message } : cur);
                                      });
                                    }}>
                                    {/* D79 甲案：序号以票自带 ref 为准（过滤后不连号），旧账无 ref 回落位次 */}
                                    <span className="text-copper">[{c.ref ?? n + 1}]</span>
                                    <span>《{c.title}》· 第 {c.seq + 1} 块</span>
                                  </button>
                                );
                              })}
                            </div>
                            {citOpen && m.citations.some(
                              (c, n) => citOpen.key === `${m.id}-${n}-${c.chunk_id}`) ? (
                              <div className="mt-1.5 rounded-2xl px-3.5 py-2.5 text-[12.5px]" style={{backgroundColor:"var(--color-parchment)", boxShadow:"inset 0 1px 2px rgba(0,0,0,0.06)"}}>
                                {citOpen.err ? (
                                  <p className="text-ink/50">取不到原文：{citOpen.err}</p>
                                ) : citOpen.content === undefined ? (
                                  <p className="text-ink/40">原文取回中…</p>
                                ) : (
                                  <>
                                    <p className="whitespace-pre-wrap leading-[1.8] text-ink/75">{citOpen.content}</p>
                                    <p className="mt-1.5 text-[10.5px] text-ink/40">—— 《{citOpen.title}》 · 第 {citOpen.seq! + 1} 块（块全文）</p>
                                  </>
                                )}
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  ) : (
                    <div className="max-w-[80%] rounded-[1.5rem] px-5 py-3.5 md:max-w-[65%]" style={{background:"linear-gradient(135deg, var(--color-copper) 0%, var(--color-copper-dk) 100%)", color:"var(--color-parchment)", borderBottomRightRadius:"0.4rem", boxShadow:"var(--shadow-user)"}}>
                      <p className="font-heading text-[15px] leading-[1.85]">{m.photo ? "📷 " : ""}{m.text}</p>
                    </div>
                  )}
                </div>
                );
              })}

              {showSuggestions && (
                <div className="animate-float-up ml-14 pl-1" style={{animationDelay:"220ms"}}>
                  <p className="mb-3 text-[12px] font-semibold tracking-wide text-ink/45">或者从这里开始 ——</p>
                  <div className="flex flex-wrap gap-3">
                    {QUICK_SUGGESTIONS.map((s) => (
                      <button key={s.text} type="button" onClick={()=>clickSuggestion(s.text)}
                              className="group inline-flex items-center gap-2 rounded-[1rem] p-1 ring-1 ring-ink/5 transition-all duration-300 hover:-translate-y-1"
                              style={{backgroundColor:"var(--color-mist)", transitionTimingFunction:"var(--ease-spring-out)", boxShadow:"var(--shadow-float-sm)"}}>
                        <div className="inline-flex items-center gap-2 rounded-[calc(1rem-0.25rem)] bg-parchment px-4 py-2.5 text-[13px] font-semibold text-ink" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
                          <span className="text-copper"><QuickIcon name={s.icon}/></span>
                          <span>{s.text}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {(thinking || (flyHere && fly !== null && fly.thinking && !fly.acc)) && (
                <div className="animate-float-up flex items-end gap-3 text-[13px] text-ink/60" style={{animationDelay:"100ms"}}>
                  <CoachAvatar />
                  <div className="inline-flex items-center gap-3 rounded-[1.5rem] px-5 py-3.5" style={{backgroundColor:"var(--color-mist)", borderBottomLeftRadius:"0.4rem", boxShadow:"var(--shadow-float-sm)"}}>
                    <span>教练正在翻你的计划</span>
                    <span className="inline-flex items-end gap-1">
                      <span className="animate-wave-dot size-1.5 rounded-full bg-copper"/>
                      <span className="animate-wave-dot size-1.5 rounded-full bg-copper" style={{animationDelay:"150ms"}}/>
                      <span className="animate-wave-dot size-1.5 rounded-full bg-copper" style={{animationDelay:"300ms"}}/>
                    </span>
                  </div>
                </div>
              )}

              {/* D67 二刀 · 在飞流正文：字从 fly 直读渲染——发起者切页再回来、
                  或另一只实例接手观看，看到的都是同一条正在生长的字（着陆后换库账） */}
              {flyHere && fly !== null && fly.acc !== "" && (
                <div className="flex items-end gap-3">
                  <CoachAvatar />
                  <div className="p-1 rounded-[1.5rem] ring-1 ring-ink/5 max-w-[80%] md:max-w-[65%]" style={{backgroundColor:"var(--color-mist)", boxShadow:"var(--shadow-float-sm)"}}>
                    <div className="px-5 py-3.5" style={{backgroundColor:"var(--color-parchment)", borderRadius:"calc(1.5rem - 0.25rem)", borderBottomLeftRadius:"0.4rem", boxShadow:"inset 0 1px 1px rgba(255,255,255,0.8)"}}>
                      <div className="md-body font-heading text-[15px] leading-[1.85] text-ink">
                        <ReactMarkdown>{fly.acc}</ReactMarkdown>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {apologizeOpen && (
                <div className="mx-auto max-w-md animate-float-up">
                  <div className="rounded-[1.5rem] p-1.5 ring-1 ring-rust/25" style={{backgroundColor:"rgba(168,84,62,0.08)"}}>
                    <div className="rounded-[calc(1.5rem-0.375rem)] bg-parchment px-6 py-5" style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.8)"}}>
                      <div className="mb-2 flex items-center gap-2 font-heading font-semibold text-rust">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M12 9v4M12 17h.01"/>
                          <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                        </svg>
                        模型暂时无法应答
                      </div>
                      <p className="text-[14px] leading-relaxed text-ink/70">看起来这会儿大脑在重启，稍等 30 秒再试一次？再不行可以去「设置」检查一下你的连接状态。</p>
                      <div className="mt-4 flex gap-2">
                        <button onClick={()=>{setApologizeOpen(false); showToast("已尝试重连。","warn");}}
                                className="group inline-flex items-center gap-2 rounded-full bg-rust px-5 py-2 text-[13px] font-semibold text-parchment transition active:scale-[0.98]"
                                style={{transitionTimingFunction:"var(--ease-spring-in)"}}>重新连接</button>
                        <button onClick={()=>setApologizeOpen(false)} className="rounded-full border border-ink/15 bg-parchment px-5 py-2 text-[13px] font-semibold text-ink/70 transition hover:border-ink/30">知道了</button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={endRef}/>
        </section>

        {/* D56 甲：QQ 线只读横幅——「记着却看不见」补上的另一半是「看得见但各回各家」 */}
        {activeIsQQ && (
          <div className="px-5 md:px-6">
            <p className="rounded-full px-4 py-2 text-center text-[12px] font-semibold text-ink/60"
               style={{backgroundColor:"var(--color-mist)"}}>
              这是 QQ 那边的对话——在这里能看、能删，想接着聊请去 QQ 找它。
            </p>
          </div>
        )}
        {/* 浮动药丸输入岛 */}
        <form
          className="px-5 pb-5 pt-3 md:px-6 md:pb-6"
          onSubmit={(e) => { e.preventDefault(); send(); }}
        >
          {/* 攥图待发型缩略预览条（S7 四刀）：拍板前让用户看清要发的是哪张，× 可撤 */}
          {pendingImg && (
            <div className="mb-2 flex items-center gap-2.5 rounded-[1rem] px-3 py-2 ring-1 ring-ink/8"
                 style={{backgroundColor:"var(--color-mist)"}}>
              {previewUrl && <img src={previewUrl} alt="待发送照片缩略图" className="size-10 rounded-lg object-cover ring-1 ring-ink/10"/>}
              <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-ink/60">{pendingImg.name}</span>
              <button type="button" title="移除照片" onClick={() => setPendingImg(null)}
                      className="grid size-7 shrink-0 place-items-center rounded-full text-ink/50 transition hover:text-rust"
                      style={{backgroundColor:"var(--color-parchment)"}}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" strokeWidth="2.2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
              </button>
            </div>
          )}
          {/* 真文件选择器藏在按钮后面：accept 与后端 _IMG_KINDS 对齐（gif 不收——动图坑收窄） */}
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
                 onChange={(e) => {
                   const f = e.target.files?.[0];
                   e.target.value = "";   // 清空否则同一张连选两次不触发 change
                   if (f) setPendingImg(f);
                 }}/>
          <div
            className="rounded-[1.25rem] p-1 ring-1 ring-ink/8"
            style={{backgroundColor:"var(--color-mist)", boxShadow:"0 8px 30px rgba(28,35,41,0.10)"}}
          >
            <div className="flex items-center gap-1 rounded-[calc(1.25rem-0.25rem)] px-3 py-2.5" style={{backgroundColor:"var(--color-parchment)", boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
              {/* 图片（S7 四刀已接真：点开文件器，选完攥进 pendingImg） */}
              <button type="button" onClick={() => fileRef.current?.click()} title="拍照汇报：选一张题图或截图发给我"
                      disabled={activeIsQQ}
                      className="grid size-10 shrink-0 place-items-center rounded-full text-ink/65 transition-all duration-300 hover:text-copper disabled:cursor-not-allowed disabled:opacity-40"
                      style={{backgroundColor:"var(--color-mist)", transitionTimingFunction:"var(--ease-glide)"}}>
                <Icon n="image"/>
              </button>
              {/* 联网兜底开关（S8 · D58 甲）：地球+小胶囊成 pill，开=copper 亮起。
                  语义钉死：关=web_search 不进模型工具箱、零命中只回「讲义里没有」；开=才准查网络。 */}
              <button type="button" onClick={toggleWeb} aria-pressed={webOn}
                      title={webOn ? "联网兜底：已开启——讲义查不到时可上网查（答案注明来自网络），也可按通用常识作答并注明" : "联网兜底：已关闭——只用你的讲义：查不到就回「知识库无相关资料」，不碰外网也不用常识补答"}
                      className={`flex h-10 shrink-0 items-center gap-1.5 rounded-full px-2.5 transition-all duration-300 ${webOn ? "text-copper" : "text-ink/65 hover:text-copper"}`}
                      style={{backgroundColor:"var(--color-mist)", transitionTimingFunction:"var(--ease-glide)"}}>
                <Icon n="globe"/>
                <span className={`relative inline-block h-4 w-7 rounded-full transition-colors ${webOn ? "bg-copper" : "bg-ink/15"}`}>
                  <span className="absolute top-[3px] size-2.5 rounded-full bg-white shadow transition-all"
                        style={{left: webOn ? "calc(100% - 13px)" : "3px"}}/>
                </span>
              </button>
              {/* 模型切换（S8 · D60 甲）：chip+当前型号+下拉箭头，菜单向上开。
                  灰项=平台没钥匙（available=false），照列不藏——配好 .env 重建容器即点亮。 */}
              <div className="relative shrink-0">
                <button type="button" onClick={() => setModelMenu((v) => !v)} aria-expanded={modelMenu}
                        title={`当前对话模型：${curModel || "…"}（点击换）${modelRows.find((m) => m.id === curModel)?.byo ? " · 自带钥匙，对话免扣积分" : ""}`}
                        className="flex h-10 shrink-0 items-center gap-1 rounded-full px-2.5 text-ink/65 transition-all duration-300 hover:text-copper"
                        style={{backgroundColor:"var(--color-mist)", transitionTimingFunction:"var(--ease-glide)"}}>
                  <Icon n="chip" size={16}/>
                  <span className="max-w-[7.5rem] truncate text-[11px] font-semibold">{curModel || "…"}</span>
                  {modelRows.find((m) => m.id === curModel)?.byo && (
                    <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold text-copper"
                          style={{backgroundColor:"var(--color-mist)"}}>自钥</span>
                  )}
                  <Icon n="chevron" size={12}/>
                </button>
                {modelMenu && (<>
                  <div className="fixed inset-0 z-10" onClick={() => setModelMenu(false)}/>
                  <ul className="absolute bottom-full left-0 z-20 mb-2 w-60 rounded-2xl p-1 ring-1 ring-ink/10"
                      style={{backgroundColor:"var(--color-parchment)", boxShadow:"0 8px 30px rgba(28,35,41,0.18)"}}>
                    {modelRows.map((m) => (
                      <li key={m.id}>
                        <button type="button" onClick={() => pickModel(m)}
                                disabled={!m.available}
                                title={m.available ? (m.byo ? `换到 ${m.id}（${m.platform} · 自带钥匙烧自己的油，不扣积分）` : `换到 ${m.id}（${m.platform} · 积分按 ×${m.multiplier ?? 1} 扣）`) : `${m.platform} 平台还没配钥匙：.env 补对应 KEY 并重建容器后可选，DeepSeek 系也可在设置页自带钥匙`}
                                className={`flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left text-[12px] transition-colors ${
                                  m.id === curModel ? "bg-copper/10 text-copper font-semibold"
                                  : m.available ? "text-ink hover:bg-ink/5" : "text-ink/30 cursor-not-allowed"}`}>
                          <span className="truncate">{m.id}{m.byo ? " ·自带钥" : ""}</span>
                          <span className="shrink-0 text-[10px] text-ink/40">{m.id === curModel ? "使用中" : m.byo ? "自带钥匙 · 免积分" : m.available ? `${m.platform} · ×${m.multiplier ?? 1}` : "未配钥匙"}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>)}
              </div>
              {/* 语音按钮已拆（2026-09-09）：S1 道具，点击只会自曝 Mock——语音输入整条腿未做 */}
              {/* 文本框 */}
              <input value={draft} onChange={(e)=>setDraft(e.target.value)}
                     placeholder={activeIsQQ ? "QQ 线只读——想接着聊去 QQ 找它" : "问点什么，比如：今晚学什么？"}
                     disabled={activeIsQQ}
                     aria-label="给教练发消息" className="min-w-0 flex-1 bg-transparent px-2 py-1.5 text-[15px] text-ink outline-none placeholder:text-ink/35 disabled:cursor-not-allowed"/>
              {/* 「新会话」假按钮已拆（2026-09-09）：单会话账后端自管，清屏=幽灵操作，真做多会话归 S8 */}
              {/* 发送 Nested CTA */}
              <button type="submit" disabled={activeIsQQ || (!draft.trim() && !pendingImg) || thinking}
                      className="group inline-flex shrink-0 items-center gap-2 rounded-full bg-copper px-5 py-2.5 text-[13px] font-semibold text-parchment transition-all duration-400 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                      style={{transitionTimingFunction:"var(--ease-spring-in)", boxShadow:"var(--shadow-copper)"}}>
                <span className="hidden sm:inline">发送</span>
                <span className="grid size-7 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-0.5 group-hover:scale-105"
                      style={{backgroundColor:"rgba(255,251,243,0.15)", transitionTimingFunction:"var(--ease-spring-in)"}}>
                  <Icon n="send" size={14}/>
                </span>
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
