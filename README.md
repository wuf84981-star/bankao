<!-- 结构基于 Best-README-Template（othneildrew）重构，2026-10-29 -->
<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![MIT License][license-shield]][license-url]
[![Python][python-shield]][python-url]
[![React][react-shield]][react-url]
[![FastAPI][fastapi-shield]][fastapi-url]
[![PostgreSQL][pg-shield]][pg-url]
[![Docker][docker-shield]][docker-url]
[![pytest 351 passing][tests-shield]][tests-url]

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <a href="https://github.com/wind989/bankao">
    <img src="frontend/public/favicon.svg" alt="Logo" width="80" height="80">
  </a>

<h3 align="center">伴考 · BanKao</h3>

  <p align="center">
    私人备考 AI Agent：排计划、盯打卡、沉错题、出强化、判分数——网页 + QQ 双通道，全部账本记在你自己的服务器上。
    <br />
    <a href="#快速开始"><strong>本地跑起来 »</strong></a>
    <br />
    <br />
    <a href="https://github.com/wind989/bankao/issues/new?labels=bug">Report Bug</a>
    &middot;
    <a href="https://github.com/wind989/bankao/issues/new?labels=enhancement">Request Feature</a>
  </p>
</div>

<!-- TABLE OF CONTENTS -->
<details>
  <summary>目录</summary>
  <ol>
    <li><a href="#项目简介">项目简介：解决什么痛点</a></li>
    <li><a href="#核心亮点">✨ 核心亮点</a></li>
    <li><a href="#技术栈">🛠️ 技术栈</a></li>
    <li><a href="#效果图">📷 效果图</a></li>
    <li><a href="#快速开始">🚀 快速启动</a></li>
    <li><a href="#目录结构">📁 项目目录说明</a></li>
    <li><a href="#使用示例">📖 使用示例与接口说明</a></li>
    <li><a href="#后续规划">📋 后续规划</a></li>
    <li><a href="#参与贡献">参与贡献 / 许可证 / 联系 / 致谢</a></li>
  </ol>
</details>

---

<!-- ABOUT THE PROJECT -->
## 项目简介

<a id="项目简介"></a>

**痛点**——自学备考的人普遍卡死在五件事上：

| 痛点 | 现状 | 伴考的答案 |
|---|---|---|
| 计划不会倒排 | 距离考试还剩几天、每天该学多久，全凭感觉 | 登记考试类型+日期后，按考试日**倒排**逐日铺任务，末日必须恰好是考试前一日，超载会被纯函数校验墙整版打回 |
| 讲义是死的 | PDF/Word 躺在网盘，做题时查不到那一页 | 资料仓切块向量化入库，**三路召回**（向量+中文全文+关键词模糊）带引用出处作答；查不到就直说「知识库无相关资料」 |
| 通用大模型不教学 | 直接报答案、替写作文、讲义外的事靠幻觉补 | 六节点教学状态机引导思路；**客观题对错由程序裁决**不归模型嘴；严格讲义模式默认禁联网禁常识补答 |
| 学完没账 | 错在哪、为什么错、哪薄弱，没有系统记得 | 错题自动归「错误模式账」（老毛病计数/新错开账），按未结案错题数出强化题，判分回写掌握度，下次排计划读这本账——**学习闭环** |
| 数据在别人家 | 学习记录、错题本存在第三方 SaaS | 全部数据落在你自己的 PostgreSQL；`.env` 密钥永不进库，QQ/网页双通道同一本账 |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- FEATURES -->
## ✨ 核心亮点

<a id="核心亮点"></a>

1. **RAG 三路召回 + RRF 融合**（`backend/search.py`）
   pgvector **HNSW 向量腿**（语义）、**jieba 分词 → tsvector 全文腿**（中文精确词，GIN 索引）、**pg_trgm 关键词腿**（错别字/模糊拼写）并行各取 top20，**RRF（k=60）融合**成统一榜单，再用相对置信阈值（0.30）砍掉弱命中、top3 进模型上下文。回答带出处；配 **goldset 评测架**（`backend/evals/`，召回率/倒数排名可量化重跑）。
