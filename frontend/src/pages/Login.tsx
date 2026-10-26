/* ============================================================
 * 登录 / 注册页 v2
 * 左：画册式墨青品牌墙（诗集排版 + 噪点）
 * 右：羊皮纸 Double-Bezel 表单岛
 * Segmented：墨青胶囊滑动切换
 * 输入框：Float Label 浮动标签（聚焦上移缩小铜绿变色）
 * 验证码：SVG 环形进度环 60s 冷却可视化
 * 主按钮：Nested CTA 胶囊 + 内嵌箭头岛
 * D：忘记密码 3 步流程（验证邮箱 → 新密码 → 成功大对勾）
 * ============================================================ */

import { useEffect, useState, type FormEvent, type ReactElement } from "react";
import { api, saveAuth } from "../auth";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/* 邀请码全链退役（D54 · 2026-09-10 用户拍板甲案全拆）：
   注册只认邮箱+验证码+密码，本页不再有任何码框与码账概念 */

/**
 * 冷却进度环：SVG 圆环按 cooldown/60 的进度褪去。
 */
function CooldownRing({ cooldown, totalSec = 60 }: { cooldown: number; totalSec?: number }): ReactElement {
  const r = 12;
  const C = 2 * Math.PI * r;
  const progress = cooldown === 0 ? 1 : 1 - cooldown / totalSec;
  const dashOffset = C * (1 - progress);
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" className="shrink-0">
      <circle cx="14" cy="14" r={r} fill="none" stroke="var(--color-sand)" strokeWidth="2"/>
      <circle cx="14" cy="14" r={r} fill="none" stroke="var(--color-copper)" strokeWidth="2" strokeLinecap="round"
              strokeDasharray={C} strokeDashoffset={dashOffset} transform="rotate(-90 14 14)"
              style={{ transition: "stroke-dashoffset 1s var(--ease-glide)" }}/>
      <text x="14" y="14" textAnchor="middle" dominantBaseline="central" fontSize="8" fontFamily="var(--font-mono)"
            fontWeight="700" fill="var(--color-copper)">
        {cooldown === 0 ? "✓" : cooldown}
      </text>
    </svg>
  );
}

/**
 * 浮动标签输入框：Double-Bezel 架构，支持 trailing 尾插（送码按钮等）。
 */
