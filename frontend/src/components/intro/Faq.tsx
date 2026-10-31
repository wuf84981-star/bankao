/* ============================================================
 * 介绍页 · 常见问题（原生 details 手风琴，零 JS 状态）
 * 答案只写项目真做到的事；做不到的直接说边界
 * ============================================================ */

import type { ReactElement } from "react";
import IntroIcon from "./Icons";
import Reveal from "../Reveal";

type QA = { q: string; a: ReactElement };

const FAQS: QA[] = [
  {
    q: "我不太会用 AI，会不会一进去不知道说什么？",
    a: (
      <>
        进门落在「对话」页，那里就是主入口。你只需要交代三件事：
        <b className="font-bold text-ink">考什么、哪天考、每天能学多久</b>。
        说完它会主动问你要不要排计划，你回「排」「确认」就行。
        计划页、资料页、记忆页是给它记账的本子，不是你必须先学会操作的东西。
      </>
    ),
  },
  {
    q: "注册要邀请码吗？收不到验证码怎么办？",
    a: (
      <>
        不要邀请码，凭邮箱验证码即可注册。验证码 10 分钟内有效，
        没收到先去垃圾箱翻翻——QQ 邮箱最容易把它当垃圾邮件。
        密码至少 8 位且含字母和数字；忘了密码走「忘记密码」，同样是邮箱验证码重置。
      </>
    ),
  },
  {
    q: "我的错题和学习记录存在哪里？别人能看到吗？",
    a: (
      <>
        存在这套系统自己的库里，不寄存在第三方 SaaS。
        每一手操作的查询都强制带上你的用户身份做闸门，跨户取账直接查空——
        不存在「换个 id 看看别人数据」的路。
      </>
    ),
  },
  {
    q: "它会不会像普通大模型那样瞎编答案？",
    a: (
      <>
        三处收口：讲义里查不到就明说「知识库无相关资料」，不靠常识补；
        客观题对错由程序裁决，不由模型嘴说；计划落库前要过纯函数校验墙，
        每日总量超载会整版打回重排。模型只负责提议，规则由代码执法。
      </>
    ),
  },
  {
    q: "一定要在网页上用吗？手机上怎么办？",
    a: (
      <>
        网页端全部页面适配手机，浏览器打开就能用，底部是触摸导航。
        另外可以绑定 QQ 作为第二条通道：在设置页拿 6 位绑定码，QQ 私聊发码即通，
        两边共用同一本账。QQ 走第三方协议、登录态可能掉线，所以定位是可选体验通道，
        核心功能永远以网页端为主腿——掉线期间数据零丢失，重连后历史依然完整。
      </>
    ),
  },
  {
    q: "对话要花钱吗？积分怎么算？",
    a: (
      <>
        平台按积分计量，余额是从流水账加总出来的，没人能偷偷改数；
        签到和开池会给积分。你也可以在设置页挂上自己的 DeepSeek API Key，
        之后 DeepSeek 系对话烧你自己的平台余额、不扣本平台积分——
        积分见底的账号也能靠这把钥匙继续开口。
      </>
    ),
  },
];

export default function Faq({ onEnter }: { onEnter: () => void }): ReactElement {
  return (
    <section id="faq" className="mx-auto max-w-6xl scroll-mt-28 px-4 py-16 sm:px-6 lg:py-24">
      <div className="grid gap-8 lg:grid-cols-[0.85fr_1.15fr] lg:gap-12">
        <Reveal>
          <div className="lg:sticky lg:top-28">
            <p className="text-[11px] font-bold tracking-[0.22em] text-copper">先替你问了</p>
            <h2 className="mt-3 font-display text-[clamp(1.8rem,4.4vw,2.6rem)] leading-tight tracking-[0.04em] text-ink">
              第一次用会问的六个问题
            </h2>
            <p className="mt-4 text-[14px] leading-[1.85] text-ink/65">
              看完还有疑问，就直接进对话页问教练本人——它记得住你的情况，
              问它比问说明书快。
            </p>
            <button type="button" onClick={onEnter}
                    className="mt-6 inline-flex items-center gap-2 rounded-full px-5 py-3 text-[14px] font-bold transition-all duration-400 hover:brightness-[1.06] active:scale-[0.98]"
                    style={{
                      backgroundColor: "var(--color-copper)", color: "#FFFDF7",
                      boxShadow: "var(--shadow-copper)", transitionTimingFunction: "var(--ease-spring-in)",
                    }}>
              注册进去问它
              <IntroIcon name="arrow" size={15} strokeWidth={1.8} />
            </button>
          </div>
        </Reveal>

        <div className="space-y-3">
          {FAQS.map((item, i) => (
            <Reveal key={item.q} delay={i * 70}>
              <details className="group rounded-[1.4rem] p-1.5 ring-1 ring-ink/5 transition-all duration-300 hover:ring-copper/25 open:ring-copper/30"
                       style={{ backgroundColor: "var(--color-mist)", transitionTimingFunction: "var(--ease-glide)" }}>
                <summary className="flex cursor-pointer select-none items-center gap-3 rounded-[calc(1.4rem-0.375rem)] px-4 py-4"
                         style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)" }}>
                  <span className="grid size-7 shrink-0 place-items-center rounded-full text-copper ring-1 ring-copper/25">
                    <IntroIcon name="question" size={14} />
                  </span>
                  <span className="min-w-0 flex-1 text-[14px] font-bold leading-snug text-ink">{item.q}</span>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
                       className="shrink-0 text-ink/40 transition-transform duration-300 group-open:rotate-180">
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </summary>
                <div className="px-4 pb-1 pt-3">
                  <p className="border-l-2 pl-4 text-[13px] leading-[1.85] text-ink/70"
                     style={{ borderColor: "var(--color-copper)" }}>
                    {item.a}
                  </p>
                </div>
              </details>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
