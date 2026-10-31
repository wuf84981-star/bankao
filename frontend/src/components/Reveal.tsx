/* ============================================================
 * Reveal · 滚动渐入包装（介绍页专用）
 * 只做 opacity + transform 两件事（GPU 合成层），进过一次即断开观察
 * prefers-reduced-motion 由 index.css 的 .reveal 兜底强制可见
 * ============================================================ */

import { useEffect, useRef, useState, type ReactNode } from "react";

type RevealProps = {
  children: ReactNode;
  /** 入场延迟（毫秒），同组卡片错峰用 */
  delay?: number;
  className?: string;
};

export default function Reveal({ children, delay = 0, className = "" }: RevealProps) {
  const box = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    // 老浏览器没有观察者：直接显形，绝不让内容卡在透明态
    if (typeof IntersectionObserver === "undefined") { setShown(true); return; }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) { setShown(true); io.disconnect(); break; }
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.05 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div ref={box} className={`reveal ${shown ? "in" : ""} ${className}`}
         style={{ transitionDelay: `${delay}ms` }}>
      {children}
    </div>
  );
}
