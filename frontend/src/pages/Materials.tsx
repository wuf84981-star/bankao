/**
 * ============================================================
 * 资料页（Materials）— 高端沉稳感 v2
 * ------------------------------------------------------------
 * 设计要点：
 *   1. Double-Bezel 双层卡片架构：外层 mist 浅米灰壳 + 内层 parchment 羊皮纸芯
 *      每一层独立圆角（内圆角 = 外圆角 - 0.375rem / 0.5rem），内核带 inset 高光
 *   2. 暖色配色：cream / mist / parchment 为底，ink 墨青 + copper 沉铜绿为主色，
 *      rust 铁锈赭作为错误态强调，wheat 麦黄做轻高亮
 *   3. 字体层次：font-display（Noto Serif SC）用于知识树大标题，font-heading
 *      用于文件名/章节，font-mono tabular-nums 做大小/百分比对齐
 *   4. 过渡统一使用 --ease-glide 或 --ease-spring，禁用 linear / ease-in-out
 *   5. 状态徽章异形：parsing（进度胶囊+旋转圆弧）、ready（沉铜绿对勾圆岛）、
 *      failed（铁锈赭三角告警岛+圆角重试胶囊）
 *   6. 知识树 details/summary：SVG ▶ 箭头 open 时 rotate-90，缩进用 cream
 *      背景色块而非 border-left
 *   7. 上传区虚线卡 hover：border-copper + 上浮 -2px + wheat/40 背景
 *
 * 组件架构：
 *   - Materials（默认导出）
 *       ├─ UploadCard 上传区（虚线 Double-Bezel）
 *       ├─ EmptyStateCard 空态提示卡（仅 docs.length === 0 时显示）
 *       ├─ FileCardList 文件卡列表（space-y-4）
 *       │    └─ FileCard 单张文件卡（exam徽章 + status徽章 + size/原因/重试）
 *       └─ KnowledgeTree 知识树面板（details/summary 原生折叠）
 *
 * 作者位置标记：v2
 * ============================================================
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactElement } from "react";
import { api, apiDelete, apiUpload } from "../auth";

/** 资料解析三态 */
type Status = "parsing" | "ready" | "failed";

/**
 * 资料文档类型（形状严格保留 PRD 字段）
 * @property id       唯一 ID
 * @property name     文件名
 * @property size     文件大小（例："4.2 MB"）
 * @property exam     所属考试："国考" 或 "通用"（通用对所有考试可见）
 * @property status   解析状态：parsing / ready / failed
 * @property progress 解析进度百分比（仅 parsing 时有）
 * @property reason   失败原因文案（仅 failed 时有）
 */
type Doc = {
  id: number;
  name: string;
  size: string;
  exam: "国考" | "通用";
  status: Status;
  progress?: number;
  reason?: string;
  /** 解析战报（仅真上传成功后有）：如「读到 12 页 · 8,340 字」 */
  meta?: string;
};

/** 八刀（D46 甲）：三条演示假卡摘除（用户真机戳穿——库里 0 行、磁盘 0 文件，
 *  全是从前橱窗时代的道具）。列表进页从 /api/materials 拉真账，空账吃空态卡。 */

