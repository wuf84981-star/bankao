/* ============================================================
 * 设置页 v2 · 高端沉稳感设计
 * 设计要点：
 *   - 三组 Double-Bezel 卡片架构（外 mist 壳 + 内 parchment 核，圆角差 0.5rem）
 *   - Eyebrow Tag + display 字体标题的编辑式排版
 *   - Float Label 浮动标签输入框：有值/聚焦上移缩小并变沉铜绿
 *   - 账号数据 4 行禁用态小卡：灰状态竖条 + 半透明 + hover 显亮 + 原生 title 提示
 *   - 保存按钮：Nested CTA 胶囊 + 内嵌对勾岛（hover 右移微放大 + active 按压缩放）
 *   - Toast：fixed 顶部中央滑入 / 滑出，2500ms 展示 + 350ms 出场后卸载
 *   - 过渡全部使用 var(--ease-glide) / var(--ease-spring-in) / var(--ease-spring-out)
 *   - 全中文 UI，图标使用内联 SVG 细线（strokeWidth ≤ 1.5）
 * 原功能逻辑保留：
 *   - state：name / remind / persona / customPrompt（初值来自 GET /api/settings/profile 真账）
 * D61 甲（2026-09-11）：整页从道具升级成真腿——四本账（名字/人设/自定义描述/提醒时点）
 *   与聊天口 set_agent_name、set_remind_time 同列同账；页面所见即数据库真相。
 * D62 甲（2026-09-11 用户拍板「为什么要个保存」）：全页自动落账——
 *   每个控件的完成动作（点卡/失焦/选时）即 POST 该字段，保存按钮拆除；
 *   booked ref 记「后端确认过的账」，落账失败当场回弹本地 state——选中态永不撒谎。
 * D81 挂招牌刀（2026-10-17）：教学轨用户开关进本页「教学 · 引导」组——
 *   独立端点 /api/settings/teaching 的独立账（enabled 布尔），三态语义与
 *   后端 user_teaching_on 同一判据：从没动过=开；关=考点问题回事务轨直答。
 * D89 费曼加招（2026-10-18 用户拍板）：同组第二闸「费曼式检验」——
 *   教学轨 15 招里「你讲我听」的意愿开关，/api/settings/feynman 独立账，
 *   同款三态（从没动过=开）；子闸从属大门：教学关了它无台可唱（文案标明）。
 * BYOK（2026-10-31 用户拍板「积分消耗太快，让用户自己接 DeepSeek」）：
 *   新增「模型钥匙 · 自带」组（OwnKeyPanel）——带钥期间 DeepSeek 系对话
 *   免扣积分；钥匙只回掩码、永不回显全文。
 * ============================================================ */

import { useEffect, useRef, useState } from "react";
import { api } from "../auth";

/** 后端 /api/settings/profile 的账形状（persona 兜底值由后端读侧统一给） */
type Profile = { name: string | null; persona: string; custom_prompt: string | null; remind_time: string | null };

/**
 * 设置页主组件：
 *   渲染"人设与命名 / 学习提醒 / 账号与数据"三组表单卡片，
 *   提供保存按钮与顶部滑入 Toast 提示。
 * @returns React.ReactNode 设置页 JSX
 */