2. **自研 29 工具 function-call 循环 + LangGraph 六节点教学状态机**（`backend/orchestrator.py` / `teaching_graph.py`）
   对话大脑挂 29 手工具（排计划/打卡/出题/判分/查账/存档……），工具循环 6 轮封顶防发散。**判定权全归程序**：客观题对错由代码裁（`question_validator.grade_one`）、错题归类锁五档枚举、计划落库前过纯函数校验墙 V1~V6——模型只提议，代码执法。
3. **SSE 流式输出**（`backend/main.py` `/api/chat/stream`）
   `StreamingResponse` + `text/event-stream`：增量 delta 帧直透前端打字机；**注释帧心跳**抗代理层空闲断线；`X-Accel-Buffering: no` 让 nginx 关响应级缓冲不攒包；断流/未收敛/电厂故障各有独立 error 帧语义。
4. **双通道同一本账 + 按用户数据隔离**
   网页（REST/SSE）与 QQ（NoneBot2 收 OneBot11 事件）两条腿**汇进同一个 orchestrator**：同一个脑子、同一套 23 张表。每一手工具的每条 SQL 都带 `user_id` 票闸（程序级强制，跨户取账直接查空），不存在「换个 id 看看别人数据」的路。
5. **学习闭环回流线**
   档案（`exam_profiles`）→ 倒排计划（读掌握度账倾斜弱项）→ 打卡（积压即提议整版重排）→ 判分（错题归 `error_patterns`，同错计数）→ 强化出题（额度=未结案错题数、已答自动排除）→ 掌握度回写 → 影响下一轮计划。环环有代码有测试。
6. **工程质量**
   **351 个离线单测**全绿：假件只注入外部服务（假电厂/假 OCR/假邮件腿/假联网传输），零真网络零真烧钱；每日 04:00 自动备份整库+资料仓滚动留 7 份；积分余额**从流水账导出**，无人能偷偷改数。

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- BUILT WITH -->
## 🛠️ 技术栈

<a id="技术栈"></a>

| 层 | 选型 |
|---|---|
| **前端** | React 19 · TypeScript · Vite · Tailwind CSS 4（7 个页面：Chat / Login / Materials / Plan / Memory / Settings / Admin） |
| **后端** | Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · APScheduler（uv 管依赖与锁） |
| **AI 编排** | LangGraph（教学状态机）· 自研 29 工具 function-call 循环 · MCP · 多模型（DeepSeek / 通义千问 / 智谱 GLM，7 型号热切换） |
| **数据** | PostgreSQL 16 + pgvector（HNSW 向量索引）+ pg_trgm/tsvector · Redis 7 |
| **消息通道** | NoneBot2 · NapCat（OneBot 11 HTTP）· 邮箱验证码 SMTP |
| **认证与安全** | JWT + bcrypt + 验证码账 · 全链 user_id 票闸 · 密钥外置 `.env` |
| **部署** | Docker Compose 六容器（nginx :80 大门 / backend :8000 / bot / db / redis / napcat）· Nginx 反代 + 静态递送 |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- SCREENSHOTS -->
## 📷 效果图

<a id="效果图"></a>

> 截图位待补：本地跑起来后截下面四张放进 `docs/images/` 目录即可让本节点亮（命名保持一致）。

| 建议截图 | 文件名 | 展示什么 |
|---|---|---|
| 聊天页 | `docs/images/chat.png` | 流式打字机 + 引用出处 + 积分卡 + 模型/地球开关 |
| 计划页 | `docs/images/plan.png` | 考试日倒排日历 + 打卡状态 |
| 资料仓 | `docs/images/materials.png` | PDF/Word 入库与切块状态 |
| 记忆页 | `docs/images/memory.png` | 考试档案 / 掌握度 / 错误模式账 |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- GETTING STARTED -->
## 🚀 快速启动

<a id="快速开始"></a>

### 前置依赖