/** 字节数→人话重量；磁盘对不上号（None）显「—」，不编造 */
function fmtSize(bytes: number | null): string {
  if (bytes == null) return "—";
  return bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/* ============================================================
 *                        自定义缓动样式
 * ============================================================ */

/** 统一 glide 缓动的 style 工厂 */
const glideStyle = (durationMs = 300): CSSProperties => ({
  transitionTimingFunction: "var(--ease-glide)",
  transitionDuration: `${durationMs}ms`,
});

/** Double-Bezel 内核统一 inset 高光阴影 */
const BEZEL_INNER_SHADOW: CSSProperties = {
  boxShadow: "inset 0 1px 1px rgba(255,255,255,0.85)",
};

/* ============================================================
 *                       SVG 细线图标集合
 *                strokeWidth ≤ 1.5，全部手写内联
 * ============================================================ */

/**
 * 上传云图标（48×48，细线风）
 * @returns ReactElement
 */
function CloudUploadIcon(): ReactElement {
  return (
    <svg
      width="48"
      height="48"
      viewBox="0 0 48 48"
      fill="none"
      stroke="rgba(28,35,41,0.55)"
      strokeWidth={1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M33 33H15a7 7 0 1 1 1.4-13.86A9 9 0 0 1 34 21a6 6 0 0 1-1 12z" />
      <path d="M24 33V21" />
      <path d="M19 26l5-5 5 5" />
    </svg>
  );
}

/**
 * 旋转圆弧（解析中 spinner，配合 animate-spin-slow 类）
 * @returns ReactElement
 */
function SpinnerArc(): ReactElement {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
    >
      <circle cx="12" cy="12" r="9" strokeDasharray="40 20" />
    </svg>
  );
}

/**
 * 沉铜绿对勾图标（已就绪态）
 * @returns ReactElement
 */
function CheckTickIcon(): ReactElement {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--color-copper-dk)"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M5 12.5l4.5 4.5L19 7.5" />
    </svg>
  );
}

/**
 * 三角形 + 感叹号告警图标（失败态）
 * @returns ReactElement
 */
function WarningTriangleIcon(): ReactElement {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--color-rust)"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

/**
 * 旋转箭头（重试按钮）
 * @returns ReactElement
 */
function ReloadIcon(): ReactElement {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 12a9 9 0 1 1-3-6.7L21 8" />
      <path d="M21 3v5h-5" />
    </svg>
  );
}

/* ============================================================
 *                        子组件定义
 * ============================================================ */

/**
 * 上传区卡片（虚线 Double-Bezel）
 * @param onPicked 文件选择回调（接收 FileList | null）
 * @returns ReactElement
 */
function UploadCard({ onPicked }: { onPicked: (f: FileList | null) => void }): ReactElement {
  return (
    <label
      className="block cursor-pointer border-2 border-dashed p-2 rounded-[1.5rem] hover:-translate-y-[2px] transition-all"
      style={{
        borderColor: "var(--color-sand)",
        backgroundColor: "rgba(243,240,234,0.5)",
        ...glideStyle(300),
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget;
        el.style.borderColor = "var(--color-copper)";
        el.style.backgroundColor = "rgba(239,230,210,0.4)";
        el.style.boxShadow = "0 8px 24px rgba(28,35,41,0.06)";
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget;
        el.style.borderColor = "var(--color-sand)";
        el.style.backgroundColor = "rgba(243,240,234,0.5)";
        el.style.boxShadow = "none";
      }}
    >
      <div
        className="rounded-[1.125rem] px-6 py-7 text-center"
        style={{
          backgroundColor: "rgba(255,251,243,0.7)",
          ...BEZEL_INNER_SHADOW,
        }}
      >
        <div className="flex justify-center">
          <CloudUploadIcon />
        </div>
        <div
          className="mt-3 text-[15px] font-semibold"
          style={{ fontFamily: "var(--font-heading)", color: "var(--color-ink)" }}
        >
          上传你的讲义
        </div>
        <div
          className="text-[13px] mt-1"
          style={{ color: "rgba(28,35,41,0.55)" }}
        >
          点选择文件，或把讲义拖进来（PDF/Word(.docx)/TXT/MD 会真上传到服务器解析并入库）
        </div>
      </div>
      <input
        type="file"
        multiple
        accept=".pdf,.docx,.txt,.md"
        className="sr-only"
        onChange={(e) => {
          onPicked(e.target.files);
          e.target.value = "";
        }}
      />
    </label>
  );
}

/**
 * 空态提示卡（无文件时展示）
 * @returns ReactElement
 */
