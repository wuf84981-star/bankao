/* ============================================================
 * 介绍页 · 落地首屏（未登录时先见本页，读懂了再进登录/注册）
 * 结构：顶栏 → Hero（文案 + 主视觉 + 双 CTA）→ 怎么用 → 能力 → 闭环 → 常见问题 → 尾 CTA
 * 视觉：沿用 index.css 令牌（暖奶油底 × 墨青 × 沉铜绿 × 麦黄便利贴）+ Double-Bezel 卡壳
 * ============================================================ */

import type { ReactElement } from "react";
import IntroIcon from "../components/intro/Icons";
import Faq from "../components/intro/Faq";
import Features from "../components/intro/Features";
import Loop from "../components/intro/Loop";
import Reveal from "../components/Reveal";
import Steps from "../components/intro/Steps";

/* 主视觉与示意图已本地化（2026-10-31 接入刀）：原 CDN 外链带 auth_key 会过期，
   首屏挂在人家域名上是事故隐患——图缩宽 1600 转 WebP 后随 dist 由 nginx 递送 */
const HERO_IMG = "/intro/hero-desk.webp";
const TIMELINE_IMG = "/intro/plan-timeline.webp";

/** 锚点滚动：介绍页内部导航，不引入路由库 */
function scrollTo(id: string): void {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* 顶栏右侧的次要入口 */
function GhostButton({ label, onClick }: { label: string; onClick: () => void }): ReactElement {
  return (
    <button type="button" onClick={onClick}
            className="rounded-full px-4 py-2 text-[13px] font-semibold text-ink/70 ring-1 ring-ink/10 transition-all duration-300 hover:text-copper hover:ring-copper/35 active:scale-[0.98]"
            style={{ backgroundColor: "var(--color-parchment)", transitionTimingFunction: "var(--ease-glide)" }}>
      {label}
    </button>
  );
}

/* 主 CTA：Nested CTA 胶囊 + 内嵌箭头岛（与登录页主按钮同一只手） */
function PrimaryButton({
  label, hint, onClick,
}: { label: string; hint?: string; onClick: () => void }): ReactElement {
  return (
    <button type="button" onClick={onClick}
            className="group inline-flex items-center justify-between gap-3 rounded-full px-6 py-3.5 text-[15px] font-bold transition-all duration-400 hover:brightness-[1.06] active:scale-[0.98]"
            style={{
              backgroundColor: "var(--color-copper)", color: "#FFFDF7",
              boxShadow: "var(--shadow-copper)", transitionTimingFunction: "var(--ease-spring-in)",
            }}>
      <span className="ml-2 tracking-wide">{label}</span>
      <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-1 group-hover:scale-105"
            style={{ backgroundColor: "rgba(255,253,247,0.14)" }}>
        {hint
          ? <span className="text-[11px] font-bold">{hint}</span>
          : <IntroIcon name="arrow" size={16} strokeWidth={1.8} />}
      </span>
    </button>
  );
}

export default function Intro({
  onEnter, onLogin,
}: { onEnter: () => void; onLogin: () => void }): ReactElement {
  return (
    <div className="relative z-[2] min-h-[100dvh] w-full overflow-x-hidden">
      {/* ============ 顶栏 ============ */}
      <header className="sticky top-0 z-40 px-4 pt-4 sm:px-6">
        <div className="mx-auto max-w-6xl rounded-[1.5rem] p-1.5 ring-1 ring-ink/5 backdrop-blur-md"
             style={{ backgroundColor: "rgba(221,215,200,0.82)" }}>
          <div className="flex items-center justify-between rounded-[calc(1.5rem-0.375rem)] px-4 py-3 sm:px-6"
               style={{ backgroundColor: "rgba(250,246,236,0.94)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)" }}>
            <div className="flex items-baseline gap-3">
              <span className="font-display text-2xl leading-none tracking-[0.22em] text-ink">伴考</span>
              <span className="hidden text-[11px] font-semibold tracking-[0.18em] text-ink/45 sm:inline">
                长期陪伴式备考教练
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => scrollTo("how")}
                      className="hidden rounded-full px-4 py-2 text-[13px] font-semibold text-ink/65 transition-colors duration-300 hover:text-copper sm:inline-flex"
                      style={{ transitionTimingFunction: "var(--ease-glide)" }}>
                怎么用
              </button>
              <GhostButton label="已有账号？登录" onClick={onLogin} />
            </div>
          </div>
        </div>
      </header>

      {/* ============ Hero ============ */}
      <section className="mx-auto max-w-6xl px-4 pb-4 pt-10 sm:px-6 lg:pt-16">
        <div className="grid items-center gap-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12">
          {/* 左：文案 + CTA */}
          <div className="animate-float-up">
            <p className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[11px] font-bold tracking-[0.16em] text-copper ring-1 ring-copper/25"
               style={{ backgroundColor: "rgba(94,133,119,0.08)" }}>
              <span className="size-1.5 rounded-full" style={{ backgroundColor: "var(--color-copper)" }} />
              网页 + QQ 双通道 · 账本记在你自己手里
            </p>
            <h1 className="mt-5 font-display text-[clamp(2.4rem,6vw,4rem)] leading-[1.12] tracking-[0.04em] text-ink">
              把备考这件事
              <br />
              <span className="text-copper">交给一个会记账的教练</span>
            </h1>
            <p className="mt-5 max-w-xl text-[15px] leading-[1.85] text-ink/70 sm:text-[16px]">
              登记考试日期，它按考试日<b className="font-bold text-ink">倒排</b>逐日铺任务；
              讲义传进去，它<b className="font-bold text-ink">读给你听</b>并带出处；
              错题自动归账、按账出强化、判分回写掌握度——
              下一次排计划，它读的就是这本账。
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <PrimaryButton label="立即使用 · 注册进入" onClick={onEnter} />
              <button type="button" onClick={() => scrollTo("how")}
                      className="group inline-flex items-center gap-2 rounded-full px-5 py-3.5 text-[14px] font-bold text-ink/75 ring-1 ring-ink/12 transition-all duration-300 hover:text-copper hover:ring-copper/40 active:scale-[0.98]"
                      style={{ backgroundColor: "var(--color-mist)", transitionTimingFunction: "var(--ease-glide)" }}>
                先看四步怎么用
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
                     className="transition-transform duration-300 group-hover:translate-y-0.5">
                  <path d="M12 5v14" /><path d="m6 13 6 6 6-6" />
                </svg>
              </button>
            </div>

            {/* 演示入口：沙箱侧免验证码的现成账号 */}
            <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-ink/55">
              <span className="inline-flex items-center gap-1.5">
                <IntroIcon name="key" size={14} />
                凭邮箱验证码即可注册，无邀请码门槛
              </span>
            </div>
          </div>

          {/* 右：主视觉 + 便利贴签名件 */}
          <div className="relative">
            <div className="rounded-[2rem] p-2 ring-1 ring-ink/5"
                 style={{ backgroundColor: "var(--color-mist)", boxShadow: "var(--shadow-float-lg)" }}>
              <div className="overflow-hidden rounded-[calc(2rem-0.5rem)]"
                   style={{ backgroundColor: "var(--color-parchment)" }}>
                <img src={HERO_IMG} alt="书桌上的讲义、笔记本与倒计时便利贴"
                     width={1200} height={900} decoding="async"
                     className="aspect-[4/3] w-full object-cover" />
              </div>
            </div>

            {/* 便利贴：与侧栏签名件同款麦黄 + 微倾斜 */}
            <div className="absolute -bottom-4 left-2 w-32 sm:-bottom-6 sm:left-6 sm:w-36">
              <div className="rounded-[1.25rem] p-1.5"
                   style={{
                     backgroundColor: "rgba(239,230,210,0.7)", transform: "rotate(-2deg)",
                     boxShadow: "var(--shadow-wheat)",
                   }}>
                <div className="px-3 py-3 text-center"
                     style={{
                       backgroundColor: "var(--color-wheat)", borderRadius: "calc(1.25rem - 0.375rem)",
                       boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)", color: "var(--color-ink)",
                     }}>
                  <div className="text-[9px] font-bold tracking-[0.16em] text-ink/70">登记考试日后</div>
                  <div className="mt-1 font-mono text-4xl font-black leading-none tabular-nums"
                       style={{ color: "var(--color-copper-dk)" }}>
                    D-day
                  </div>
                  <div className="mt-1 text-[9px] font-bold tracking-[0.14em] text-ink/70">逐日倒排</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 一句话能力条 */}
        <div className="mt-12 sm:mt-16">
          <div className="rounded-[1.5rem] p-1.5 ring-1 ring-ink/5" style={{ backgroundColor: "rgba(28,35,41,0.04)" }}>
            <div className="grid grid-cols-2 gap-y-4 rounded-[calc(1.5rem-0.375rem)] px-4 py-5 sm:grid-cols-4 sm:px-6"
                 style={{ backgroundColor: "var(--color-parchment)" }}>
              {[
                { icon: "stream", t: "流式打字机", d: "边想边答，带引用出处" },
                { icon: "ledger", t: "程序裁对错", d: "客观题不归模型嘴" },
                { icon: "backup", t: "每日自动备份", d: "整库 + 资料仓滚动留档" },
                { icon: "phone", t: "手机也能用", d: "全部页面适配移动端" },
              ].map((f) => (
                <div key={f.t} className="flex flex-col items-center gap-1.5 px-2 text-center">
                  <span className="text-copper"><IntroIcon name={f.icon as "stream"} size={18} /></span>
                  <span className="text-[13px] font-bold text-ink">{f.t}</span>
                  <span className="text-[11px] leading-snug text-ink/55">{f.d}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ============ 后续区块 ============ */}
      <Steps />
      <Features timelineImg={TIMELINE_IMG} />
      <Loop />
      <Faq onEnter={onEnter} />

      {/* ============ 尾 CTA ============ */}
      <section className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        <Reveal>
          <div className="overflow-hidden rounded-[2rem] p-1.5 ring-1 ring-ink/5"
               style={{ backgroundColor: "rgba(28,35,41,0.05)", boxShadow: "var(--shadow-float-lg)" }}>
            <div className="relative overflow-hidden rounded-[calc(2rem-0.375rem)] px-6 py-12 text-center sm:px-10 sm:py-16"
                 style={{ backgroundColor: "var(--color-ink)" }}>
              <div aria-hidden className="pointer-events-none absolute inset-0"
                   style={{ background: "radial-gradient(600px 320px at 50% 0%, rgba(94,133,119,0.22), transparent 70%)" }} />
              <div className="relative">
                <h2 className="font-display text-[clamp(1.6rem,4vw,2.4rem)] leading-tight tracking-[0.06em] text-parchment">
                  今天离考试还剩几天？
                </h2>
                <p className="mx-auto mt-3 max-w-lg text-[14px] leading-relaxed text-parchment/70">
                  注册后第一件事，就是把考试日期告诉它。剩下的账，它来记。
                </p>
                <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                  <button type="button" onClick={onEnter}
                          className="group inline-flex items-center justify-between gap-3 rounded-full px-6 py-3.5 text-[15px] font-bold transition-all duration-400 hover:brightness-[1.06] active:scale-[0.98]"
                          style={{
                            backgroundColor: "var(--color-wheat)", color: "var(--color-ink)",
                            boxShadow: "var(--shadow-wheat)", transitionTimingFunction: "var(--ease-spring-in)",
                          }}>
                    <span className="ml-2">立即使用 · 注册进入</span>
                    <span className="grid size-8 place-items-center rounded-full transition-transform duration-400 group-hover:translate-x-1"
                          style={{ backgroundColor: "rgba(31,42,51,0.10)" }}>
                      <IntroIcon name="arrow" size={16} strokeWidth={1.8} />
                    </span>
                  </button>
                  <button type="button" onClick={onLogin}
                          className="rounded-full px-5 py-3.5 text-[14px] font-bold text-parchment/85 ring-1 ring-parchment/25 transition-all duration-300 hover:text-parchment hover:ring-parchment/50">
                    已有账号，直接登录
                  </button>
                </div>
              </div>
            </div>
          </div>
        </Reveal>

        <p className="mt-8 text-center text-[11px] leading-relaxed text-ink/40">
          伴考 · BanKao — 私人备考 AI Agent。学习记录与错题本存在你自己的库里，不寄存在第三方。
        </p>
      </section>
    </div>
  );
}