export default function Settings() {
  const [name, setName] = useState("");
  const [remind, setRemind] = useState("");
  const [persona, setPersona] = useState("senior");
  const [customPrompt, setCustomPrompt] = useState("");
  const [teaching, setTeaching] = useState(true);   // D81：教学引导开关（初值=默认档「从没动过=开」）
  const [feynman, setFeynman] = useState(true);     // D89：费曼检验开关（初值=同款默认档「开」）
  const [saved, setSaved] = useState(false);
  const [closing, setClosing] = useState(false);
  const [toastMsg, setToastMsg] = useState("");   // 真话或报错都从这一个口出
  /**
   * 账号安全面板折叠态：默认收起，减少页面纵向滚动距离。
   * 用户点击标题区切换，true=展开 4 条禁用项。
   */
  const [accountOpen, setAccountOpen] = useState(false);

  /* D62 甲核心：booked=「后端确认过的账」基准。控件改动与基准比对，
     只发差量（复用 D61 端点的字段级语义：None=没改）；失败回弹基准——
     页面上的选中态永远等于账上的真相，不存在「忘了保存」。 */
  const booked = useRef({ name: "", persona: "senior", custom_prompt: "", remind_time: "", teaching: true, feynman: true });

  /* 开页灌真账：读失败不动本地 state（编辑到一半的字段不被网络故障吞掉） */
  useEffect(() => {
    api("/api/settings/profile")
      .then((d) => {
        const p = d as Profile;
        booked.current = {
          ...booked.current,   // teaching 是另一本账（独立端点），profile 落账不碰它
          name: p.name ?? "", persona: p.persona || "senior",
          custom_prompt: p.custom_prompt ?? "", remind_time: p.remind_time ?? "",
        };
        setName(booked.current.name);
        setPersona(booked.current.persona);
        setCustomPrompt(booked.current.custom_prompt);
        setRemind(booked.current.remind_time);
      })
      .catch(() => {});
  }, []);

  /* D81/D89：两把引导闸的账分家在这本——各自独立端点，读失败不动本地态（同上方家法） */
  useEffect(() => {
    api("/api/settings/teaching")
      .then((d) => {
        const t = (d as { enabled: boolean }).enabled;
        booked.current.teaching = t;
        setTeaching(t);
      })
      .catch(() => {});
    api("/api/settings/feynman")
      .then((d) => {
        const t = (d as { enabled: boolean }).enabled;
        booked.current.feynman = t;
        setFeynman(t);
      })
      .catch(() => {});
  }, []);

  /**
   * 单字段落账：成功→刷新基准+Toast 点名报账；失败→revert 回弹本地改动。
   * @param fields  只含本次改动字段的账片段
   * @param label   Toast 上的人话（如「人设=严师型」）
   * @param revert  失败时把对应 state 拨回基准的回调
   */
  function patch(fields: Record<string, string>, label: string, revert: () => void): void {
    api("/api/settings/profile", fields)
      .then(() => {
        booked.current = { ...booked.current, ...fields };
        showToast(`已落账：${label}`);
      })
      .catch((e) => {
        revert();
        showToast(e instanceof Error ? e.message : "没落上，已改回原样");
      });
  }

  /** 名字框失焦：与账上不同才发（空串=清账，后端把「起名」和「改名」一肩挑） */
  function commitName(): void {
    const v = name.trim();
    if (v === booked.current.name) return;
    patch({ name: v }, v ? `名字=『${v}』` : "名字已清空", () => setName(booked.current.name));
  }
  /** 自定义描述失焦：同上，没改不 Empty POST */
  function commitCustom(): void {
    const v = customPrompt.trim();
    if (v === booked.current.custom_prompt) return;
    patch({ custom_prompt: v }, v ? "自定义描述已更新" : "自定义描述已清空",
          () => setCustomPrompt(booked.current.custom_prompt));
  }
  /** D81：翻开关=意图完成，即 POST 独立账；失败回弹——选中态永不撒谎 */
  function flipTeaching(): void {
    const next = !teaching;
    setTeaching(next);
    api("/api/settings/teaching", { enabled: next })
      .then(() => {
        booked.current.teaching = next;
        showToast(next ? "已落账：教学引导=开" : "已落账：考点问题改直答");
      })
      .catch((e) => {
        setTeaching(!next);
        showToast(e instanceof Error ? e.message : "没落上，已改回原样");
      });
  }
  /** D89：费曼闸同款——即翻即 POST，失败回弹（大门关了这闸不登台，账照样存） */
  function flipFeynman(): void {
    const next = !feynman;
    setFeynman(next);
    api("/api/settings/feynman", { enabled: next })
      .then(() => {
        booked.current.feynman = next;
        showToast(next ? "已落账：费曼式检验=开" : "已落账：不再请你复述");
      })
      .catch((e) => {
        setFeynman(!next);
        showToast(e instanceof Error ? e.message : "没落上，已改回原样");
      });
  }
  /** Toast 展示节奏（D61 的动画骨架原样保留） */
  function showToast(msg: string): void {
    setToastMsg(msg);
    if (saved) return;          // 已在展示中：只换字不重播入场
    setClosing(false);
    setSaved(true);
    // 2.5s 后开始关闭动画
    setTimeout(() => setClosing(true), 2500);
    // 关闭动画 350ms 后卸载 Toast
    setTimeout(() => {
      setSaved(false);
      setClosing(false);
    }, 2500 + 350);
  }

  /* D65 续刀：QQ 绑定整件搬进本页（QqBindPanel 自带读账轮询）——
     账号区里不再挂指路行，功能在哪眼就在哪 */
  const accountRows: Array<{ label: string; hint: string; locked: boolean }> = [
    { label: "修改密码", hint: "本页暂未开放——去登录页走「忘记密码？」，邮件验证码重置（功能已上线）", locked: true },
    { label: "导出我的学习数据", hint: "此功能还没建", locked: true },
    { label: "注销账号", hint: "此功能还没建", locked: true },
  ];

  /* ---------- Float Label 活动态判断（name 输入框） ---------- */
  const nameActive = name.length > 0;
  /* ---------- Float Label 活动态判断（time 输入框） ---------- */
  const remindActive = remind.length > 0;

  return (
    <section className="flex-1 overflow-y-auto px-5 md:px-8 py-6 md:py-8 mb-20">
      <div className="max-w-5xl space-y-8 lg:space-y-10 mx-auto md:ml-0 md:mr-auto">
        {/* =========================================================
         *  组一：人设与命名
         * ========================================================= */}
        <div
          className="rounded-[1.75rem] p-2 ring-1 ring-ink/5"
          style={{ backgroundColor: "var(--color-mist)" }}
        >
          <div
            className="rounded-[calc(1.75rem-0.5rem)] p-5"
            style={{
              backgroundColor: "var(--color-parchment)",
              boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
            }}
          >
            {/* Eyebrow Tag */}
            <span
              className="mb-2 inline-block rounded-full px-3 py-1 text-[10px] font-bold tracking-[0.25em]"
              style={{
                backgroundColor: "rgba(28,35,41,0.10)",
                color: "rgba(28,35,41,0.70)",
              }}
            >
              人设 · 命名
            </span>
            {/* 组大标题 */}
            <h2 className="font-display text-2xl text-ink">教练的名字和身份</h2>

            {/* Float Label：教练叫什么 */}
            <div className="mt-6">
              <div
                className="rounded-[1rem] p-1 ring-1 ring-ink/10 transition-all duration-300 focus-within:ring-copper/30"
                style={{
                  backgroundColor: "var(--color-mist)",
                  transitionTimingFunction: "var(--ease-glide)",
                }}
              >
                <div
                  className="relative rounded-[calc(1rem-0.25rem)] px-4 py-3"
                  style={{
                    backgroundColor: "var(--color-parchment)",
                    boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
                  }}
                >
                  <label
                    htmlFor="coach-name"
                    className="pointer-events-none absolute left-4 origin-left transition-all duration-300"
                    style={{
                      top: nameActive ? "6px" : "50%",
                      transform: nameActive
                        ? "translateY(0) scale(0.78)"
                        : "translateY(-50%) scale(1)",
                      color: nameActive
                        ? "var(--color-copper)"
                        : "rgba(28,35,41,0.72)",
                      fontWeight: nameActive ? 700 : 600,
                      transitionTimingFunction: "var(--ease-glide)",
                    }}
                  >
                    教练叫什么
                  </label>
                  <input
                    id="coach-name"
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    onBlur={commitName}
                    maxLength={8}
                    placeholder={nameActive ? "比如：老考、小师妹" : ""}
                    className="w-full min-w-0 bg-transparent text-[15px] font-semibold text-ink pt-[14px] outline-none placeholder:text-ink/55"
                  />
                </div>
              </div>
            </div>

            {/* =========================================================
             *  C. 人设选择器 4 张 Double-Bezel 卡（PRD 3.1 F-07）
             *   严师型 墨青底 / 学长学姐型 铜绿底（默认选中）/ 学习搭子 麦黄底 / 自定义型 虚线
             * ========================================================= */}
            <div className="mt-8">
              <p className="mb-4 text-[10px] font-bold tracking-[0.25em] text-copper">选一种性格，或者自己写描述</p>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:gap-5">
                {[
                  { k:"strict", name:"严师型",    tag:"批评督促", desc:"不达标会提醒甚至批评，适合管不住自己的人。", color:"ink" as const },
                  { k:"senior", name:"学长/学姐型", tag:"过来人",   desc:"像考过的学长学姐，分享避坑指南和心得。",       color:"copper" as const },
                  { k:"buddy",  name:"学习搭子型",  tag:"平等陪伴", desc:"我们一起努力，像搭子互相鼓励。",                color:"wheat" as const },
                  { k:"custom", name:"自定义型",    tag:"自己描述", desc:"想让它怎么说话？温柔/毒舌/学术/幽默都可以。",   color:"custom" as const },
                ].map((p) => {
                  const active = persona === p.k;   // D61：选中态听账的，不再写死
                  const activeColor =
                    p.color === "ink"    ? "var(--color-ink)" :
                    p.color === "copper" ? "var(--color-copper)" :
                    p.color === "wheat"  ? "var(--color-wheat)" :
                                           "var(--color-mist)";
                  const textColor =
                    p.color === "ink" || p.color === "copper" ? "#FFFDF7" : "var(--color-ink)";
                  const badgeBg =
                    p.color === "ink" || p.color === "copper" ? "rgba(255,253,247,0.14)" : "rgba(28,35,41,0.08)";
                  const badgeColor =
                    p.color === "ink" || p.color === "copper" ? "#FFFDF7" : "var(--color-ink)";
                  return (
                    <div
                      key={p.k}
                      role="button" aria-pressed={active} tabIndex={0}
                      onClick={() => {
                        if (active) return;
                        setPersona(p.k);   // 先翻面给用户看，账若没落上 revert 会弹回来
                        patch({ persona: p.k }, `人设=${p.name}`,
                              () => setPersona(booked.current.persona));
                      }}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); (e.currentTarget as HTMLDivElement).click(); } }}
                      className="cursor-pointer rounded-[1.375rem] p-1.5 transition-all duration-300"
                      style={{
                        border: active
                          ? "2px solid var(--color-copper)"
                          : p.color === "custom"
                          ? "1px dashed rgba(28,35,41,0.25)"
                          : "1px solid rgba(28,35,41,0.08)",
                        borderRadius: "calc(1.375rem + 1.5px)",
                        transitionTimingFunction: "var(--ease-glide)",
                        boxShadow: active ? "var(--shadow-copper)" : undefined,
                      }}
                    >
                      <div
                        className="relative rounded-[1.375rem] px-5 py-5"
                        style={{
                          backgroundColor: activeColor,
                          boxShadow:
                            p.color === "custom" || p.color === "wheat"
                              ? "inset 0 1px 1px rgba(255,255,255,0.9)"
                              : "inset 0 1px 1px rgba(255,255,255,0.10)",
                        }}
                      >
                        {/* 选中态对勾岛 */}
                        {active && (
                          <span
                            className="absolute right-3 top-3 grid size-6 place-items-center rounded-full"
                            style={{ backgroundColor: "var(--color-parchment)" }}
                          >
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--color-copper)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
                          </span>
                        )}
                        <div className="flex items-center justify-between gap-2">
                          <p className="font-display text-[18px] font-bold" style={{color:textColor}}>{p.name}</p>
                          <span
                            className="rounded-full px-2.5 py-0.5 text-[10px] font-semibold"
                            style={{ backgroundColor: badgeBg, color: badgeColor }}
                          >{p.tag}</span>
                        </div>
                        <p className="mt-2 text-[12px] leading-relaxed font-semibold"
                           style={{
                             color:
                               p.color === "custom" ? "rgba(28,35,41,0.78)" :
                               p.color === "wheat"  ? "rgba(28,35,41,0.88)" :
                                                    "#FFFDF7",
                           }}>{p.desc}</p>
                        {p.color === "custom" && active && (
                          <textarea
                            value={customPrompt}
                            onChange={(e) => setCustomPrompt(e.target.value)}
                            onBlur={commitCustom}
                            maxLength={500}
                            placeholder="想让它怎么跟你说话？比如：像教练一样短促直接，只说重点，每次末尾催我去做题…"
                            rows={2}
                            className="mt-4 w-full rounded-[0.8rem] border border-ink/10 bg-parchment px-3 py-2.5 text-[12px] leading-relaxed text-ink outline-none focus:border-copper/30"
                          />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="mt-5 text-[11px] font-semibold leading-relaxed text-ink/50">
                PRD 规则：切换人设不影响已存的记忆；自定义底线 = 不得要求代写申论 / 辱骂用户（内容安全模板）。
              </p>
            </div>
          </div>
        </div>

        {/* =========================================================
         *  组一·B：教学 · 引导（D81 挂招牌刀）
         *   独立账独立端点；开关行沿用账号区「竖条+文字+右控件」骨架，
         *   竖条铜/灰直接把账上状态画给眼看（同「一眼分虚实」家法）。
         * ========================================================= */}
        <div
          className="rounded-[1.75rem] p-2 ring-1 ring-ink/5"
          style={{ backgroundColor: "var(--color-mist)" }}
        >
          <div
            className="rounded-[calc(1.75rem-0.5rem)] p-5"
            style={{
              backgroundColor: "var(--color-parchment)",
              boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
            }}
          >
            <span
              className="mb-2 inline-block rounded-full px-3 py-1 text-[10px] font-bold tracking-[0.25em]"
              style={{
                backgroundColor: "rgba(28,35,41,0.10)",
                color: "rgba(28,35,41,0.70)",
              }}
            >
              教学 · 引导
            </span>
            <h2 className="font-display text-2xl text-ink">教练怎么带你做题</h2>

            {/* 开关行：点整行都可翻（button 包全行，触达面积大） */}
            <button
              type="button" role="switch" aria-checked={teaching}
              onClick={flipTeaching}
              className="group mt-6 w-full rounded-[1rem] p-1 text-left ring-1 ring-ink/5 transition-all duration-300 hover:ring-copper/30"
              style={{
                backgroundColor: "rgba(243,240,234,0.70)",
                transitionTimingFunction: "var(--ease-glide)",
              }}
            >
              <div
                className="flex items-center gap-4 rounded-[calc(1rem-0.25rem)] px-4 py-3"
                style={{ backgroundColor: "rgba(255,251,243,0.50)" }}
              >
                <div className={`h-7 w-1 shrink-0 rounded-full transition-colors duration-300 ${teaching ? "bg-copper/70" : "bg-ink/20"}`} />
                <div className="min-w-0 flex-1">
                  <div className="font-heading text-[15px] font-bold text-ink">苏格拉底式引导</div>
                  <div className="mt-0.5 text-[12px] font-bold text-ink/80">
                    开：考点问题翻资料、多轮反问带着想；关：教练直接给答案
                  </div>
                </div>
                {/* Toggle pill：48 宽 24 珠，位移=48-24-2×2=20px */}
                <span
                  className="relative inline-block h-7 w-12 shrink-0 rounded-full ring-1 ring-ink/10 transition-colors duration-300"
                  style={{
                    backgroundColor: teaching ? "var(--color-copper)" : "rgba(28,35,41,0.15)",
                    transitionTimingFunction: "var(--ease-glide)",
                  }}
                >
                  <span
                    className="absolute left-0.5 top-0.5 block size-6 rounded-full bg-parchment shadow transition-transform duration-300"
                    style={{
                      transform: teaching ? "translateX(20px)" : "translateX(0)",
                      transitionTimingFunction: "var(--ease-spring-in)",
                    }}
                  />
                </span>
              </div>
            </button>

            {/* D89 费曼闸：教学轨 15 招里「你讲我听」那招的意愿开关（子闸——大门关了无台可唱） */}
            <button
              type="button" role="switch" aria-checked={feynman}
              onClick={flipFeynman}
              className="group mt-3 w-full rounded-[1rem] p-1 text-left ring-1 ring-ink/5 transition-all duration-300 hover:ring-copper/30"
              style={{
                backgroundColor: "rgba(243,240,234,0.70)",
                transitionTimingFunction: "var(--ease-glide)",
              }}
            >
              <div
                className="flex items-center gap-4 rounded-[calc(1rem-0.25rem)] px-4 py-3"
                style={{ backgroundColor: "rgba(255,251,243,0.50)" }}
              >
                <div className={`h-7 w-1 shrink-0 rounded-full transition-colors duration-300 ${feynman ? "bg-copper/70" : "bg-ink/20"}`} />
                <div className="min-w-0 flex-1">
                  <div className="font-heading text-[15px] font-bold text-ink">费曼式检验</div>
                  <div className="mt-0.5 text-[12px] font-bold text-ink/80">
                    开：你说「懂了」时，教练请你用大白话讲一遍，讲不通处补漏；关：不用这招
                  </div>
                </div>
                {/* Toggle pill：与上闸同款 48 宽 24 珠 */}
                <span
                  className="relative inline-block h-7 w-12 shrink-0 rounded-full ring-1 ring-ink/10 transition-colors duration-300"
                  style={{
                    backgroundColor: feynman ? "var(--color-copper)" : "rgba(28,35,41,0.15)",
                    transitionTimingFunction: "var(--ease-glide)",
                  }}
                >
                  <span
                    className="absolute left-0.5 top-0.5 block size-6 rounded-full bg-parchment shadow transition-transform duration-300"
                    style={{
                      transform: feynman ? "translateX(20px)" : "translateX(0)",
                      transitionTimingFunction: "var(--ease-spring-in)",
                    }}
                  />
                </span>
              </div>
            </button>

            <p className="mt-4 text-[11px] font-semibold leading-relaxed text-ink/50">
              只管「怎么教」这一件事——排计划、设提醒、出题判分这些事务不经过这道闸。默认就是开；只要没关过，账上不留痕。
              费曼闸是教学轨内的子开关：苏格拉底开着才有教学，它才登台。
            </p>
          </div>
        </div>

        {/* =========================================================
         *  组二：学习提醒
         * ========================================================= */}
        <div
          className="rounded-[1.75rem] p-2 ring-1 ring-ink/5"
          style={{ backgroundColor: "var(--color-mist)" }}
        >
          <div
            className="rounded-[calc(1.75rem-0.5rem)] p-5"
            style={{
              backgroundColor: "var(--color-parchment)",
              boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
            }}
          >
            <span
              className="mb-2 inline-block rounded-full px-3 py-1 text-[10px] font-bold tracking-[0.25em]"
              style={{
                backgroundColor: "rgba(28,35,41,0.10)",
                color: "rgba(28,35,41,0.70)",
              }}
            >
              提醒 · 时间
            </span>
            <h2 className="font-display text-2xl text-ink">什么时候催你坐下来学</h2>
            <p className="text-[12px] font-semibold text-ink/70 mb-3 mt-1">
              我们会尽量温柔，不会在你下班路上轰炸。
            </p>

            {/* Float Label：time 输入框 */}
            <div className="w-full max-w-[280px]">
              <div
                className="rounded-[1rem] p-1 ring-1 ring-ink/10 transition-all duration-300 focus-within:ring-copper/30"
                style={{
                  backgroundColor: "var(--color-mist)",
                  transitionTimingFunction: "var(--ease-glide)",
                }}
              >
                <div
                  className="relative rounded-[calc(1rem-0.25rem)] px-4 py-3"
                  style={{
                    backgroundColor: "var(--color-parchment)",
                    boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
                  }}
                >
                  <label
                    htmlFor="remind-time"
                    className="pointer-events-none absolute left-4 origin-left transition-all duration-300"
                    style={{
                      top: remindActive ? "6px" : "50%",
                      transform: remindActive
                        ? "translateY(0) scale(0.78)"
                        : "translateY(-50%) scale(1)",
                      color: remindActive
                        ? "var(--color-copper)"
                        : "rgba(28,35,41,0.72)",
                      fontWeight: remindActive ? 700 : 600,
                      transitionTimingFunction: "var(--ease-glide)",
                    }}
                  >
                    每天这个时间，QQ 上催你
                  </label>
                  <input
                    id="remind-time"
                    type="time"
                    value={remind}
                    onChange={(e) => {
                      const v = e.target.value;
                      setRemind(v);
                      // time 控件只在选完整时才出值，选上=意图完成，直接落账
                      patch({ remind_time: v }, v ? `提醒=${v}` : "提醒已清空（回默认档）",
                            () => setRemind(booked.current.remind_time));
                    }}
                    className="w-full min-w-0 bg-transparent text-[15px] text-ink pt-[14px] outline-none"
                  />
                </div>
              </div>
            </div>

            <p className="mt-3 text-[12px] font-semibold text-ink/65">
              提醒靠 QQ 机器人送达（S6 已上线）——到点调度器读这本账拼当日计划催你，不烧大脑 token。
            </p>
          </div>
        </div>

        {/* =========================================================
         *  组二·B：模型钥匙 · 自带（BYOK 2026-10-31 用户拍板：积分消耗太快，
         *  接自己的 DeepSeek——带钥期间 DeepSeek 系对话免扣积分，烧自家油）
         * ========================================================= */}
        <OwnKeyPanel />

        {/* =========================================================
         *  组三：QQ 绑定（D65 续刀：整件从侧栏搬来——侧栏窄塞不下好友码）
         * ========================================================= */}
        <QqBindPanel />

        {/* =========================================================
         *  组四：账号与数据（3 行禁用态）
         * ========================================================= */}
        <div
          className="rounded-[1.75rem] p-2 ring-1 ring-ink/5"
          style={{ backgroundColor: "var(--color-mist)" }}
        >
          <div
            className="rounded-[calc(1.75rem-0.5rem)] p-5"
            style={{
              backgroundColor: "var(--color-parchment)",
              boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
            }}
          >
            {/* 标题区：可点击切换折叠；默认收起减少纵向滚动 */}
            <button
              type="button"
              onClick={() => setAccountOpen(!accountOpen)}
              aria-expanded={accountOpen}
              className="flex w-full items-start justify-between gap-4 text-left"
            >
              <div className="min-w-0">
                <span
                  className="mb-2 inline-block rounded-full px-3 py-1 text-[10px] font-bold tracking-[0.25em]"
                  style={{
                    backgroundColor: "rgba(28,35,41,0.10)",
                    color: "rgba(28,35,41,0.70)",
                  }}
                >
                  账号 · 数据
                </span>
                <h2 className="font-display text-2xl text-ink">账号安全和数据主权</h2>
              </div>
              {/* Chevron 箭头：展开时旋转 180°，spring-out 过渡 */}
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="mt-1 shrink-0 text-ink/60 transition-transform duration-300"
                style={{
                  transform: accountOpen ? "rotate(180deg)" : "rotate(0deg)",
                  transitionTimingFunction: "var(--ease-spring-out)",
                }}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </button>

            {/* 折叠内容容器：grid-rows 0fr→1fr 平滑动画，溢出隐藏 */}
            <div
              className="grid transition-all duration-300"
              style={{
                gridTemplateRows: accountOpen ? "1fr" : "0fr",
                transitionTimingFunction: "var(--ease-spring-out)",
              }}
            >
              <div className="overflow-hidden">
                <div className="mt-6 space-y-3">
                  {accountRows.map((r) => (
                    <div
                      key={r.label}
                      className={`group rounded-[1rem] p-1 ring-1 ring-ink/5 ${r.locked ? "cursor-not-allowed" : ""}`}
                      style={{
                        backgroundColor: r.locked ? "rgba(243,240,234,0.70)" : "rgba(255,251,243,0.70)",
                      }}
                    >
                      <div
                        className={`flex items-center gap-4 rounded-[calc(1rem-0.25rem)] px-4 py-3 transition duration-300 ${r.locked ? "opacity-70 group-hover:opacity-85" : ""}`}
                        style={{
                          backgroundColor: "rgba(255,251,243,0.50)",
                          transitionTimingFunction: "var(--ease-glide)",
                        }}
                      >
                        {/* 状态竖条：锁行灰、活账铜色——一眼分虚实 */}
                        <div className={`w-1 h-7 rounded-full shrink-0 ${r.locked ? "bg-ink/20" : "bg-copper/70"}`} />
                        {/* 文字区 */}
                        <div className="flex-1 min-w-0">
                          <div className="font-heading text-[15px] font-bold text-ink">
                            {r.label}
                          </div>
                          <div className="text-[12px] font-bold text-ink/80 mt-0.5">{r.hint}</div>
                        </div>
                        {/* 右侧锁图标：只挂真没做的行（D63：锁的出现本身不再撒谎） */}
                        {r.locked && (
                        <svg
                          width="18"
                          height="18"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="shrink-0 text-ink/75"
                        >
                          <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                        </svg>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* 分割线：与账号项隔开 */}
            <div className="my-5 h-px w-full" style={{ backgroundColor: "var(--color-mist)" }} />

            {/* D62 甲：保存按钮已拆——本页不存在「改了没生效」的中间态，
                每个控件的完成动作（点卡/失焦/选时）即时落账，顶部 Toast 点名报账 */}
            <p className="text-[12px] font-semibold text-ink/60">
              这一页没有保存钮——改动即时落账，顶部的『已落账』提示就是回执。
            </p>
          </div>
        </div>
      </div>

      {/* =========================================================
       *  Toast：顶部中央滑入滑出（saved 为真才渲染）
       * ========================================================= */}
      {saved && (
        <div
          className="fixed top-6 left-1/2 z-50 -translate-x-1/2"
          style={{ willChange: "transform, opacity" }}
        >
          <div
            className={`p-1 rounded-full ring-1 ring-copper/20 backdrop-blur-xl ${
              closing ? "animate-toast-out" : "animate-toast-in"
            }`}
            style={{ backgroundColor: "rgba(98,117,122,0.10)" }}
          >
            <div
              className="rounded-full px-5 py-2.5 text-[13px] font-bold"
              style={{
                backgroundColor: "rgba(255,251,243,0.90)",
                color: "var(--color-copper)",
                boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)",
              }}
            >
              {toastMsg}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

/* ============================================================
 * BYOK 自带钥匙功能组（2026-10-31 用户拍板：积分消耗太快，接自己的 DeepSeek）：
 * 账走 /api/settings/ownkey 三端点——GET 只回掩码、POST 空串=清除、/test 真验钥。
 * 语义说在人话里：带钥=DeepSeek 系对话烧自家油不扣积分；非 DeepSeek 平台不吃这把钥；
 * 日 token 配额仍守（防失控）。钥匙永不回显全文：存后只剩掩码行，输入框 password 型、存完即清。
 * ============================================================ */
function OwnKeyPanel() {
  const [configured, setConfigured] = useState(false);
  const [masked, setMasked] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [msgOk, setMsgOk] = useState(false);

  useEffect(() => {
    api("/api/settings/ownkey")
      .then((d) => {
        const r = d as { configured: boolean; masked: string | null };
        setConfigured(r.configured);
        setMasked(r.masked);
      })
      .catch(() => {});   // 读失败只是状态行空着，不打扰页面其余账
  }, []);

  /** 本组回执走页内一行（与 QqBindPanel 同款不自重定向 Toast，报错就近看得见） */
  function flash(ok: boolean, text: string): void { setMsgOk(ok); setMsg(text); }

  async function save(): Promise<void> {
    const k = draft.trim();
    if (!k) { flash(false, "先把钥匙贴进来再存"); return; }
    setBusy(true);
    try {
      const d = (await api("/api/settings/ownkey", { key: k })) as { configured: boolean; masked: string | null };
      setConfigured(d.configured); setMasked(d.masked); setDraft("");
      flash(true, "已落账：自带钥匙存好——DeepSeek 系对话从此不扣积分");
    } catch (e) { flash(false, (e as Error).message); }
    finally { setBusy(false); }
  }

  async function test(): Promise<void> {
    setBusy(true);
    try {
      // 有草稿先验草稿（存前验真），没草稿验账上存的
      const d = (await api("/api/settings/ownkey/test",
                           { key: draft.trim() || null })) as { ok: boolean; msg: string };
      flash(d.ok, d.msg);
    } catch (e) { flash(false, (e as Error).message); }
    finally { setBusy(false); }
  }

  async function clear(): Promise<void> {
    setBusy(true);
    try {
      await api("/api/settings/ownkey", { key: "" });
      setConfigured(false); setMasked(null); setDraft("");
      flash(true, "自带钥匙已清除——回到积分计费");
    } catch (e) { flash(false, (e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{ backgroundColor: "var(--color-mist)" }}>
      <div className="rounded-[calc(1.75rem-0.5rem)] p-5"
           style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)" }}>
        <span className="mb-2 inline-block rounded-full px-3 py-1 text-[10px] font-bold tracking-[0.25em]"
              style={{ backgroundColor: "rgba(28,35,41,0.10)", color: "rgba(28,35,41,0.70)" }}>
          钥匙 · 自带
        </span>
        <h2 className="font-display text-2xl text-ink">接上你自己的 DeepSeek 钥匙</h2>
        <p className="mt-1 text-[12px] font-semibold leading-relaxed text-ink/70">
          去 platform.deepseek.com 注册并充值，建一把 API Key 贴进来。存好之后，
          DeepSeek 系模型的对话烧的是你自己在 DeepSeek 的余额，<b className="text-copper">不再扣本平台积分</b>；
          通义 / 智谱的型号不吃这把钥匙，照旧积分计费。每日 token 配额仍会守（防失控）。
        </p>

        {/* 状态行：存过=掩码 + 清除钮；没存=灰条说明（一眼分虚实，同本页家法） */}
        <div className="mt-4 rounded-[1rem] p-1 ring-1 ring-ink/5"
             style={{ backgroundColor: "rgba(243,240,234,0.70)" }}>
          <div className="flex items-center gap-4 rounded-[calc(1rem-0.25rem)] px-4 py-3"
               style={{ backgroundColor: "rgba(255,251,243,0.50)" }}>
            <div className={`h-7 w-1 shrink-0 rounded-full ${configured ? "bg-copper/70" : "bg-ink/20"}`} />
            <div className="min-w-0 flex-1">
              <div className="font-heading text-[15px] font-bold text-ink">
                {configured ? "自带钥匙在账上" : "还没存自带钥匙"}
              </div>
              <div className="mt-0.5 font-mono text-[12px] font-semibold text-ink/70">
                {configured ? masked : "现在烧平台积分；存一把就换你自己的油"}
              </div>
            </div>
            {configured && (
              <button type="button" onClick={clear} disabled={busy}
                      className="shrink-0 rounded-full border border-copper/40 px-4 py-1.5 text-[12px] font-bold text-copper transition-colors duration-300 hover:bg-copper/10 disabled:opacity-50">
                清除
              </button>
            )}
          </div>
        </div>

        {/* 钥匙输入：password 型防肩窥；存完即清空，页面永不回显全文（要看状态看掩码行） */}
        <div className="mt-4">
          <div className="rounded-[1rem] p-1 ring-1 ring-ink/10 transition-all duration-300 focus-within:ring-copper/30"
               style={{ backgroundColor: "var(--color-mist)", transitionTimingFunction: "var(--ease-glide)" }}>
            <input type="password" autoComplete="off" spellCheck={false} value={draft}
                   onChange={(e) => setDraft(e.target.value)}
                   placeholder="sk-…　从 platform.deepseek.com 建钥匙后粘这里"
                   className="w-full rounded-[calc(1rem-0.25rem)] bg-parchment px-4 py-3 text-[14px] font-semibold text-ink outline-none placeholder:text-ink/45" />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" onClick={save} disabled={busy || !draft.trim()}
                    className="rounded-full px-5 py-2 text-[13px] font-bold text-parchment shadow-copper transition-transform duration-300 active:scale-95 disabled:opacity-50"
                    style={{ backgroundColor: "var(--color-copper)" }}>
              存钥匙
            </button>
            <button type="button" onClick={test} disabled={busy || (!draft.trim() && !configured)}
                    className="rounded-full border border-copper/40 px-4 py-1.5 text-[12px] font-bold text-copper transition-colors duration-300 hover:bg-copper/10 disabled:opacity-50">
              测试连通
            </button>
            {msg && (
              <span className={`text-[11px] font-semibold ${msgOk ? "text-copper" : "text-ink/70"}`}>{msg}</span>
            )}
          </div>
        </div>

        <p className="mt-4 text-[11px] font-semibold leading-relaxed text-ink/50">
          诚实边界：钥匙以明文存在你账号的设置行里（熟人期现状，公网开放前会改加密存储）；
          页面与日志只出现掩码。删钥匙随时可，删完立刻回到积分计费。
        </p>
      </div>
    </div>
  );
}

/* ============================================================
 * QQ 绑定功能组（D65 续刀 · 2026-09-12 用户拍板「把绑定 QQ 放到设置里」）：
 * 原侧栏 QqBindCard 整件搬家——三态形状不变（未绑→加好友指路+拿码钮 /
 * pending→大号 6 位码+每秒巡绑成自动翻态 / bound→状态+换绑），
 * 皮换成本页 Double-Bezel 浅色骨架；bot 号读后端账（binding.bot_number），
 * 前端不抄第二份；好友码图在 frontend/public/qq_friend_qrcode.jpg，
 * 图缺退占位文案、号没配指路段隐身——页面永不编造账上没有的东西。
 * ============================================================ */
type BindState = {
  status: string; qq_number?: string | null;
  code?: string | null; bot_number?: string | null;
};

function QqBindPanel() {
  const [st, setSt] = useState<BindState>({ status: "none" });
  const [left, setLeft] = useState(0);      // 码剩余秒（本地钟，与后端 10 分钟同口径）
  const [err, setErr] = useState("");
  const [imgOk, setImgOk] = useState(true);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api("/api/qq/binding").then((d) => setSt(d as BindState)).catch(() => {});
  }, []);

  const hasCode = !!st.code && left > 0;
  useEffect(() => {
    if (!hasCode) return;
    const t = setInterval(async () => {
      setLeft((n) => Math.max(0, n - 1));
      try {
        const d = (await api("/api/qq/binding")) as BindState;
        if (d.status === "bound") { setSt(d); setLeft(0); }
      } catch { /* 巡更失手不打扰，下一秒再巡 */ }
    }, 1000);
    return () => clearInterval(t);
  }, [hasCode]);

  async function fetchCode(): Promise<void> {
    setErr("");
    try {
      // api() 约定：带 body 才算 POST——空物件是「递材料」的门面
      const d = (await api("/api/qq/bind-code", {})) as { code: string; expires_min: number };
      // 功能式更新：只翻 status/code，bot_number 等既有字段不能被发码抹掉
      setSt((s) => ({ ...s, status: "pending", code: d.code }));
      setLeft(d.expires_min * 60);
    } catch (e) { setErr((e as Error).message); }
  }

  async function copyBot(): Promise<void> {
    if (!st.bot_number) return;
    try {
      await navigator.clipboard.writeText(st.bot_number);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* 剪贴板失手不打扰——号在屏上，选抄即可 */ }
  }

  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");

  return (
    <div className="rounded-[1.75rem] p-2 ring-1 ring-ink/5" style={{ backgroundColor: "var(--color-mist)" }}>
      <div className="rounded-[calc(1.75rem-0.5rem)] p-5"
           style={{ backgroundColor: "var(--color-parchment)", boxShadow: "inset 0 1px 1px rgba(255,255,255,0.8)" }}>
        <span className="mb-2 inline-block rounded-full px-3 py-1 text-[10px] font-bold tracking-[0.25em]"
              style={{ backgroundColor: "rgba(28,35,41,0.10)", color: "rgba(28,35,41,0.70)" }}>
          QQ · 绑定
        </span>
        <h2 className="font-display text-2xl text-ink">把助教认进你的好友列表</h2>

        {st.status === "bound" ? (
          <div className="mt-4">
            <p className="text-[14px] font-bold text-ink">已绑定 QQ · {st.qq_number}</p>
            <p className="mt-1 text-[12px] font-semibold text-ink/60">
              到点的提醒和 QQ 私聊都认这个号；换号点下面重新发码。
            </p>
            <button type="button" onClick={fetchCode}
                    className="mt-3 rounded-full border border-copper/40 px-4 py-1.5 text-[12px] font-bold text-copper transition-colors duration-300 hover:bg-copper/10">
              换绑（重新发码）
            </button>
          </div>
        ) : (
          <>
            {hasCode ? (
              <div className="mt-4">
                <p className="font-mono text-4xl font-black tracking-[0.3em] text-ink">{st.code}</p>
                <p className="mt-1.5 text-[12px] font-semibold text-ink/60">
                  10 分钟内把这串码私聊发给助教 · 剩 {mm}:{ss}
                </p>
              </div>
            ) : (
              <p className="mt-2 text-[13px] font-semibold text-ink/70">
                两步走：① 先加助教当 QQ 好友（不是好友，消息递不到它）　② 拿 6 位码发给它私聊。
              </p>
            )}

            {/* 指路段：好友码 + 搜号兜底；bot_number 没配整段隐身 */}
            {st.bot_number && (
              <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start">
                {imgOk ? (
                  <a href="/qq_friend_qrcode.jpg" target="_blank" rel="noreferrer"
                     title="点开看大图" className="shrink-0">
                    <img src="/qq_friend_qrcode.jpg" alt="加好友二维码"
                         onError={() => setImgOk(false)}
                         className="w-36 rounded-xl border border-ink/10" />
                  </a>
                ) : (
                  <div className="w-36 shrink-0 rounded-xl border border-dashed border-ink/15 px-3 py-6 text-center text-[11px] font-semibold text-ink/50">
                    好友码还没上架——找户主要邀请码
                  </div>
                )}
                <div className="min-w-0 text-[12px] font-semibold leading-relaxed text-ink/70">
                  <p>手机 QQ 扫左边的码，自动通过；或搜号添加：</p>
                  <button type="button" onClick={copyBot}
                          className="mt-1.5 rounded-md px-2.5 py-1 font-mono text-[13px] font-bold text-ink ring-1 ring-ink/10 transition-colors duration-300 hover:bg-copper/10"
                          style={{ backgroundColor: "var(--color-mist)" }}>
                    {st.bot_number}{copied ? "　✓ 已复制" : "　点复制"}
                  </button>
                  <p className="mt-2">加上好友后再回来拿码——绑成前这一步绕不开。</p>
                </div>
              </div>
            )}

            <button type="button" onClick={fetchCode}
                    className="mt-5 rounded-full px-5 py-2 text-[13px] font-bold text-parchment shadow-copper transition-transform duration-300 active:scale-95"
                    style={{ backgroundColor: "var(--color-copper)" }}>
              {hasCode ? "重新发码" : "我已加好友 · 拿 6 位绑定码"}
            </button>
            {err && <p className="mt-2 text-[11px] font-semibold text-copper">{err}</p>}
          </>
        )}
      </div>
    </div>
  );
}