function EmptyStateCard(): ReactElement {
  return (
    <div
      className="mt-6 p-2 rounded-[1.5rem] ring-1"
      style={{
        backgroundColor: "var(--color-mist)",
        boxShadow: "var(--shadow-float-sm)",
        // eslint-disable-next-line @typescript-eslint/no-dupe-keys
        ["--tw-ring-color" as string]: "rgba(28,35,41,0.05)",
      }}
    >
      <div
        className="rounded-[1.125rem] px-6 py-5 text-center"
        style={{
          backgroundColor: "var(--color-parchment)",
          ...BEZEL_INNER_SHADOW,
        }}
      >
        <p
          className="text-[14px]"
          style={{
            color: "rgba(28,35,41,0.6)",
            fontFamily: "var(--font-body)",
          }}
        >
          把第一份讲义传上来，我读完就能替你出题
        </p>
      </div>
    </div>
  );
}

/**
 * 考试徽章（国考 / 通用 两款异形）
 * @param exam "国考" 或 "通用"
 * @returns ReactElement
 */
function ExamBadge({ exam }: { exam: "国考" | "通用" }): ReactElement {
  if (exam === "国考") {
    return (
      <span
        className="rounded-full px-3 py-1 text-[11px] font-bold tracking-wide"
        style={{
          backgroundColor: "rgba(28,35,41,0.1)",
          color: "var(--color-ink)",
        }}
      >
        国考
      </span>
    );
  }
  // 通用：斜角胶囊双层 skew
  return (
    <span
      className="rounded-md skew-x-[-6deg] px-3 py-1"
      style={{ backgroundColor: "rgba(98,117,122,0.12)" }}
    >
      <span
        className="skew-x-[6deg] block text-[11px] font-bold tracking-wide"
        style={{ color: "var(--color-copper)" }}
      >
        通用 · 全考试可见
      </span>
    </span>
  );
}

/**
 * 解析中状态徽章（进度胶囊 + 旋转圆弧）
 * @param progress 进度百分比 0~100
 * @returns ReactElement
 */
function ParsingBadge({ progress = 0 }: { progress?: number }): ReactElement {
  return (
    <span
      className="rounded-full px-3 py-1.5 inline-flex items-center gap-2 text-[12px] font-bold"
      style={{
        backgroundColor: "rgba(98,117,122,0.1)",
        color: "var(--color-copper)",
      }}
    >
      {/* 旋转圆弧 — index.css 中定义的 animate-spin-slow（glide 缓动，非 linear） */}
      <span
        className="inline-flex animate-spin-slow"
        style={{ animationDuration: "1.4s" }}
      >
        <SpinnerArc />
      </span>
      {/* 进度条外槽 */}
      <span
        className="inline-block h-2 w-32 rounded-full overflow-hidden"
        style={{ backgroundColor: "var(--color-mist)" }}
      >
        <span
          className="block h-full rounded-full"
          style={{
            width: `${progress}%`,
            backgroundImage:
              "linear-gradient(to right, rgba(98,117,122,0.6), var(--color-copper))",
            transitionProperty: "width",
            transitionDuration: "500ms",
            transitionTimingFunction: "var(--ease-glide)",
          }}
        />
      </span>
      <span
        className="tabular-nums"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {progress}%
      </span>
    </span>
  );
}

/**
 * 已就绪状态徽章（圆对勾岛）
 * @returns ReactElement
 */
function ReadyBadge(): ReactElement {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="w-7 h-7 rounded-full grid place-items-center"
        style={{ backgroundColor: "rgba(98,117,122,0.15)" }}
      >
        <CheckTickIcon />
      </span>
      <span
        className="text-[12px] font-bold"
        style={{ color: "var(--color-copper)" }}
      >
        已就绪 · 可被引用
      </span>
    </span>
  );
}

/**
 * 失败状态徽章（三角告警岛）
 * @returns ReactElement
 */
