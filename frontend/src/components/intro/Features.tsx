/* ============================================================
 * 介绍页 · 能力面（六张卡 + 倒排示意图）
 * 文案全部来自 README「核心亮点」与后端实际能力，不写做不到的事
 * ============================================================ */

import type { ReactElement } from "react";
import IntroIcon, { type IntroIconName } from "./Icons";
import Reveal from "../Reveal";

type Feature = { icon: IntroIconName; title: string; body: string; tag: string };

const FEATURES: Feature[] = [
  {
    icon: "book", tag: "资料仓",
    title: "讲义传进去，它读给你听",
    body: "PDF / Word / TXT / MD 上传后自动切块入库，回答时走「向量语义 + 中文全文 + 关键词模糊」三路召回再融合排序，答案带出处。查不到就直说「知识库无相关资料」，不编。",
  },
  {
    icon: "compass", tag: "计划",
    title: "按考试日倒排，超载当场打回",
    body: "登记考试类型和日期后逐日铺任务，末日必须恰好是考试前一日；每日总量过校验墙，排不下就整版重排。日历总览、单日清单、页门打卡三视图都在计划页。",
  },
  {
    icon: "ledger", tag: "教学",
    title: "它引导思路，不替你答题",
    body: "教学状态机先问思路再给提示；客观题对错由程序裁决，不归模型嘴；主观题走要点对照加点评。严格讲义模式默认禁联网、禁常识补答。",
  },
  {
    icon: "stream", tag: "闭环",
    title: "错题归账，按账出强化",
    body: "错题自动归入错误模式账：老毛病计数、新错开账。强化题额度等于未结案错题数，答过的自动排除；判分回写掌握度，下一轮排计划就读这本账。",
  },
  {
    icon: "mail", tag: "记忆",
    title: "关于你的事，它自己记着",
    body: "考试档案、已确认事实、未确认推测、知识点掌握度、错误模式、有时效的生活事件——六本账在记忆页可查、可确认、可遗忘。它没确认的推测不会当成事实来用。",
  },
  {
    icon: "key", tag: "自带钥匙",
    title: "挂上自己的 Key，烧自己的额度",
    body: "设置页挂上 DeepSeek API Key 后，对话走你自己的平台余额、不扣本平台积分；钥匙只回掩码、存前可一键验真。也提供多平台模型热切换与人设、联网、费曼等开关。",
  },
];

export default function Features({ timelineImg }: { timelineImg: string }): ReactElement {
  return (
    <section id="features" className="mx-auto max-w-6xl scroll-mt-28 px-4 py-16 sm:px-6 lg:py-24">
      <Reveal>
        <div className="max-w-2xl">
          <p className="text-[11px] font-bold tracking-[0.22em] text-copper">它会做什么</p>
          <h2 className="mt-3 font-display text-[clamp(1.8rem,4.4vw,2.8rem)] leading-tight tracking-[0.04em] text-ink">
            一个教练该做的六件事
          </h2>
        </div>
      </Reveal>

      {/* 倒排示意：图 + 说明并置 */}
      <Reveal delay={80}>
        <div className="mt-10 grid items-center gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-[1.75rem] p-1.5 ring-1 ring-ink/5"
               style={{ backgroundColor: "var(--color-mist)", boxShadow: "var(--shadow-float)" }}>
            <div className="overflow-hidden rounded-[calc(1.75rem-0.375rem)]"
                 style={{ backgroundColor: "var(--color-parchment)" }}>
              <img src={timelineImg} alt="逐日倒排的任务格示意" width={1600} height={900}
                   decoding="async" className="aspect-[16/9] w-full object-cover" />
            </div>
          </div>
          <div className="rounded-[1.75rem] px-5 py-6 sm:px-7 sm:py-8"
               style={{ backgroundColor: "rgba(94,133,119,0.07)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.7)" }}>
            <p className="text-[11px] font-bold tracking-[0.18em] text-copper">倒排是什么</p>
            <p className="mt-3 text-[14px] leading-[1.9] text-ink/72">
              普通待办清单从「今天」往后堆，堆到考试前一天才发现堆不下。
              伴考反过来：先钉死考试日，再按每天能投入的时间往回铺，
              所以<b className="font-bold text-ink">每一天的量都是算过的</b>，
              积压了会提议整版重排，而不是让你背着还不清的账往前走。
            </p>
          </div>
        </div>
      </Reveal>

      <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((f, i) => (
          <Reveal key={f.title} delay={(i % 3) * 90}>
            <article className="group h-full rounded-[1.75rem] p-1.5 ring-1 ring-ink/5 transition-all duration-400 hover:-translate-y-1 hover:ring-copper/25"
                     style={{ backgroundColor: "var(--color-mist)", boxShadow: "var(--shadow-float-sm)", transitionTimingFunction: "var(--ease-glide)" }}>
              <div className="flex h-full flex-col rounded-[calc(1.75rem-0.375rem)] px-5 py-6"
                   style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)" }}>
                <div className="flex items-center gap-3">
                  <span className="grid size-10 shrink-0 place-items-center rounded-full transition-transform duration-400 group-hover:scale-105"
                        style={{ backgroundColor: "var(--color-ink)", color: "var(--color-wheat)" }}>
                    <IntroIcon name={f.icon} size={18} />
                  </span>
                  <span className="rounded-full px-2.5 py-1 text-[10px] font-bold tracking-[0.14em] text-copper ring-1 ring-copper/25">
                    {f.tag}
                  </span>
                </div>
                <h3 className="mt-4 font-heading text-[16px] font-bold leading-snug text-ink">{f.title}</h3>
                <p className="mt-2.5 text-[13px] leading-[1.8] text-ink/62">{f.body}</p>
              </div>
            </article>
          </Reveal>
        ))}
      </div>
    </section>
  );
}