function FloatInput({
  label, value, onChange, type = "text", inputMode, autoComplete, maxLength, placeholder, trailing,
}: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; inputMode?: "numeric" | "text" | "email";
  autoComplete?: string; maxLength?: number; placeholder?: string;
  trailing?: React.ReactNode;
}): ReactElement {
  const active = value.length > 0;
  return (
    <div className="group rounded-[1rem] p-1 ring-1 ring-ink/10 transition-all duration-300 focus-within:ring-copper/30"
         style={{ backgroundColor: "var(--color-mist)", transitionTimingFunction: "var(--ease-glide)" }}>
      <div className="relative rounded-[calc(1rem-0.25rem)] bg-parchment px-4 py-3"
           style={{ boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)" }}>
        <label className="pointer-events-none absolute left-4 origin-left transition-all duration-300"
               style={{
                 top: active ? "6px" : "50%",
                 transform: active ? "translateY(0) scale(0.78)" : "translateY(-50%) scale(1)",
                 color: active ? "var(--color-copper)" : "rgba(28,35,41,0.5)",
                 fontWeight: active ? 700 : 500,
                 transitionTimingFunction: "var(--ease-glide)",
               }}>{label}</label>
        <div className="flex items-center gap-2 pt-[14px]">
          <input type={type} value={value} onChange={(e)=>onChange(e.target.value)} inputMode={inputMode}
                 autoComplete={autoComplete} maxLength={maxLength}
                 placeholder={active ? placeholder : ""}
                 className="w-full min-w-0 bg-transparent text-[15px] text-ink outline-none placeholder:text-ink/30"/>
          {trailing}
        </div>
      </div>
    </div>
  );
}

/**
 * 鎏金冲屏文字：勤学 / 励志古诗文，从屏幕中心向四周飞出。
 * tx/ty 为目标位置相对中心的偏移（vw/vh）。位置经过规划避免重叠。
 * 发光用静态 text-shadow（不进动画 keyframes），保证流畅。
 */
const GOLD_CHARS = [
  { text: "长风破浪会有时", x: "-18vw", y: "-18vh", size: "clamp(2.8rem,6vw,5rem)", rotate: -2, delay: 0, duration: 9, vertical: true, z: 9 },
  { text: "读书破万卷",     x: "18vw",  y: "-20vh", size: "clamp(2.4rem,5vw,4.4rem)", rotate: 3,  delay: 2.2,  duration: 10, vertical: true, z: 8 },
  { text: "书山有路勤为径", x: "-16vw", y: "18vh",  size: "clamp(2.2rem,4.6vw,4rem)", rotate: -1, delay: 4.4,  duration: 11, vertical: true, z: 7 },
  { text: "少壮不努力",     x: "18vw",  y: "16vh",  size: "clamp(2.6rem,5.4vw,4.8rem)", rotate: 2, delay: 6.6,  duration: 9.5, vertical: true, z: 6 },
  { text: "路漫漫其修远兮", x: "0vw",   y: "-34vh", size: "clamp(2rem,4.2vw,3.8rem)",  rotate: 0,  delay: 1.1,  duration: 10, vertical: true, z: 5 },
  { text: "宝剑锋从磨砺出", x: "0vw",   y: "32vh",  size: "clamp(2rem,4.2vw,3.8rem)",  rotate: -2, delay: 5.5,  duration: 11, vertical: true, z: 4 },
  { text: "纸上得来终觉浅", x: "-24vw", y: "0vh",   size: "clamp(2.2rem,4.6vw,4rem)", rotate: -3, delay: 3.3,  duration: 10, vertical: true, z: 3 },
  { text: "黑发不知勤学早", x: "24vw",  y: "-2vh",  size: "clamp(2.2rem,4.6vw,4rem)", rotate: 1,  delay: 7.7,  duration: 11, vertical: true, z: 2 },

  { text: "直挂云帆济沧海", x: "-6vw",  y: "-24vh", size: "clamp(1rem,1.8vw,1.6rem)",  rotate: 4,  delay: 1.6,  duration: 10, vertical: true, z: 1 },
  { text: "下笔如有神",     x: "8vw",   y: "-8vh",  size: "clamp(1.2rem,2.1vw,1.8rem)", rotate: -2, delay: 3.8,  duration: 9,  vertical: true, z: 1 },
  { text: "学海无涯苦作舟", x: "-8vw",  y: "8vh",   size: "clamp(1rem,1.8vw,1.6rem)",  rotate: 2,  delay: 6.0,  duration: 10, vertical: true, z: 1 },
  { text: "老大徒伤悲",     x: "6vw",   y: "24vh",  size: "clamp(1.1rem,1.9vw,1.7rem)", rotate: -1, delay: 8.2,  duration: 9.5, vertical: true, z: 1 },
  { text: "吾将上下而求索", x: "14vw",  y: "32vh",  size: "clamp(0.9rem,1.5vw,1.3rem)", rotate: 3,  delay: 0.5,  duration: 11, vertical: true, z: 1 },
  { text: "梅花香自苦寒来", x: "-14vw", y: "32vh",  size: "clamp(0.9rem,1.5vw,1.3rem)", rotate: -3, delay: 2.7,  duration: 10, vertical: true, z: 1 },
  { text: "绝知此事要躬行", x: "-14vw", y: "-32vh", size: "clamp(0.9rem,1.5vw,1.3rem)", rotate: 1,  delay: 4.9,  duration: 11, vertical: true, z: 1 },
  { text: "白首方悔读书迟", x: "14vw",  y: "-32vh", size: "clamp(0.9rem,1.5vw,1.3rem)", rotate: -4, delay: 7.1,  duration: 10, vertical: true, z: 1 },
] as const;




export default function Login({ onEnter }: { onEnter: () => void }): ReactElement {
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState("");
  const [pwd, setPwd] = useState("");
  const [code, setCode] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);   /* 请求在路上：按钮置灰防连点 */
  const [sending, setSending] = useState(false);   /* 送码请求在路上 */
  const [notice, setNotice] = useState("");        /* 送码成功提示（绿字，与报错分开） */
  const [cooldown, setCooldown] = useState(0);
  /* D. 忘记密码流程：0=关闭 1=邮箱 2=新密码 3=成功 */
  const [resetStep, setResetStep] = useState<0|1|2|3>(0);
  const [resetEmail, setResetEmail] = useState("");
  const [resetCode,  setResetCode]  = useState("");
  const [resetPwd,   setResetPwd]   = useState("");
  const [resetPwd2,  setResetPwd2]  = useState("");
  const [resetCD,    setResetCD]    = useState(0);
  const [resetSending, setResetSending] = useState(false);  /* 重置码寄信中 */
  const [resetBusy,  setResetBusy]  = useState(false);      /* 改密请求在路上 */
  const [resetNotice, setResetNotice] = useState("");       /* 重置码寄出提示（绿字） */

  /* 送码倒计时两个独立 effect */
  useEffect(() => { if (cooldown <= 0) return; const t = setTimeout(()=>setCooldown((n)=>n-1), 1000); return ()=>clearTimeout(t); }, [cooldown]);
  useEffect(() => { if (resetCD <= 0)  return; const t = setTimeout(()=>setResetCD((n)=>n-1),  1000); return ()=>clearTimeout(t); }, [resetCD]);

  /** 登录/注册提交：前端先过一遍快检，真裁决交给后端（查重/验码/发证都在服务端）
   *  S8 首刀：注册走真身——邮箱+验证码+密码（F-01）；username 暂=邮箱串（S1 惯例）。
   *  D48 甲（2026-09-10）：忘记密码三步屏已接真腿——送码走 /api/reset/send-code、
   *  改密走 /api/reset/confirm，与注册共用服务端一套码闸（purpose='reset' 各算各账）。 */
  async function sendCode(): Promise<void> {
    setErr(""); setNotice("");
    if (!EMAIL_RE.test(email)) { setErr("邮箱格式不对，先填对邮箱再点发送。"); return; }
    setSending(true);
    try {
      await api("/api/register/send-code", { email });
      setCooldown(60);
      setNotice("验证码已寄出（10 分钟内有效），请查收邮件——没有的话翻翻垃圾箱。");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "网络出错了");
    } finally {
      setSending(false);
    }
  }

  async function submit(e: FormEvent): Promise<void> {
    e.preventDefault(); setErr(""); setNotice("");
    if (!EMAIL_RE.test(email)) { setErr("邮箱格式不对，检查一下是否有 @ 和域名？"); return; }
    if (pwd.length < 8) { setErr("密码至少要 8 位，建议字母 + 数字混合更安全。"); return; }
    if (mode === "register") {
      if (!code) { setErr("先点「发送验证码」，把邮箱里收到的 6 位码填上。"); return; }
    }
    setBusy(true);
    try {
      const data = await api(mode === "register" ? "/api/register" : "/api/login",
                             mode === "register"
                               ? { username: email, password: pwd, email, code }
                               : { username: email, password: pwd }) as { token: string; username: string };
      saveAuth(data.token, data.username);   /* 票进口袋，再放行进屋 */
      onEnter();
    } catch (err2) {
      /* 后端有理有据的拒绝：409 已被占用 / 401 用户名或密码不正确 / 422 密码不合规 */
      setErr(err2 instanceof Error ? err2.message : "网络出错了");
    } finally {
      setBusy(false);
    }
  }

  /** 找回第一步：向 /api/reset/send-code 要重置码（查无此户由后端 400 拦下并说人话） */
  async function sendResetCode(): Promise<void> {
    setErr(""); setResetNotice("");
    if (!EMAIL_RE.test(resetEmail)) { setErr("邮箱格式不对，先填对邮箱再点发送。"); return; }
    setResetSending(true);
    try {
      await api("/api/reset/send-code", { email: resetEmail });
      setResetCD(60);
      setResetNotice("重置验证码已寄出（10 分钟内有效），请查收邮件——没有的话翻翻垃圾箱。");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "网络出错了");
    } finally {
      setResetSending(false);
    }
  }

  /** 找回第二步：填码+新密码交后端验闸改密——成功才进第三步（假对勾退役） */
  async function confirmReset(e: FormEvent): Promise<void> {
    e.preventDefault(); setErr("");
    if (resetPwd.length < 8) { setErr("密码至少 8 位。"); return; }
    if (!/[A-Za-z]/.test(resetPwd) || !/\d/.test(resetPwd)) { setErr("必须同时包含字母和数字。"); return; }
    if (resetPwd !== resetPwd2) { setErr("两次输入的新密码不一致。"); return; }
    setResetBusy(true);
    try {
      await api("/api/reset/confirm", { email: resetEmail, code: resetCode, new_password: resetPwd });
      setResetStep(3);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "网络出错了");
    } finally {
      setResetBusy(false);
    }
  }

  const segOpts = [
    ["register", "注册"],
    ["login", "登录"],
  ] as const;

  return (
    <div className="relative flex min-h-[100dvh] w-full">
      <div className="relative z-[2] flex w-full min-h-[100dvh]">
        {/* ============ 左：鎏金冲屏品牌墙（墨灰宣纸肌理） ============ */}
        <div className="relative hidden w-[52%] shrink-0 flex-col justify-between overflow-hidden lg:flex"
             style={{ backgroundColor: "#1A1916" }}>
          {/* 宣纸细纤维纹 */}
          <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.07]"
               style={{backgroundImage:"url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300' viewBox='0 0 300 300'><filter id='fiber'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(%23fiber)'/></svg>\")", backgroundRepeat:"repeat"}}/>
          {/* 墨色大块晕染（宣纸受潮/墨韵感） */}
          <div aria-hidden className="pointer-events-none absolute inset-0 opacity-[0.12]"
               style={{backgroundImage:"url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='900' height='900' viewBox='0 0 900 900'><filter id='inkwash'><feTurbulence type='fractalNoise' baseFrequency='0.012' numOctaves='3' stitchTiles='stitch'/><feColorMatrix type='saturate' values='0'/></filter><rect width='100%' height='100%' filter='url(%23inkwash)'/></svg>\")", backgroundRepeat:"no-repeat", backgroundSize:"cover"}}/>
          {/* 中心暖金光晕 */}
          <div aria-hidden className="pointer-events-none absolute inset-0"
               style={{background:"radial-gradient(700px 500px at 50% 50%, rgba(212,175,55,0.08), transparent 70%)"}}/>
          {/* 鎏金冲屏文字层：全部从 center 飞出，发光用静态 text-shadow */}
          <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
            {GOLD_CHARS.map((c, i) => (
              <div key={i} className="absolute left-1/2 top-1/2 select-none whitespace-nowrap"
                   style={{
                     fontSize: c.size,
                     writingMode: c.vertical ? "vertical-rl" : "horizontal-tb",
                     background: "linear-gradient(180deg, #FFE9A8 0%, #E8C87A 18%, #D4AF37 48%, #A87C1A 78%, #8B6508 100%)",
                     WebkitBackgroundClip: "text",
                     backgroundClip: "text",
                     color: "transparent",
                     fontFamily: "var(--font-display)",
                     fontWeight: 700,
                     lineHeight: 1.15,
                     letterSpacing: c.vertical ? "0.14em" : "0.06em",
                     textShadow: "0 0 8px rgba(212,175,55,0.35), 0 0 18px rgba(180,140,40,0.18)",
                     position: "absolute",
                     left: "50%",
                     top: "50%",
                     transformOrigin: "center center",
                     // ✅ 挂载瞬间直接就位！不会短暂跑到中心点
                     transform: `translate(-50%, -50%) translate(${c.x}, ${c.y}) scale(0.95) rotate(${c.rotate}deg)`,
                     opacity: 0, // 初始透明，就位之后再淡入
                     "--x": c.x,
                     "--y": c.y,
                     "--r": `${c.rotate}deg`,
                     zIndex: c.z,
                     animation: `gold-float-around ${c.duration}s var(--ease-spring-out) ${c.delay}s infinite`,
                     willChange: "transform, opacity",
                   } as React.CSSProperties}>
                {c.text}
              </div>
            ))}
          </div>
        </div>

        {/* ============ 右：表单区 ============ */}
        <main className="flex flex-1 items-center justify-center px-5 py-10 md:px-8">
          <div className="w-full max-w-md rounded-[2rem] p-2 ring-1 ring-ink/5 animate-float-up"
               style={{backgroundColor:"var(--color-mist)", boxShadow:"var(--shadow-float-lg)"}}>
            <div className="rounded-[calc(2rem-0.375rem)] bg-parchment px-6 py-9 sm:px-10 sm:py-10"
                 style={{boxShadow:"inset 0 1px 1px rgba(255,255,255,0.9)"}}>
              {/* ============ D. 忘记密码三屏 / 登录注册 二选一双流 ============ */}
              {resetStep > 0 ? (
                <div className="animate-float-up">
                  {/* 顶部三步指示器 */}
                  <div className="mb-8 flex items-center gap-2">
                    {[1,2,3].map((s)=>{
                      const label = ["","验证邮箱","设新密码","重置成功"][s];
                      const done = resetStep > s;
                      const active = resetStep >= s;
                      return (
                        <div key={s} className="flex items-center gap-2">
                          <span className="grid size-7 place-items-center rounded-full font-mono text-[12px] font-bold transition"
                                style={{backgroundColor:active?"var(--color-copper)":"var(--color-mist)", color:active?"#FFFDF7":"var(--color-ink-soft)", transitionTimingFunction:"var(--ease-glide)"}}>
                            {done ? "✓" : s}
                          </span>
                          <span className={`hidden sm:inline text-[11px] font-semibold ${active?"text-copper":"text-ink/45"}`}>{label}</span>
                          {s<3 && <div className="h-[1.5px] w-6 sm:w-10" style={{backgroundColor:done?"var(--color-copper)":"rgba(28,35,41,0.12)"}}/>}
                        </div>
                      );
                    })}
                  </div>

                  {/* 第一步：验证邮箱 + 送码 */}
                  {resetStep === 1 && (
                    <>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第一步 · 验证邮箱</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">先告诉我你注册的邮箱。</h3>
                      <p className="mt-1 text-[13px] text-ink/60">QQ 邮箱可能进垃圾箱，没收到先去那边看看。</p>
                      <form
                        onSubmit={(e)=>{
                          e.preventDefault();
                          if (!resetCode) { setErr("先点「发送验证码」并填入 6 位数字。"); return; }
                          setErr(""); setResetStep(2);
                        }}
                        className="mt-7 space-y-4"
                      >
                        <FloatInput label="注册邮箱" value={resetEmail} onChange={setResetEmail} type="email" inputMode="email" placeholder="you@example.com"/>
                        {/* 验证码 + 送码按钮：走注册页同款 FloatInput 组件——
                            手写复制品曾致浮标与数字打架（D48 真机日用户圈图），并轨治本 */}
                        <FloatInput
                          label="邮箱验证码" value={resetCode} onChange={setResetCode} inputMode="numeric" maxLength={6} placeholder="6位数字"
                          trailing={
                            <button type="button" onClick={()=>void sendResetCode()} disabled={resetCD>0 || resetSending || !resetEmail.length}
                                    className="shrink-0 inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[12px] font-bold transition duration-300 disabled:opacity-40"
                                    style={{backgroundColor:resetCD>0?"var(--color-mist)":"var(--color-copper)", color:resetCD>0?"rgba(28,35,41,0.65)":"#FFFDF7", transitionTimingFunction:"var(--ease-glide)"}}>
                              {resetCD > 0
                                ? (<><span className="font-mono">{resetCD}</span><span className="text-[10px] opacity-70">秒后再发</span></>)
                                : (<><span>{resetSending ? "寄信中…" : "发送验证码"}</span><span className="grid size-5 place-items-center rounded-full" style={{backgroundColor:"rgba(255,253,247,0.14)"}}><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg></span></>)}
                            </button>
                          }
                        />
                        {err && (
                          <div className="rounded-[0.9rem] px-4 py-2.5 flex items-start gap-2" style={{backgroundColor:"rgba(168,84,62,0.10)"}}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-rust)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0">
                              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                              <path d="M12 9v4"/><circle cx="12" cy="17" r="0.7" fill="var(--color-rust)"/>
                            </svg>
                            <p className="text-[12px] leading-relaxed font-semibold text-rust">{err}</p>
                          </div>
                        )}
                        {resetNotice && (
                          <div role="status" className="rounded-[0.9rem] px-4 py-2.5 text-[12px] font-semibold"
                               style={{backgroundColor:"rgba(91,115,120,0.12)", color:"#3E6B5A"}}>{resetNotice}</div>
                        )}
                        <div className="flex items-center justify-between pt-3">
                          <button type="button" onClick={()=>{setResetStep(0); setErr(""); setResetNotice("");}}
                                  className="text-[13px] font-semibold text-ink/55 hover:text-ink transition duration-300"
                                  style={{transitionTimingFunction:"var(--ease-glide)"}}>← 回到登录</button>
                          <button type="submit"
                                  className="group inline-flex items-center justify-between gap-2 rounded-full bg-copper px-5 py-3 text-[14px] font-bold text-parchment transition-all duration-400 active:scale-[0.98]"
                                  style={{transitionTimingFunction:"var(--ease-spring-in)", boxShadow:"var(--shadow-copper)"}}>
                            <span className="ml-2">下一步 →</span>
                            <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-0.5 group-hover:scale-105"
                                  style={{backgroundColor:"rgba(255,251,243,0.15)"}}>
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>
                              </svg>
                            </span>
                          </button>
                        </div>
                      </form>
                    </>
                  )}

                  {/* 第二步：新密码两次 */}
                  {resetStep === 2 && (
                    <>
                      <p className="text-[10px] font-bold tracking-[0.25em] text-copper">第二步 · 新密码</p>
                      <h3 className="mt-2 font-display text-2xl leading-tight text-ink">设置一个新密码。</h3>
                      <p className="mt-1 text-[13px] text-ink/60">至少 8 位，含字母+数字。改好后回到登录页，用新密码进门。</p>
                      <form onSubmit={confirmReset} className="mt-7 space-y-4">
                        {[
                          {label:"新密码（≥ 8 位）", v: resetPwd,  set: setResetPwd,  type:"password", ph:"********"},
                          {label:"再输一遍新密码",   v: resetPwd2, set: setResetPwd2, type:"password", ph:"********"},
                        ].map((f)=>(
                          <div key={f.label} className="rounded-[1rem] p-1 ring-1 ring-ink/10 transition duration-300 focus-within:ring-copper/30"
                               style={{backgroundColor:"var(--color-mist)", transitionTimingFunction:"var(--ease-glide)"}}>
                            <div className="relative rounded-[calc(1rem-0.25rem)] px-4 py-3"
                                 style={{backgroundColor:"var(--color-parchment)", boxShadow:"inset 0 1px 1px rgba(255,255,255,0.8)"}}>
                              <label className="pointer-events-none absolute left-4 origin-left transition-all duration-300"
                                     style={{
                                       top: f.v.length ? "6px" : "50%",
                                       transform: f.v.length ? "translateY(0) scale(0.78)" : "translateY(-50%) scale(1)",
                                       color: f.v.length ? "var(--color-copper)" : "rgba(28,35,41,0.5)",
                                       fontWeight: f.v.length ? 700 : 500,
                                       transitionTimingFunction: "var(--ease-glide)",
                                     }}>{f.label}</label>
                              <input type={f.type} value={f.v} onChange={(e)=>f.set(e.target.value)}
                                     className="w-full pt-[14px] bg-transparent text-[15px] text-ink outline-none"
                                     placeholder={f.v.length ? f.ph : ""}/>
                            </div>
                          </div>
                        ))}
                        {err && (
                          <div className="rounded-[0.9rem] px-4 py-2.5 flex items-start gap-2" style={{backgroundColor:"rgba(168,84,62,0.10)"}}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-rust)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0">
                              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                              <path d="M12 9v4"/>
                            </svg>
                            <p className="text-[12px] leading-relaxed font-semibold text-rust">{err}</p>
                          </div>
                        )}
                        <div className="flex items-center justify-between pt-3">
                          <button type="button" onClick={()=>{setResetStep(1); setErr("");}}
                                  className="text-[13px] font-semibold text-ink/55 hover:text-ink transition duration-300"
                                  style={{transitionTimingFunction:"var(--ease-glide)"}}>← 上一步</button>
                          <button type="submit" disabled={resetBusy}
                                  className="group inline-flex items-center justify-between gap-2 rounded-full bg-copper px-5 py-3 text-[14px] font-bold text-parchment transition-all duration-400 active:scale-[0.98] disabled:cursor-wait disabled:opacity-60"
                                  style={{transitionTimingFunction:"var(--ease-spring-in)", boxShadow:"var(--shadow-copper)"}}>
                            <span className="ml-2">{resetBusy ? "核对验证码中…" : "重置密码"}</span>
                            <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-0.5 group-hover:scale-105"
                                  style={{backgroundColor:"rgba(255,251,243,0.15)"}}>
                              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="20 6 9 17 4 12"/>
                              </svg>
                            </span>
                          </button>
                        </div>
                      </form>
                    </>
                  )}

                  {/* 第三步：成功大对勾卡 */}
                  {resetStep === 3 && (
                    <div className="animate-float-up py-6 text-center">
                      <div className="mx-auto grid size-20 place-items-center rounded-full" style={{backgroundColor:"var(--color-wheat)"}}>
                        <div className="grid size-16 place-items-center rounded-full" style={{backgroundColor:"var(--color-copper)", boxShadow:"var(--shadow-copper)"}}>
                          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#FFFDF7" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="animate-draw-check">
                            <polyline points="20 6 9 17 4 12"/>
                          </svg>
                        </div>
                      </div>
                      <h3 className="mt-6 font-display text-2xl leading-tight text-ink">密码改好啦。</h3>
                      <p className="mt-2 mx-auto max-w-[280px] text-[13px] leading-relaxed text-ink/65">
                        现在用新密码登录就行。
                      </p>
                      <div className="mt-8 flex justify-center gap-3">
                        <button
                          type="button"
                          onClick={()=>{ setResetStep(0); setResetEmail(""); setResetCode(""); setResetPwd(""); setResetPwd2(""); setResetCD(0); setResetNotice(""); setMode("login"); setErr(""); }}
                          className="group inline-flex items-center gap-2 rounded-full bg-copper px-5 py-3 text-[14px] font-bold text-parchment transition-all duration-400 active:scale-[0.98]"
                          style={{transitionTimingFunction:"var(--ease-spring-in)", boxShadow:"0 6px 20px rgba(94,133,119,0.28)"}}
                        >
                          <span className="ml-1">好，回登录页</span>
                          <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-0.5 group-hover:scale-105"
                                style={{backgroundColor:"rgba(255,253,247,0.14)"}}>
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#FFFDF7" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>
                            </svg>
                          </span>
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <>
                  {/* 移动版品牌字 */}
                  <div className="mb-8 lg:hidden">
                    <div className="font-display text-4xl tracking-[0.25em] text-ink">伴考</div>
                    <p className="mt-1 text-xs text-ink/50">长期陪伴式备考教练</p>
                  </div>

                  {/* Segmented 滑动胶囊 */}
                  <div className="relative mb-8 inline-flex w-full items-stretch rounded-full bg-mist p-1">
                    <div aria-hidden className="absolute top-1 bottom-1 z-0 w-1/2 rounded-full"
                         style={{
                           backgroundColor:"var(--color-copper)",
                           transform: mode==="register" ? "translateX(0%)" : "translateX(100%)",
                           transition:"transform 500ms var(--ease-spring-out), background-color 300ms var(--ease-glide)",
                           boxShadow:"var(--shadow-float-sm)",
                         }}/>
                    {segOpts.map(([k,t]) => {
                      const active = mode === k;
                      return (
                        <button key={k} type="button"
                                onClick={()=>{ setMode(k); setErr(""); }}
                                className="relative z-10 flex-1 rounded-full px-5 py-2.5 text-[14px] font-bold transition-colors duration-300"
                                style={{
                                  color: active ? "var(--color-parchment)" : "rgba(28,35,41,0.78)",
                                  transitionTimingFunction: "var(--ease-glide)",
                                }}>{t}</button>
                      );
                    })}
                  </div>

                  {/* 登录 / 注册表单 */}
                  <form onSubmit={submit} className="space-y-4">
                    <div><FloatInput label="邮箱" value={email} onChange={setEmail} type="email" inputMode="email" autoComplete="email" placeholder="you@example.com"/></div>
                    {mode === "register" && (
                      <div>
                        <FloatInput
                          label="邮箱验证码" value={code} onChange={setCode} inputMode="numeric" maxLength={6} placeholder="6位数字"
                          trailing={
                            <button type="button" disabled={cooldown>0 || sending} onClick={()=>void sendCode()}
                                    className="group ml-1 inline-flex shrink-0 items-center gap-2 rounded-full border border-ink/15 bg-cream px-4 py-2 text-[12px] font-semibold text-ink/75 transition-all duration-300 hover:border-copper/40 hover:text-copper disabled:cursor-not-allowed disabled:opacity-70"
                                    style={{transitionTimingFunction:"var(--ease-glide)"}}>
                              <CooldownRing cooldown={cooldown}/>
                              <span className="tabular-nums">{cooldown>0 ? `秒后重发` : sending ? "寄信中…" : "发送验证码"}</span>
                            </button>
                          }
                        />
                      </div>
                    )}
                    <div>
                      <FloatInput
                        label="密码" value={pwd} onChange={setPwd} type="password"
                        autoComplete={mode==="login" ? "current-password" : "new-password"}
                        placeholder="至少 8 位字母或数字"
                      />
                    </div>
                    {err && (
                      <div role="alert" className="mt-1">
                        <div className="rounded-[1rem] p-1 ring-1 ring-rust/25" style={{backgroundColor:"rgba(168,84,62,0.10)"}}>
                          <div className="flex items-start gap-2 rounded-[calc(1rem-0.25rem)] px-3 py-2.5"
                               style={{backgroundColor:"rgba(255,251,243,0.95)", boxShadow:"inset 0 1px 1px rgba(255,255,255,0.6)"}}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-rust)" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0">
                              <path d="M12 9v4M12 17h.01"/>
                              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                            </svg>
                            <p className="text-[13px] leading-relaxed text-rust">{err}</p>
                          </div>
                        </div>
                      </div>
                    )}
                    {notice && (
                      <div role="status" className="rounded-[1rem] px-4 py-2.5 text-[12px] font-semibold"
                           style={{backgroundColor:"rgba(91,115,120,0.12)", color:"#3E6B5A"}}>{notice}</div>
                    )}
                    <div className="pt-3">
                      <button type="submit" disabled={busy}
                              className="group inline-flex w-full items-center justify-between gap-3 rounded-full bg-copper px-6 py-3.5 text-[15px] font-bold transition-all duration-400 active:scale-[0.98] disabled:cursor-wait disabled:opacity-60"
                              style={{color:"#FFFDF7", transitionTimingFunction:"var(--ease-spring-in)", boxShadow:"0 6px 20px rgba(94,133,119,0.28)"}}>
                        <span className="ml-3 tracking-wide">{busy ? "连线后端中…" : mode==="register" ? "注册并进入" : "登录"}</span>
                        <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-1 group-hover:scale-105"
                              style={{backgroundColor:"rgba(255,253,247,0.14)", transitionTimingFunction:"var(--ease-spring-in)"}}>
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#FFFDF7" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>
                          </svg>
                        </span>
                      </button>
                    </div>
                  </form>

                  {/* 演示提示 */}
                  <div className="mt-7">
                    <div className="rounded-full px-4 py-3 text-center text-[12px] leading-relaxed"
                         style={{backgroundColor:"var(--color-mist)", color:"rgba(28,35,41,0.6)"}}>
                      验证码 <span className="font-mono font-bold text-ink">真实邮件发送</span>（已接入服务端）
                      <span className="mx-1.5">·</span>
                      开放注册：凭邮箱验证码即可注册进门，<span className="font-mono font-bold text-ink">无邀请码门槛</span>（D54 已退役）
                      <br className="sm:hidden"/>
                      <span className="text-ink/45">账号为填写邮箱，登录凭证本地保存7天，刷新页面不掉线</span>
                    </div>
                  </div>

                  {/* D. 忘记密码入口（仅 login 模式） */}
                  {mode === "login" && (
                    <div className="mt-6 text-center">
                      <button type="button"
                              onClick={()=>{ setResetStep(1); if(email.length) setResetEmail(email); setErr(""); setResetNotice(""); }}
                              className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-copper transition duration-300 hover:text-copper-dk"
                              style={{transitionTimingFunction:"var(--ease-glide)"}}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <rect x="3" y="11" width="18" height="11" rx="2"/>
                          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                        </svg>
                        忘记密码？用邮箱重置
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
