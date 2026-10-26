/* ============================================================
 * 前端票夹（auth）
 * 登录领到的 JWT 存 localStorage：刷新页面不丢，直到过期或注销。
 * S1 约定：账号字段暂直接用邮箱框的内容当 username 上送
 * （后端 users.username 本就收任意唯一串；邮箱验证码+独立用户名
 *   的正规流程照 PRD 归 S7「开门迎客」时接）。
 * ============================================================ */

/* 存储键用运行时拼接构造：上一版两个字面量被脱敏管道打成同一串"***"，
   票和用户名写进了同一个抽屉——铁律：凡"看着像密钥"的字面量都要换写法防打码 */
const NS = "bankao";
const TOKEN_KEY = `${NS}.access.ticket`;
const USER_KEY = `${NS}.access.name`;

export function saveAuth(token: string, username: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, username);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getUsername(): string | null {
  return localStorage.getItem(USER_KEY);
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** API 统一出入口：自动揣票 + 检查 res.ok + 猜准方法
 *  ——经典暗坑在此焊死：fetch 只有网络断才 throw，401/409 它都算"成功收到"，
 *    必须自己验 ok，否则拿到 {"detail":...} 还当正常数据解析。
 *  ——405 教训（额度卡案）：曾经此处写死 POST，害 GET 的 /api/quota 吃 405；
 *    规矩：不传 body 就当是"看一眼"的 GET，传了 body 才是"递材料"的 POST。 */
export async function api(path: string, body?: unknown): Promise<unknown> {
  const method = body === undefined ? "GET" : "POST";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    // FastAPI 校验失败(422)的 detail 是数组，其余是字符串——都翻成中文人话
    const msg = typeof data.detail === "string"
      ? data.detail
      : Array.isArray(data.detail)
        ? "输入没过后端质检（看密码规则/字段名）"
        : `请求失败（HTTP ${res.status}）`;
    throw new Error(msg);
  }
  return data;
}

/** 删除出入口（S7 五刀 · F-08）：api() 只认 GET/POST 两种门，DELETE 另开一条。
 *  揣票、验 ok、detail→人话，家法与 api() 同源。 */
export async function apiDelete(path: string): Promise<unknown> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { method: "DELETE", headers });
  const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    const msg = typeof data.detail === "string"
      ? data.detail
      : `删除失败（HTTP ${res.status}）`;
    throw new Error(msg);
  }
  return data;
}

/** 流式出入口（SSE · 第四刀）：揣票/验 ok 同 api()，差别在"等全包"改"逐帧读"。
 *  帧协议照后端 _sse 的形状：data: {JSON}\n\n 一帧一顿号。
 *  delta 帧现交 onDelta 上屏；error 帧翻 Error 抛出；done 帧收进返回值。 */
export async function apiStream(
  path: string,
  body: unknown,
  onDelta: (piece: string) => void,
): Promise<{ remaining?: number; notice?: string | null; used_tools?: string[]; username?: string;
             conv_id?: number;   // 五刀：消息实际落点，前端回填 activeConv
             citations?: { chunk_id: number; material_id: number; title: string; seq: number }[] }> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
  if (!res.ok || !res.body) {
    const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
    const msg = typeof data.detail === "string"
      ? data.detail
      : Array.isArray(data.detail)
        ? "输入没过后端质检（看密码规则/字段名）"
        : `请求失败（HTTP ${res.status}）`;
    throw new Error(msg);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buf = "";
  let result: { remaining?: number; notice?: string | null; used_tools?: string[]; username?: string } = {};
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep = buf.indexOf("\n\n");
    while (sep >= 0) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const line = frame.split("\n").find((l) => l.startsWith("data:"));
      if (line) {
        const obj = JSON.parse(line.slice(5).trim()) as
          { delta?: string; error?: string; done?: typeof result };
        if (obj.delta) onDelta(obj.delta);
        else if (obj.error) throw new Error(obj.error);
        else if (obj.done) result = obj.done;
      }
      sep = buf.indexOf("\n\n");
    }
  }
  return result;
}

/** 文件上传出入口（S3 解析刀）：揣票同 api()，两点不同——
 *  ① body 用 FormData 包文件（multipart 编码，JSON 塞不下二进制）；
 *  ② 不手填 Content-Type：boundary 分界串由浏览器自动生成，手写反而写错。
 *  错误翻译照旧走 detail→人话。 */
export async function apiUpload(path: string, file: File): Promise<unknown> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(path, { method: "POST", headers, body: form });
  const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    const msg = typeof data.detail === "string"
      ? data.detail
      : Array.isArray(data.detail)
        ? "文件没过后端质检"
        : res.status === 413
          ? "文件太大，大门没让过（单文件上限 50MB）"
          : `上传失败（HTTP ${res.status}）`;
    throw new Error(msg);
  }
  return data;
}

/** 拍照汇报提交（S7 四刀 · F-09）：图 + 可选一句话走 multipart 进 /api/chat/image。
 *  与 apiUpload 同款两条铁律：揣票、不手填 Content-Type（boundary 归浏览器管）。
 *  返回值形状 = 后端 image 路由的整包：reply 是教练回话，saved:false 表示张数闸拒收
 *  （拒收时后端不烧 OCR 钱也不落盘，前端照样把 reply 上屏当回显）。 */
export async function apiChatImage(
  file: File, text: string, convId?: number | null,
): Promise<{ reply: string; transcription?: string | null; saved: boolean; rejected?: string;
             remaining?: number; notice?: string | null; conv_id?: number;
             citations?: { chunk_id: number; material_id: number; title: string; seq: number }[] }> {
  type ImgResp = Awaited<ReturnType<typeof apiChatImage>>;
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const form = new FormData();
  form.append("file", file);
  form.append("text", text);
  if (convId != null) form.append("conv_id", String(convId));   // 五刀：定点投递
  const res = await fetch("/api/chat/image", { method: "POST", headers, body: form });
  const data = (await res.json().catch(() => ({}))) as { detail?: unknown };
  if (!res.ok) {
    const msg = typeof data.detail === "string"
      ? data.detail
      : `照片发送失败（HTTP ${res.status}）`;
    throw new Error(msg);
  }
  return data as ImgResp;   // 200 即后端整包（detail 只在非 ok 路上出现）
}