- Docker Desktop（跑六容器）
- Node.js 18+（构建前端）
- [uv](https://docs.astral.sh/uv/)（跑迁移与测试）
- 三把可选的 API 钥匙：DeepSeek（对话腿，必填）、阿里云百炼（OCR，必填）、Tavily / 智谱（可选功能，不配不坏）

### 安装与启动

```bash
# 1. 克隆仓库
git clone https://github.com/wind989/bankao.git
cd bankao

# 2. 配密钥：模板复制一份，按注释填钥匙
cp .env.example .env

# 3. 构建前端（nginx 直接递送这份静态产物）
cd frontend && npm ci && npm run build && cd ..

# 4. 起六箱（首次会 build 后端镜像；国内网络慢可多等）
docker compose up -d --build

# 5. 建表：跑一次数据库迁移（宿主连 compose 暴露在 5432 的 db 箱）
uv run alembic upgrade head
```

打开 `http://localhost` 即见登录页，**先注册**：`.env` 里 `BANKAO_ADMIN_EMAIL` 配的邮箱注册出的账号自动成为户主（可见管理页）。

### `.env` 键一览

| 键 | 干什么 | 去哪申请 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 对话大脑（默认模型） | platform.deepseek.com |
| `DASHSCOPE_API_KEY` | 图片 OCR（拍题）+ 资料点火 | 阿里云百炼 |
| `SMTP_USER` / `SMTP_PASS` | 注册/找回验证码邮件（465 SSL） | 任意邮箱 SMTP 授权码 |
| `BANKAO_ADMIN_EMAIL` | 户主邮箱，此邮箱注册直升管理员 | 你自己定 |
| `TAVILY_API_KEY`（可选） | 联网兜底（聊天里地球开关开了才用） | app.tavily.com |
| `ZHIPU_API_KEY`（可选） | 模型菜单 GLM 三路 | open.bigmodel.cn |
| `DB_PASSWORD` / `ONEBOT_API_TOKEN` / `WEBUI_TOKEN` | 底盘三键：库口令 / QQ 推送票 / NapCat 面板口令 | 默认值是熟人期开发值 |

> **上公网前必换** `DB_PASSWORD`：① 改 `.env`；② 进 db 箱对齐真库：
> `docker compose exec db psql -U bankao -d bankao -c "ALTER USER bankao WITH PASSWORD '新口令'"`，然后 `docker compose up -d` 重建。
> 密钥值只待在 `.env`——永远不进 git、不进日志。

### QQ 通道（可选）

`docker compose up` 后进 NapCat 面板 `http://localhost:6099`（口令=`WEBUI_TOKEN`），小号扫码登录，网络设置配两个 HTTP 服务：收消息推 `bot:8080`、发消息走 `napcat:3000`。之后网页「设置 → QQ 绑定」拿 6 位绑定码、QQ 私聊发码即通。

> **诚实边界**：NapCat 走 NTQQ 协议，新小号在腾讯风控下**登录态易掉**（常见挂半天就下线，需重新扫码）。本项目按「可选体验通道」设计它：所有账记在服务端，QQ 掉线期间数据零丢失，重连后网页侧栏历史依然完整；核心功能永远以网页端为主腿。

### 开发模式与测试

```bash
# 后端热重载：compose 已挂载 ./backend（--reload），改存盘即生效
# 前端开发口：cd frontend && npm run dev（:5173，出货口仍是 :80）
uv run --with pytest -q python -m pytest tests/   # 351 例离线单测，零真网络零真烧钱
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ARCHITECTURE / 目录 -->
## 📁 项目目录说明

<a id="目录结构"></a>

```
bankao/
├── backend/               # FastAPI 后端（大脑所在）
│   ├── main.py            #   51 个 REST/SSE 路由（网页腿）
│   ├── qq.py              #   OneBot11 事件腿（QQ 消息进、主动推送出）
│   ├── orchestrator.py    #   双通道汇合点：29 工具 function-call 循环
│   ├── teaching_graph.py  #   LangGraph 六节点教学状态机
│   ├── tools.py           #   工具手：排计划/打卡/出题/判分/存档/查账……
│   ├── search.py          #   RAG 三路召回 + RRF 融合
│   ├── plan_validator.py  #   计划纯函数校验墙（V1~V6）
│   ├── question_validator.py / questioning.py  # 客观题程序裁决 / 主观题要点对照
│   ├── jobs.py            #   APScheduler 三张日程：03:00 清事件/每 5 分钟提醒/04:00 备份
│   ├── points.py / short_memory.py / gaps.py / analytics.py …  # 积分流水/会话摘要/缺口账/埋点
│   └── evals/             #   检索评测架（goldset + 召回指标，可重跑）
├── frontend/              # React 19 + TS + Tailwind 4；src/pages 七页；dist 出货品
├── migrations/            # Alembic 迁移（23 张表的户口登记簿）
├── tests/                 # 351 离线单测（假件注入外部服务，数据库走真箱）
├── infra/nginx.conf       # 大门值班手册（静态递送 + /api 反代 + SSE 放行）
├── docker-compose.yml     # 六箱配载图（本机与云服务器跑同一份）
├── .env.example           # 密钥模板（真 .env 永不进库）
├── data/                  # 运行数据（不入库）：uploads 资料仓 / backups 备份 / napcat 登录态
└── LICENSE                # MIT
```

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- USAGE EXAMPLES -->
## 📖 使用示例与接口说明

<a id="使用示例"></a>

### 一段真实对话剧本（闭环全链路走一遍）

```text
你：我 12 月 20 号考考研数学一，工作日每天晚 3 小时，周末 6 小时
它：（调 save_exam_profile 存档）已登记：考研数学一 · 2026-12-20。要我现在按这个日期倒排一份计划吗？
你：排
它：（generate_plan 读档案+掌握度账 → 校验墙 V1~V6 放行 → 草案 v1）共 N 天逐日任务，末日恰是考前一天。确认生效吗？
你：确认            （activate_plan，旧版自动归档）
——两周后——
你：今晚的高数极限那组完成了，最后一题老毛病又错了
它：（check_in 打卡记账 → 判分归类「计算粗心」第 3 次 → update_mastery 建议「极限·薄弱」你点头落账）
    要不要按错题账出 3 道极限强化题？
你：出              （quiz 出题：额度按未结案错题数，答过的自动排除）
它：（你报答案 → grade_answer 客观题程序裁决对错，简答走要点对照+点评）
    对 2 错 1。错题已归账。下次排计划会把极限加权。
```

### 接口说明（共 51 个，全部 JWT 鉴权 + user_id 票闸）

启动后访问 **`http://localhost/docs`** 可看 FastAPI 自动生成的交互式文档（可直接试调用）。下表按模块分组：

| 模块 | 接口 | 说明 |
|---|---|---|
| 账号（6） | `POST /api/register/send-code` · `/api/register` · `/api/login` · `/api/reset/send-code` · `/api/reset/confirm` · `GET /api/me` | 邮箱验证码注册/登录/找回密码 |
| 对话（7） | `POST /api/chat` · `/api/chat/stream` · `/api/chat/image` · `GET/POST/DELETE /api/conversations` · `GET /api/history` | **`/api/chat/stream` 即 SSE**：`data: {"delta":…}` 字流 → `{"citations":…}` 引用 → `{"done":{余额,提醒}}`；断线有心跳注释帧 |
| 计划（5） | `GET /api/plan/summary` · `/api/plan/calendar` · `/api/plan/day` · `POST /api/plan/item/{id}/check` · `POST /api/checkin` | 倒排结果、日历视图、单日清单、页门打卡 |
| 资料/RAG（6） | `GET/DELETE /api/materials` · `POST /api/parse` · `/api/ingest` · `GET /api/search` · `GET /api/chunks/{id}` | 上传解析（PDF/Word/TXT/MD）→ 切块向量化 → 检索调试 |
| 记忆（7） | `GET /api/memories` · `POST /api/memories/fact` · `/confirm` · `/forget` · `/mastery` · `POST/DELETE /api/memories/profile` | 档案/偏好/掌握度/错误模式的查、认、忘 |
| 设置（10） | `GET/POST /api/settings/`（profile · model · teaching · websearch · feynman） | 人设/模型/教学开关/联网开关/费曼模式，页面与聊天同一本账 |
| 积分（2） | `GET /api/points` · `POST /api/checkin` | 钱包与签到流水 |
| QQ（2） | `GET /api/qq/binding` · `POST /api/qq/bind-code` | 绑定码签发；OneBot 事件腿在 bot 箱 :8080 |
| 管理（4） | `GET /api/admin/users` · `/stats` · `/gaps` · `POST /api/admin/points/adjust` | 仅户主 |
| 系统（2） | `GET /api/health` · `POST /api/echo` | 健康检查/回环 |

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ROADMAP -->
## 📋 后续规划

<a id="后续规划"></a>

- [ ] 公网部署三件套：HTTPS + 域名备案 + nginx 限流（当前仅局域网可用）
- [ ] 资料仓补形：图片讲义 OCR 转写、网页链接抓取入库（PRD 5.1.1 承诺项）
- [ ] 会话体验：网页会话重命名；QQ 端「新对话」口令对齐网页按钮
- [ ] 登录票吊销账：改密码即时踢下线（JWT 无状态的欠账）
- [ ] 备份异地化：对象存储同步（当前每日 04:00 本地滚动 7 份）
- [ ] QQ 通道运维：掉线检测与主动提醒重扫（协议侧登录态是外部约束，按可选通道定位）
- [ ] 检索再进一步：goldset 扩金标 + 三路结果 rerank

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTRIBUTING -->
## 参与贡献

1. Fork 本仓库，建特性分支（`git checkout -b feature/AmazingFeature`）
2. 家规三条：代码注释简体中文、变量名英文；**任何行为改动必须让 351 例 pytest 全绿**，新功能补离线测试；数据库变更必须走 `alembic revision --autogenerate` 且人工检查生成物（误拆别人家的表是历史上真踩过的坑）
3. Push 分支并开 Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- LICENSE -->
## 许可证

MIT License，见 [LICENSE](LICENSE)。

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- CONTACT -->
## 联系

项目问题请开 [GitHub Issues](https://github.com/wind989/bankao/issues)。

Project Link: [https://github.com/wind989/bankao](https://github.com/wind989/bankao)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- ACKNOWLEDGMENTS -->
## 致谢

* [pgvector](https://github.com/pgvector/pgvector) · [LangGraph](https://github.com/langchain-ai/langgraph) · [NoneBot2](https://github.com/nonebot/nonebot2) · [NapCat](https://github.com/NapNapCAT/napcat)
* [uv](https://docs.astral.sh/uv/) · [FastAPI](https://fastapi.tiangolo.com) · [Vite](https://vite.dev) · [Tailwind CSS](https://tailwindcss.com)
* README 骨架取自 [Best-README-Template](https://github.com/othneildrew/Best-README-Template)

<p align="right">(<a href="#readme-top">back to top</a>)</p>

<!-- MARKDOWN LINKS & IMAGES -->
[license-shield]: https://img.shields.io/github/license/wind989/bankao?style=for-the-badge
[license-url]: LICENSE
[python-shield]: https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white
[python-url]: https://www.python.org/
[react-shield]: https://img.shields.io/badge/React_19-20232A?style=for-the-badge&logo=react&logoColor=61DAFB
[react-url]: https://reactjs.org/
[fastapi-shield]: https://img.shields.io/badge/FastAPI-019442?style=for-the-badge&logo=fastapi&logoColor=white
[fastapi-url]: https://fastapi.tiangolo.com
[pg-shield]: https://img.shields.io/badge/PostgreSQL16%2Bpgvector-336791?style=for-the-badge&logo=postgresql&logoColor=white
[pg-url]: https://www.postgresql.org/
[docker-shield]: https://img.shields.io/badge/Docker_Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white
[docker-url]: https://www.docker.com/
[tests-shield]: https://img.shields.io/badge/pytest-351_passing-649ED2?style=for-the-badge&logo=pytest&logoColor=white
[tests-url]: tests/
