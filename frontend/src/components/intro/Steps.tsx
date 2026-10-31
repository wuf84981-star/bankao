/* ============================================================
 * 介绍页 · 「怎么用」四步
 * 步骤号用麦黄便利贴质感，连线走铜绿虚线；移动端竖排自动收线
 * ============================================================ */

import type { ReactElement } from "react";
import IntroIcon, { type IntroIconName } from "./Icons";
import Reveal from "../Reveal";

type Step = {
  no: string;
  title: string;
  icon: IntroIconName;
  body: string;
  say: string;      /* 可直接对教练说的话术示例 */
};

const STEPS: Step[] = [
  {
    no: "01", title: "进门：邮箱注册", icon: "mail",
    body: "填邮箱、收 6 位验证码、设一个 8 位以上含字母数字的密码，注册即进门。登录态本地保存 7 天，刷新页面不掉线。",
    say: "第一次进来只做这一件事，不用配任何钥匙。",
  },
  {
    no: "02", title: "交底：说清考试与时间", icon: "calendar",
    body: "在对话里一句话说清考什么、哪天考、工作日和周末各能学多久。它会存成考试档案，侧栏的倒计时便利贴立刻换成真天数。",
    say: "例：「我 12 月 20 号考考研数学一，工作日每晚 3 小时，周末 6 小时」",
  },
  {
    no: "03", title: "排账：让它倒排再确认", icon: "compass",
    body: "按考试日倒排逐日铺任务，末日恰好落在考前一天；超载会被校验墙整版打回重排。草案要你点头才生效，旧版本自动归档。",
    say: "例：「排」→ 看草案 →「确认生效」",
  },
  {
    no: "04", title: "每天：打卡、出题、判分", icon: "ledger",
    body: "学完对教练说「我完成了××」就记账；错题自动归错误模式账，按未结案错题数出强化题，答完判分回写掌握度，下次排计划读这本账。",
    say: "例：「今晚高数极限那组完成了，最后一题又错了」",
  },
];

export default function Steps(): ReactElement {
  return (
    <section id="how" className="mx-auto max-w-6xl scroll-mt-28 px-4 py-16 sm:px-6 lg:py-24">
      <Reveal>
        <div className="max-w-2xl">
          <p className="text-[11px] font-bold tracking-[0.22em] text-copper">怎么用 · 四步</p>
          <h2 className="mt-3 font-display text-[clamp(1.8rem,4.4vw,2.8rem)] leading-tight tracking-[0.04em] text-ink">
            不用学操作，只要会说话
          </h2>
          <p className="mt-4 text-[15px] leading-[1.85] text-ink/65">
            伴考的主入口是一个对话框。你交代得越具体，它排的账越准；
            所有该记住的东西它自己落到账本里，你不需要维护表格。
          </p>
        </div>
      </Reveal>

      <ol className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {STEPS.map((s, i) => (
          <Reveal key={s.no} delay={i * 90}>
            <li className="group h-full rounded-[1.75rem] p-1.5 ring-1 ring-ink/5 transition-all duration-400 hover:ring-copper/25"
                style={{ backgroundColor: "var(--color-mist)", boxShadow: "var(--shadow-float-sm)", transitionTimingFunction: "var(--ease-glide)" }}>
              <div className="flex h-full flex-col rounded-[calc(1.75rem-0.375rem)] px-5 py-6"
                   style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)" }}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[13px] font-black tabular-nums tracking-widest"
                        style={{ color: "var(--color-copper)" }}>
                    {s.no}
                  </span>
                  <span className="grid size-9 place-items-center rounded-full transition-transform duration-400 group-hover:scale-105"
                        style={{ backgroundColor: "var(--color-wheat)", color: "var(--color-ink)" }}>
                    <IntroIcon name={s.icon} size={17} />
                  </span>
                </div>
                <h3 className="mt-4 font-heading text-[17px] font-bold leading-snug text-ink">{s.title}</h3>
                <p className="mt-2 flex-1 text-[13px] leading-[1.8] text-ink/62">{s.body}</p>
                <p className="mt-4 rounded-[0.85rem] px-3 py-2.5 text-[11.5px] leading-relaxed text-ink-soft"
                   style={{ backgroundColor: "rgba(94,133,119,0.08)" }}>
                  {s.say}
                </p>
              </div>
            </li>
          </Reveal>
        ))}
      </ol>
    </section>
  );
}
