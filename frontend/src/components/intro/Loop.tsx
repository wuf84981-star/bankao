/* ============================================================
 * 介绍页 · 学习闭环回流线
 * 六环成圈：档案 → 倒排计划 → 打卡 → 判分 → 强化出题 → 掌握度回写
 * 桌面用 SVG 圆环 + 节点；移动端退化成竖列步骤，同一份数据两种排法
 * ============================================================ */

import type { ReactElement } from "react";
import Reveal from "../Reveal";

type Node = { key: string; note: string };

const RING: Node[] = [
  { key: "考试档案", note: "考什么、哪天考、每天能学多久" },
  { key: "倒排计划", note: "读掌握度账，弱项加权铺开" },
  { key: "每日打卡", note: "说一声「完成了××」即记账" },
  { key: "判分归类", note: "客观题程序裁，错题进错误模式账" },
  { key: "强化出题", note: "额度＝未结案错题数" },
  { key: "掌握度回写", note: "影响下一轮排计划" },
];

/** 圆环节点坐标：从正上方起顺时针均分 */
function ringPos(i: number, total: number, r: number): { x: number; y: number } {
  const a = (i / total) * Math.PI * 2 - Math.PI / 2;
  return { x: 210 + r * Math.cos(a), y: 210 + r * Math.sin(a) };
}

export default function Loop(): ReactElement {
  const n = RING.length;
  const R = 150;

  return (
    <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6 lg:py-24">
      <Reveal>
        <div className="rounded-[2rem] p-1.5 ring-1 ring-ink/5"
             style={{ backgroundColor: "rgba(28,35,41,0.05)", boxShadow: "var(--shadow-float-lg)" }}>
          <div className="rounded-[calc(2rem-0.375rem)] px-5 py-10 sm:px-10 sm:py-14"
               style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.9)" }}>
            <div className="mx-auto max-w-2xl text-center">
              <p className="text-[11px] font-bold tracking-[0.22em] text-copper">为什么它记得你的账</p>
              <h2 className="mt-3 font-display text-[clamp(1.8rem,4.4vw,2.6rem)] leading-tight tracking-[0.04em] text-ink">
                学完不是结束，是下一轮的输入
              </h2>
              <p className="mt-4 text-[14px] leading-[1.85] text-ink/65">
                这六步不是六个功能页面，是一条回流线：每一次打卡和判分都会写回账本，
                下一次排计划时读的就是这本账。环环相扣，才有「陪伴」这两个字。
              </p>
            </div>

            {/* ===== 桌面圆环 ===== */}
            <div className="mt-10 hidden justify-center lg:flex">
              <svg width="420" height="420" viewBox="0 0 420 420" role="img" aria-label="学习闭环六环示意">
                <circle cx="210" cy="210" r={R} fill="none" stroke="var(--color-sand)" strokeWidth="1.5" strokeDasharray="4 6" />
                {RING.map((node, i) => {
                  const p = ringPos(i, n, R);
                  const q = ringPos((i + 1) % n, n, R);
                  return (
                    <g key={node.key}>
                      {/* 环上小箭头：指向下一环 */}
                      <circle cx={(p.x + q.x) / 2} cy={(p.y + q.y) / 2} r="2.5" fill="var(--color-copper)" opacity="0.55" />
                    </g>
                  );
                })}
                {RING.map((node, i) => {
                  const p = ringPos(i, n, R);
                  return (
                    <g key={`n-${node.key}`}>
                      <circle cx={p.x} cy={p.y} r="34" fill="var(--color-ink)" />
                      <circle cx={p.x} cy={p.y} r="34" fill="none" stroke="var(--color-copper)" strokeWidth="1" opacity="0.35" />
                      <text x={p.x} y={p.y} textAnchor="middle" dominantBaseline="central"
                            fontSize={node.key.length > 4 ? 10 : 11} fontWeight="700"
                            fill="var(--color-parchment)" fontFamily="var(--font-heading)">
                        {node.key}
                      </text>
                    </g>
                  );
                })}
                <text x="210" y="198" textAnchor="middle" fontSize="12" fontWeight="700"
                      letterSpacing="3" fill="var(--color-copper)" fontFamily="var(--font-heading)">
                  学习闭环
                </text>
                <text x="210" y="220" textAnchor="middle" fontSize="10" fill="rgba(31,42,51,0.45)"
                      fontFamily="var(--font-mono)">
                  loop
                </text>
              </svg>

              {/* 环旁注解列 */}
              <ul className="ml-10 flex max-w-sm flex-col justify-center gap-3">
                {RING.map((node, i) => (
                  <li key={node.key} className="flex items-start gap-3">
                    <span className="mt-0.5 font-mono text-[11px] font-bold tabular-nums"
                          style={{ color: "var(--color-copper)" }}>
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span className="text-[13px] leading-relaxed text-ink/70">
                      <b className="font-bold text-ink">{node.key}</b>
                      <span className="mx-1.5 text-sand">·</span>
                      {node.note}
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            {/* ===== 移动端 / 平板：竖列回流 ===== */}
            <ol className="mt-10 grid gap-3 lg:hidden">
              {RING.map((node, i) => (
                <li key={node.key} className="flex items-start gap-3 rounded-[1.1rem] px-4 py-3.5"
                    style={{ backgroundColor: "rgba(94,133,119,0.06)" }}>
                  <span className="grid size-7 shrink-0 place-items-center rounded-full font-mono text-[11px] font-bold"
                        style={{ backgroundColor: "var(--color-ink)", color: "var(--color-wheat)" }}>
                    {i + 1}
                  </span>
                  <span className="min-w-0">
                    <b className="block text-[13.5px] font-bold text-ink">{node.key}</b>
                    <span className="mt-0.5 block text-[12px] leading-relaxed text-ink/60">{node.note}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
