/* ============================================================
 * 介绍页细线图标集（1.25px stroke，与 App 导航同一把尺子）
 * 禁 Lucide/FontAwesome 粗线；一律 currentColor，由外层定色
 * ============================================================ */

import type { ReactElement } from "react";

export type IntroIconName =
  | "calendar" | "book" | "compass" | "ledger" | "vault"
  | "stream" | "key" | "backup" | "mail" | "phone" | "question" | "arrow";

const PATHS: Record<IntroIconName, ReactElement> = {
  calendar: (<>
    <rect x="3" y="5" width="18" height="16" rx="2.5" />
    <path d="M8 3v4M16 3v4M3 10h18" />
    <path d="M17.5 15.5v3M16 17.5h3" />
  </>),
  book: (<>
    <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v14H6.5A2.5 2.5 0 0 0 4 19.5z" />
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H19v4H6.5A2.5 2.5 0 0 1 4 19.5z" />
    <path d="M9 7.5h6" />
  </>),
  compass: (<>
    <circle cx="12" cy="12" r="9" />
    <path d="M15.5 8.5l-2 5-5 2 2-5z" />
  </>),
  ledger: (<>
    <path d="M5 3h11a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5z" />
    <path d="M9 8h5M9 12h5M9 16h3" />
    <path d="M19.5 9.5v5" strokeDasharray="2 2" />
  </>),
  vault: (<>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <circle cx="11" cy="12" r="3.5" />
    <path d="M11 8.5v-1M11 16v-1M7.5 12h-1M15.5 12h-1M17 9v6" />
  </>),
  stream: (<>
    <path d="M4 7h10M4 12h7M4 17h10" />
    <path d="M17 9.5l3 2.5-3 2.5" />
  </>),
  key: (<>
    <circle cx="8" cy="12" r="3.5" />
    <path d="M11.5 12H21M18 12v3M15.5 12v2" />
  </>),
  backup: (<>
    <path d="M20 12a8 8 0 1 1-3-6.2" />
    <path d="M20 4v4h-4" />
    <path d="M12 8.5v4l2.5 1.5" />
  </>),
  mail: (<>
    <rect x="3" y="5" width="18" height="14" rx="2.5" />
    <path d="M4 7l8 6 8-6" />
  </>),
  phone: (<>
    <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
    <path d="M11 18.5h2" />
  </>),
  question: (<>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5A2.5 2.5 0 1 1 12 12.5v1.5" />
    <path d="M12 17.5h.01" />
  </>),
  arrow: (<>
    <path d="M5 12h14" />
    <path d="m13 6 6 6-6 6" />
  </>),
};

/** 细线图标：size 默认 20，strokeWidth 默认 1.25 */
export default function IntroIcon({
  name, size = 20, strokeWidth = 1.25,
}: { name: IntroIconName; size?: number; strokeWidth?: number }): ReactElement {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={strokeWidth}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