function FailedBadge(): ReactElement {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className="w-7 h-7 rounded-[8px] grid place-items-center"
        style={{ backgroundColor: "rgba(168,84,62,0.12)" }}
      >
        <WarningTriangleIcon />
      </span>
      <span
        className="text-[12px] font-bold"
        style={{ color: "var(--color-rust)" }}
      >
        解析失败
      </span>
    </span>
  );
}

/**
 * 单张文件卡（Double-Bezel 外壳 + 羊皮纸内核）
 * @param doc     文档数据
 * @param onRetry 重试回调（失败态点击）
 * @param onDelete 删除回调（D84：两步确认，防手滑——物理删不可逆）
 * @returns ReactElement
 */
function FileCard({ doc, onRetry, onDelete }: { doc: Doc; onRetry: (id: number) => void; onDelete: (id: number) => void }): ReactElement {
  /* 删除武装态：第一击变「确认删除？」，第二击才落刀；走开或再点别处解除 */
  const [armed, setArmed] = useState(false);
  return (
    <li
      className="p-1.5 rounded-[1.5rem] ring-1"
      style={{
        backgroundColor: "var(--color-mist)",
        boxShadow: "var(--shadow-float-sm)",
        ["--tw-ring-color" as string]: "rgba(28,35,41,0.05)",
      }}
    >
      <div
        className="rounded-[1.125rem] p-5"
        style={{
          backgroundColor: "var(--color-parchment)",
          ...BEZEL_INNER_SHADOW,
        }}
      >
        {/* 顶部行：文件名 + 考试徽章 + 状态徽章 */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span
            className="min-w-0 flex-1 truncate text-[15px] font-semibold"
            style={{
              fontFamily: "var(--font-heading)",
              color: "var(--color-ink)",
            }}
            title={doc.name}
          >
            {doc.name}
          </span>
          <ExamBadge exam={doc.exam} />
          {doc.status === "parsing" && <ParsingBadge progress={doc.progress} />}
          {doc.status === "ready" && <ReadyBadge />}
          {doc.status === "failed" && <FailedBadge />}
        </div>

        {/* 次行：大小 / 失败原因 / 重试按钮 */}
        <div
          className="mt-3 flex flex-wrap items-center gap-3 text-[12px]"
          style={{ color: "rgba(28,35,41,0.55)" }}
        >
          <span
            className="tabular-nums"
            style={{ fontFamily: "var(--font-mono)" }}
          >
            {doc.size}
          </span>
          {doc.status === "ready" && doc.meta && <span>{doc.meta}</span>}
          {doc.status === "failed" && (
            <>
              <span style={{ color: "rgba(168,84,62,0.9)" }}>{doc.reason}</span>
              <button
                type="button"
                onClick={() => onRetry(doc.id)}
                className="rounded-full border px-4 py-1.5 text-[12px] font-bold inline-flex items-center gap-1.5 transition-all"
                style={{
                  borderColor: "rgba(168,84,62,0.4)",
                  color: "var(--color-rust)",
                  backgroundColor: "transparent",
                  ...glideStyle(300),
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = "rgba(168,84,62,0.1)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = "transparent";
                }}
              >
                <ReloadIcon />
                重新解析
              </button>
            </>
          )}
          {/* D84 删除钮（parsing 进行中不给删）：两步确认，武装态 rust 实底 */}
          {doc.status !== "parsing" && (
            <button
              type="button"
              onClick={() => (armed ? onDelete(doc.id) : setArmed(true))}
              onBlur={() => setArmed(false)}
              className="ml-auto rounded-full border px-3.5 py-1 text-[11px] font-bold transition-all"
              style={{
                borderColor: armed ? "rgba(168,84,62,0.6)" : "rgba(28,35,41,0.15)",
                color: armed ? "var(--color-parchment)" : "rgba(28,35,41,0.5)",
                backgroundColor: armed ? "var(--color-rust)" : "transparent",
                ...glideStyle(300),
              }}
            >
              {armed ? "确认删除？文字与坐标一起清" : "删除"}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}

/**
 * 知识树面板（右侧 aside，Double-Bezel + details 原生折叠）
 * @returns ReactElement
 */
function KnowledgeTree(): ReactElement {
  return (
    <aside
      className="p-2 rounded-[1.75rem] ring-1 self-start"
      style={{
        backgroundColor: "var(--color-mist)",
        boxShadow: "var(--shadow-float)",
        ["--tw-ring-color" as string]: "rgba(28,35,41,0.05)",
      }}
    >
      <div
        className="rounded-[1.25rem] p-6"
        style={{
          backgroundColor: "var(--color-parchment)",
          boxShadow: "inset 0 1px 1px rgba(255,255,255,0.88)",
        }}
      >
        <h2
          className="text-xl mb-1"
          style={{
            fontFamily: "var(--font-display)",
            color: "var(--color-ink)",
          }}
        >
          知识树
        </h2>
        <p
          className="text-[12px] mb-4"
          style={{ color: "rgba(28,35,41,0.6)" }}
        >
          资料入库并点火后，这里会拆出你的知识点
        </p>

        {/* 八刀（D46 甲）：假枝摘除——真树待 S8 资料管理刀，以 chunks 的
             科目/章节为数据源长出来；在那之前这里只说真话，不演满树叶子。 */}
        <div
          className="rounded-[0.75rem] px-4 py-8 text-center"
          style={{
            backgroundColor: "rgba(250,248,244,0.7)",
            fontSize: "13px",
            color: "rgba(28,35,41,0.55)",
            lineHeight: "1.9",
          }}
        >
          还没有拆出的知识点
          <br />
          <span style={{ fontSize: 12 }}>资料入库并点火后，这里会长出你的真树</span>
        </div>
      </div>
    </aside>
  );
}

/* ============================================================
 *                        根组件导出
 * ============================================================ */

/**
 * 资料页根组件（Materials）
 * 功能：
 *   - 上传讲义（S3 入库刀：PDF/TXT/MD 真上传解析入库、待点火变坐标；其余格式仍演示态）
 *   - 展示文件卡列表：三态（parsing / ready / failed）
 *   - 失败重试：状态切 parsing，起始进度 8%
 *   - 右侧知识树：原生 details/summary 折叠
 * @returns ReactElement
 */
export default function Materials(): ReactElement {
  const [docs, setDocs] = useState<Doc[]>([]);

  /* 八刀（D46 甲）：进页拉真账——从前三条演员卡退役，屏幕上只许有你的真仓库。
     ready 行的 meta 顺带报点火进度（坐标数/块数），对账一眼完成。
     D84 抽成 load()：删除落刀后也要整表重拉——行在不在，服务器账说了算。 */
  function load(): void {
    void (async () => {
      try {
        const r = (await api("/api/materials")) as {
          materials: {
            id: number; title: string; exam: string; size: number | null;
            status: Status; reason: string | null; chunks: number; vectors: number;
          }[];
        };
        setDocs(r.materials.map((m) => ({
          id: m.id, name: m.title, size: fmtSize(m.size),
          exam: m.exam === "通用" ? "通用" : "国考",
          status: m.status,
          reason: m.status === "failed" ? (m.reason ?? "解析失败") : undefined,
          meta: m.status === "ready"
            ? (m.vectors > 0
                ? `已点火 ${m.vectors}/${m.chunks} 块坐标`
                : `已入库 ${m.chunks} 块（待点火变坐标）`)
            : undefined,
        })));
      } catch { /* 拉不到保持空账+空态卡——宁空不假 */ }
    })();
  }
  useEffect(() => { load(); }, []);

  /**
   * 删除（D84 · PRD AC②）：物理删一份讲义——chunks 与向量 CASCADE、磁盘原件同扫；
   * 无论成败都整表重拉：删成功卡片消失、删失败行还在，行存在性以服务器为真。
   * @param id 材料 id
   */
  function del(id: number): void {
    void apiDelete(`/api/materials/${id}`)
      .catch(() => {})          // 失败不弹新文案——重拉后行还在就是人话回答
      .finally(load);
  }
  /** 文件库：id→File 句柄。本次会话里上传过的真文件才在里面——重试按钮靠它复投，
   *  挂页拉回的历史行没有句柄，重试对无句柄行不演假动作（八刀护栏）。 */
  const fileBank = useRef(new Map<number, File>());

  /**
   * 真上传一件：POST /api/ingest → 成回写战报（ready）/ 败写人话（failed）
   * @param id 对应文件卡的 id
   * @param f 浏览器文件句柄
   * @returns void
   */
  async function sendParse(id: number, f: File): Promise<void> {
    try {
      const r = (await apiUpload("/api/ingest", f)) as {
        pages?: number;
        chars: number;
        chunks: number;
      };
      setDocs((d) =>
        d.map((doc) =>
          doc.id === id
            ? {
                ...doc,
                status: "ready",
                progress: undefined,
                meta:
                  (r.pages ? `读到 ${r.pages} 页 · ` : "读到 ") +
                  `${r.chars.toLocaleString("en-US")} 字 · 已入库 ${r.chunks} 块（待点火变坐标）`,
              }
            : doc
        )
      );
    } catch (e) {
      setDocs((d) =>
        d.map((doc) =>
          doc.id === id
            ? {
                ...doc,
                status: "failed",
                progress: undefined,
                reason: e instanceof Error ? e.message : "上传失败",
              }
            : doc
        )
      );
    }
  }

  /**
   * 失败重试：真文件（文件库有句柄）→ 回 parsing 并真复投；
   * 道具卡 → 老演示动作（切 parsing 起始 8%）。
   * @param id 文档 ID
   * @returns void
   */
  function retry(id: number): void {
    const f = fileBank.current.get(id);
    if (!f) return;   // 句柄只在浏览器内存：刷新后的历史行没法真复投，就不演假 parsing
    setDocs((d) =>
      d.map((doc) =>
        doc.id === id ? { ...doc, status: "parsing", progress: 8, reason: undefined } : doc
      )
    );
    void sendParse(id, f);
  }

  /**
   * 文件选择处理（S3 解析刀接真）：每张卡先挂上列表（parsing）再并行投递，
   * 句柄存进文件库供重试复投。
   * @param files 来自 input 的 FileList
   * @returns void
   */
  function picked(files: FileList | null): void {
    if (!files || files.length === 0) return;
    Array.from(files).forEach((f, i) => {
      const id = Date.now() + i;
      fileBank.current.set(id, f);
      setDocs((d) => [
        ...d,
        {
          id,
          name: f.name,
          size: fmtSize(f.size),
          // 与后端口径一致：ingest 未设考试归属（NULL=通用）——临时行别演另一张脸
          exam: "通用",
          status: "parsing",
          progress: 30,
        },
      ]);
      void sendParse(id, f);
    });
  }

  return (
    <section className="px-5 md:px-8 py-6 md:py-8 overflow-y-auto">
      <div className="grid gap-8 lg:grid-cols-[1fr_18rem]">
        {/* 左栏：上传区 + 文件列表 */}
        <div>
          <UploadCard onPicked={picked} />

          {docs.length === 0 && <EmptyStateCard />}

          <ul className="mt-6 space-y-4">
            {docs.map((doc) => (
              <FileCard key={doc.id} doc={doc} onRetry={retry} onDelete={del} />
            ))}
          </ul>

          {docs.length > 0 && (
            <p
              className="mt-6 text-[12px]"
              style={{ color: "rgba(28,35,41,0.55)" }}
            >
              链路进度：上传→解析→切块→存盘已通（上面就是真账）；
              点火（把文字变成可检索的坐标）目前在服务器批量执行，点完火教练才引得到。
            </p>
          )}
        </div>

        {/* 右栏：知识树 */}
        <KnowledgeTree />
      </div>
    </section>
  );
}
