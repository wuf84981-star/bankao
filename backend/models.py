# ============================================================
# 表模型 —— 字段对齐 PRD 13.1「账号与会话」，先立最小三表：
# users（人）→ conversations（一次会话）→ messages（话本身）
# 这三份 Python 定义就是建表图纸，Alembic 照它生成迁移（代码=真源）。
# ============================================================
from datetime import date, datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


def now() -> datetime:
    """统一开时间戳：UTC，别让每张表各写一套时区土办法"""
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)   # 户口不许重号（Alembic 会追这道锁）
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))   # 开发占位，鉴权上线时换真哈希
    status: Mapped[str] = mapped_column(String(32), default="normal")   # PRD：normal/注销冷静期
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)      # 户主旗号（D49 甲）：注册时 email 对上 env BANKAO_ADMIN_EMAIL 才盖
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16), default="web")     # PRD：web/qq
    title: Mapped[str] = mapped_column(String(255), default="新会话")
    context_summary: Mapped[str | None] = mapped_column(Text)           # 滚动摘要，S4 才喂
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))   # user/assistant/tool（PRD 13.1）
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)   # S1 以字数占位，S2 接真模型换真 token
    # 本轮回答引用的资料块（S3 引用刀）：[{chunk_id,material_id,title,seq}…]；
    # 出处由后端工具执行时记账，不靠回读模型正文——刷新回显、将来跳回原文都吃这份账
    citations: Mapped[list | None] = mapped_column(JSONB, default=None)
    # 每日提醒戳（S6 二刀 · F-33 · D24 甲）：非空=这行是系统当天主动开口的提醒，
    # 显式落「哪一天」（服务器本地日，与计划账同一天钟）——不拿 created_at 反推，
    # 戳跨时区算日期是一团浑水。三用：送达可查（进会话账历史可看）、
    # 防重发（remind_on==今天 等值判）、三刀 QQ 挂后的站内补偿腿同形状复用。
    remind_on: Mapped[date | None] = mapped_column(Date)
    # QQ 推送状态（S6 三刀 · D26 甲「账是本、QQ 是嘴」）：仅提醒行有用——
    # NULL=该户没绑 QQ（本就不推）/'fail'=推了没成（补偿窗内下档重试）/'ok'=嘴也到过。
    # 「过点没推上」这笔账必须有地方躺，30 分钟重试才不用翻 created_at 猜时区。
    push_state: Mapped[str | None] = mapped_column(String(8))
    # 拍照汇报的原图账（S7 四刀 · F-09 · D37/D38 甲）：仅 user 行有用——
    # [{kind:'file',path,…}|{kind:'url',url,…}…]。网页端落私有目录记路径，
    # QQ 端图在腾讯云上、二次落盘是假动作（D38 甲），只记出处不假收藏。
    # 9.1「只进文本」的凭据：进大脑的转写永远在 content 里，image_refs 只是
    # 原图的回溯线索——撤回删文件（AC③）与将来管理页都吃这份账。
    image_refs: Mapped[list | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UsageLog(Base):
    """用量流水（PRD 12.6/F-35）：每次模型成功调用记一行，按日聚合扣配额。
    失败不入账=BR-11 的天然落实（根本不会被写进来）。"""
    __tablename__ = "usage_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[object] = mapped_column(Date)   # 归属日（服务器本地日期为账期）
    tokens: Mapped[int] = mapped_column(Integer)   # prompt+completion 真用量合计
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── 资料与检索两表（S3 入仓边 · PRD 13.3 原样；索引不在此画，归迁移手写）──

class Material(Base):
    """资料户口（PRD 13.3）：一份文件一行。parse_status 三态让"半成品"也有名分；
    embedding_model 预留位——换模型=全库重嵌（13.6 条款3），旧向量是谁嵌的要查得到。"""
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str | None] = mapped_column(String(32))   # NULL=通用资料（BR-25）；考试档案表归 S4
    title: Mapped[str] = mapped_column(String(255))             # 用户视角的文件名
    storage_path: Mapped[str] = mapped_column(String(512))      # 原件落盘位置（重嵌/跳回全文的根）
    file_type: Mapped[str] = mapped_column(String(16))          # pdf/txt/md
    parse_status: Mapped[str] = mapped_column(String(16), default="parsing")   # parsing/ready/failed
    parse_error: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(String(64))   # 点火后才写 "text-embedding-v3"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Chunk(Base):
    """可检索小块（PRD 13.3）：embedding 可空 + embed_status 垫底——
    两段式入库：存字不要 key（pending 挂账），点火刀回填坐标翻 done。
    user_id/exam_type 冗余携带（13.6 条款2：检索过滤免 join，隔离无法被绕过——D4 拍板）。
    subject/chapter 此刀留空：切块器升级成吐结构化元组归检索刀（D3 裁过归属）。"""
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str | None] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(String(64))
    chapter: Mapped[str | None] = mapped_column(String(128))
    seq: Mapped[int] = mapped_column(Integer)                   # 块在原文里的座次
    content: Mapped[str] = mapped_column(Text)                  # 原文块——引用可跳回的底气
    token_count: Mapped[int] = mapped_column(Integer, default=0)   # 字数占位，同messages 那笔校准账
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))   # 1024 绑 v3（PRD 729），改维度=迁库大事
    embed_status: Mapped[str] = mapped_column(String(16), default="pending")   # done/pending
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    # S9 中文分词全文检索腿（分词在 Python 侧做，DB 只存结果——同向量点火的家法）。
    # 为什么不用生成列/触发器：jieba 是 Python 包，跑在 backend 箱；向量库在
    # db 箱。两个箱之间没有共享解释器，PG 侧触发器调不到 jieba（plpython3 要装
    # C 扩展插件，pgvector 官方镜像不带，为一列索引去编译镜像不值得）。
    # 为什么不用生成列：生成列禁止 UPDATE，存量块回填会被 PG 直接拒
    # （cannot update a generated column），而老资料库不重新上传也得能立刻被
    # 检索到——回填是这刀的核心动作。故两列皆普通列：
    # content_tokenized = jieba 分词后的空格串本体（to_tsvector 是只算函数，
    # 反向导不出词项，不存本体就无法重建索引）；content_tsv = 它的 tsvector 投影。
    # 两条写入路径负责填：解析入库那条（parsing/jobs 侧）与 ignite 点火那条，
    # 外加本刀迁移的存量回填脚本，三处都调 zh_tokenizer.ts_input()。
    #【S4 第二刀血案家法】索引必须登记进 __table_args__，否则下次 autogenerate
    # 当孤儿 DROP_INDEX 静默拆除——真机 27 例翻案，两条 GIN 都在此挂号。
    content_tokenized: Mapped[str | None] = mapped_column(Text)
    content_tsv: Mapped[str | None] = mapped_column(TSVECTOR)

    __table_args__ = (
        Index("ix_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        # user_id 是整列——GIN 没有整型默认操作族，必须借 btree_gin 扩展的
        # int4_ops（名字不带 _gin 后缀，2026-10-11 真机两轮试错钉死；
        # 与迁移 c7d3f9a1e204 的 CREATE EXTENSION btree_gin 配套）
        Index("ix_chunks_user_tsv", "user_id", "content_tsv",
              postgresql_using="gin", postgresql_ops={"user_id": "int4_ops"}),
    )


# ── 记忆表族开山（S4 首刀 · PRD 13.1 行 658 原样）──

class ExamProfile(Base):
    """考试档案（v2.3 新增表的落地）：每用户每场考试一行——一切考试日期与
    倒计时从本表取值，模型禁止心算（BR-21 的执行载体，get_current_time 转正靠它）。
    同一时刻恰有一场主考（is_primary=true，F-41 多考试一主一辅）：
    让位逻辑在写入端（save_exam_profile 先降级再晋级），DB 层再钉一道部分唯一索引
    当兜底闸——代码有 bug 也不许出现俩主考。
    【S4 第二刀血案】此闸最初只在迁移里 op.execute 手写、metadata 无户口，
    被下一次 autogenerate 当孤儿 drop_index 静默拆除（真机 27 例翻案当场抓获）。
    现登记进 __table_args__：metadata 认识它，autogenerate 从此只维护不猎杀。"""
    __tablename__ = "exam_profiles"
    __table_args__ = (
        Index("uq_exam_profiles_primary", "user_id", unique=True,
              postgresql_where=text("is_primary")),   # 部分唯一：只管 is_primary=true 的行
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str] = mapped_column(String(32))          # 公考/事考…（与 chunks.exam_type 同名联动）
    exam_date: Mapped[object] = mapped_column(Date)             # 考试日（Date 无时区：日历日就该是日历日）
    target_desc: Mapped[str | None] = mapped_column(Text)       # 目标描述（"上岸省厅"之类口述）
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)
    weekly_reserved_minutes: Mapped[int] = mapped_column(Integer, default=0)   # 每周预留（S5 计划喂数）
    # S5 第一刀扩两列（PRD 4.1④「工作日/周末每天几小时」此前全文无落库位置——勘行）：
    # V2 校验的地面真源。NULL=未声明 → generate_plan 被 V2 拒、提示先问用户。
    weekday_minutes: Mapped[int | None] = mapped_column(Integer)
    weekend_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="in-progress")     # in-progress/paused/done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── 偏好档案两表（S4 第二刀 · PRD 13.1 行 657 + 13.4 行 686）──

class AgentSetting(Base):
    """用户对 Agent 的设定（PRD 13.1）：一户一行，user_id 兼作主键。
    3.2 命名系统：agent_name 落库后组装器注入自称指令；
    remind_time 归 S6 QQ 管家、custom_prompt 是 P1 预留位——建表留列，不提前喂模型。
    active_exam_type 只是 exam_profiles 的冗余缓存（PRD 661：以档案表为准）。"""
    __tablename__ = "agent_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    agent_name: Mapped[str | None] = mapped_column(String(32))
    persona: Mapped[str | None] = mapped_column(Text)
    custom_prompt: Mapped[str | None] = mapped_column(Text)
    remind_time: Mapped[str | None] = mapped_column(String(8))
    active_exam_type: Mapped[str | None] = mapped_column(String(32))
    # D58 甲 2026-09-11（用户拍板联网腿用 Tavily）：兜底联网总闸，默认关——
    # 「只有用户打开这个开关才会联网」写进数据默认值，不靠 prompt 自觉。
    web_search_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # D60 甲 2026-09-11（用户拍板七路模型清单）：每户选定的对话模型。
    # NULL=从没换过（读侧兜向 llm.DEFAULT_MODEL）——默认值活在代码一处，
    # 不把「当时的默认」冻进每一行历史账，日后改默认只改 llm.py。
    model_choice: Mapped[str | None] = mapped_column(String(48))
    # D81 甲 2026-10-12（挂招牌刀·用户拍板）：教学轨用户级开关。
    # NULL=从没动过=开（默认档活在 teaching_track.user_teaching_on 一处，
    # 与 model_choice 同法不冻默认）；False=这户的问题全走事务轨直答。
    # env 旗 TEACHING_TRACK_ENABLED 仍是运维总闸，两级串联：总闸关=人人不出图。
    teaching_mode: Mapped[bool | None] = mapped_column(Boolean)
    # D89（2026-10-18 用户拍板·费曼加招）：费曼式检验意愿闸——教学轨内
    # 15 招规则表里 FEYNMAN 这一招的开档。NULL=从没动过=开（默认档活在
    # teaching_track.user_feynman_on 一处，与 teaching_mode 同法不冻默认）；
    # False=自称懂了也不请他复述。子闸从属大门：teaching_mode 关了没有
    # 教学轨，本闸无从生效（设置页文案标明）。
    feynman_mode: Mapped[bool | None] = mapped_column(Boolean)
    # 2026-10-31（用户拍板·自带钥匙 BYOK）：户自己的 DeepSeek API key。
    # NULL/空=没接（全走平台钥匙+积分）；有值=本户 deepseek 平台的对话电厂
    # 改用这把钥匙，且对话不扣积分（orchestrator/stream/教学轨三腿同一闸语义）。
    # ⚠️ 明文存储（熟人期决定：与 .env 同信任域——库在户主自己机器上）；
    #    执法边界：只进电厂请求头，永不进 API 回显（读侧只回掩码）、永不进日志。
    #    dashscope/zhipu 平台不吃此钥匙（OCR/向量点火照旧平台账）。
    own_deepseek_key: Mapped[str | None] = mapped_column(Text)


class MemoryFact(Base):
    """摘要事实（PRD 13.4）：一 fact 一账（UNIQUE 三键 upsert 的根）。
    BR-02 轻版闭环（D10 甲案）：user_stated 天然生效；inferred 可存但 confirmed=false
    → 注入排除（存而不生效），用户亲口确认后模型以 user_stated 重存同 key 自动升格。
    知识点类走 knowledge_mastery 不在此表（13.4 注释原话，归第三刀）。"""
    __tablename__ = "memory_facts"
    __table_args__ = (UniqueConstraint("user_id", "category", "key", name="uq_memory_facts_lookup"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(16))   # profile/goal/habit/emotion_long
    key: Mapped[str] = mapped_column(String(64))        # 账名：同 (user,category,key) 只一本
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="user_stated")     # user_stated/inferred
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)             # 推测必 false（后端强制）
    exam_type: Mapped[str | None] = mapped_column(String(32))                  # 考试相关事实才填，通用 NULL
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── 学习进度两表（S4 第三刀 · PRD 13.4 行 690~698 · D9 甲案：平铺一层）──

class KnowledgeNode(Base):
    """知识树节点（F-21 的存储底座）：本刀只建**根层平铺**（parent_id 恒 NULL，
    用户口述一个知识点=建一个根节点）；三级树/资料解析生树/可视化编辑归计划出题阶段。
    PRD 的 UNIQUE(user_id, exam_type, parent_id, name) 在 PG 里 NULL≠NULL 不互斥——
    照抄=根节点同名双胎漏闸。拆成两条部分唯一索引：根层一条、子层一条（将来建树即用），
    并全部登记进 __table_args__（第二刀血案：手写库对象不上 metadata 户口=autogenerate 收尸）。"""
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        Index("uq_knowledge_nodes_root", "user_id", "exam_type", "name",
              unique=True, postgresql_where=text("parent_id IS NULL")),
        Index("uq_knowledge_nodes_child", "user_id", "exam_type", "parent_id", "name",
              unique=True, postgresql_where=text("parent_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str | None] = mapped_column(String(32))   # 列形遵 PRD 可空；工具层强制非空（NULL 会绕开唯一闸）
    subject: Mapped[str | None] = mapped_column(String(64))     # 科目（本刀口述可空）
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_nodes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))              # 知识点名（树内模糊匹配的靶子）
    source: Mapped[str] = mapped_column(String(16), default="user_edit")  # material_analysis/user_edit/seed；本刀口述=user_edit
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeMastery(Base):
    """知识点掌握度（PRD 694 原样）：一知识点一行，level 五档中文枚举在工具层验伤；
    confidence 0~100 支撑「同级微调免确认」（BR-01，重闭环随 S5）；tags 建列留空转
    （无工具参数=不提前喂模型，AgentSetting.custom_prompt 先例）。kp_ref 外键 RESTRICT：
    PRD「节点删除须先查 mastery 引用」的 DB 级看门狗。"""
    __tablename__ = "knowledge_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "exam_type", "kp_ref", name="uq_knowledge_mastery_lookup"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(String(64))
    kp_ref: Mapped[int] = mapped_column(ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"))
    level: Mapped[str] = mapped_column(String(16))              # 未接触/初步了解/一般掌握/熟练/薄弱
    confidence: Mapped[int] = mapped_column(Integer, default=50)   # 0~100，工具层验界
    tags: Mapped[list | None] = mapped_column(ARRAY(String(32)))
    user_note: Mapped[str | None] = mapped_column(Text)
    last_learned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── 计划表族（S5 第一刀 · PRD 13.5 行 712~716）──

class Plan(Base):
    """计划版本（F-22）：一用户一考试多版（重生成 version+1 旧版留档，AC③）。
    「同一时刻至多一个 active」由部分唯一索引钉死——与主考闸同闸法，且已登记
    __table_args__（S4 第二刀血案：手写库对象不上 metadata 户口=autogenerate 拆闸）。
    status 在 PRD 的 active/archived 之外加一档 draft（D12 往返）：校验全过先生成
    草案，用户点头 activate_plan 才转正——计划不许模型单方生效（PRD 713
    「不满足校验不允许激活」的正向表达）；勘行已记。"""
    __tablename__ = "plans"
    __table_args__ = (
        Index("uq_plans_active", "user_id", "exam_type", unique=True,
              postgresql_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[object] = mapped_column(Date)
    sprint_start_date: Mapped[object] = mapped_column(Date)   # 校验器 V4 推导所得，落库供展示/提醒
    status: Mapped[str] = mapped_column(String(16), default="draft")   # draft/active/archived
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PlanItem(Base):
    """逐日任务（PRD 714）：打卡状态机 pending/done/partial/skipped 归第二刀消化，
    本刀只落 pending。user_id 冗余（隔离+「今日任务」注入免 join，S3 chunks 先例）。
    kp_ref 可空（冲刺日可能没有知识点）但给了就必须真实存在——V3 防编造闸在
    校验器里查，DB 层 FK RESTRICT 是第二道：计划引用中的节点不许被单删（S4 看门狗同款）。"""
    __tablename__ = "plan_items"
    __table_args__ = (
        Index("ix_plan_items_user_date", "user_id", "date"),   # 组装器查今日任务用
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[object] = mapped_column(Date)
    subject: Mapped[str | None] = mapped_column(String(64))
    kp_ref: Mapped[int | None] = mapped_column(ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"))
    task_desc: Mapped[str] = mapped_column(Text)
    est_minutes: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str | None] = mapped_column(String(16))   # new/exercise/review/mock/sprint
    # D20 勘账（第三刀）：首刀拿 kind 过 V4 校验后没落库=用完即弃——
    # F-25「挤占冲刺」警告与改类型全靠这列，补列并修首刀 INSERT。历史行 NULL 可空。
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending/done/partial/skipped
    done_note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PlanChangeLog(Base):
    """计划改动留痕（PRD 716 · F-24③「有理由、有去向、可回看」）：
    actor 三源——user 手改 / agent 商量调整 / life_event 事件适配（S6）。
    snapshot 存改动前关键状态（JSONB），回看不靠模型回忆。"""
    __tablename__ = "plan_change_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    actor: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── 时效生活事件（S6 首刀 · PRD 13.4 行 704 · F-15/F-26 · D22 甲案减量往返）──

class LifeEvent(Base):
    """时效记忆（6.3.6）：出差/加班这类一次性事件，区间内计划自动减压、到期自清。
    比 PRD 原样**少一列 expire_at**（已勘行）：「最后一天 24:00 失效」的语义由
    「每日 03:00 清理 + 条件 end_at < 今天」完全等价承载——少一列时间戳少一种时区雷
    （exam_date 先例：日历日就该是 Date）。
    type 列遵 PRD 形制但本刀工具闸只收一次性——周期性（「每周三加班」）按 6.3.6 规则 5
    转 memory_facts(habit)，不建时效条目；列留着不喂模型。
    applied_at 一列两用：NULL=事件已登记、计划未减（create 不碰计划，用户点头才
    apply——D22 甲），非 NULL=减过（apply 防重入闸）。恢复建议的真值不在本表——
    事件行次日被 03:00 物理删（6.3.6③ 原文「不再生效」），靠的是 apply 时 change_logs
    快照里的 end_date：「end=昨天」这个等式只真一天，无状态一次性触发。"""
    __tablename__ = "life_events"
    __table_args__ = (
        Index("ix_life_events_user_range", "user_id", "end_at"),   # 组装器每轮查「覆盖今天的事件」
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text)                     # 「去杭州出差」事件本体也要落账
    type: Mapped[str] = mapped_column(String(16), default="one_time")   # one_time；periodic 预留不用
    start_at: Mapped[object] = mapped_column(Date)
    end_at: Mapped[object] = mapped_column(Date)
    impact_note: Mapped[str | None] = mapped_column(Text)          # 备考调整说明（口述可空）
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # NULL=待确认；非空=已减量
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── QQ 绑定账（S6 三刀 · PRD 13.1 行 665 · F-34 · D27 甲：发起只在网页端）──

class QQBinding(Base):
    """QQ 号 ⇄ 平台账号的户口。PRD 原列组缺两样，补齐后勘行：
    code_expires_at（10 分钟有效要有时限戳）与 fail_count（错 3 次作废要有秤）。
    user_id 上 UNIQUE——一人绑一 QQ（PRD 只钉了「一号只一主」方向，换绑流程
    按 1:1 立形状：网页点「绑定/换绑」= 本行重置 pending 发新码，旧 QQ 失效）。
    一列三态：pending=码已发生效中等 QQ 上门；bound=已通；invalid=错 3 次作废
    （等用户网页重新发码）。bind_code 绑成即清——一次性，账上不留过期钥匙。"""
    __tablename__ = "qq_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    qq_number: Mapped[str | None] = mapped_column(String(32), unique=True)   # 未绑到时为空
    bind_code: Mapped[str | None] = mapped_column(String(6))
    code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending/bound/invalid
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── 出题与答题两表（S7 首刀 · PRD 13.5 行 729~735 · F-27/28）──

class Question(Base):
    """题库（F-27）：一题一行，**题面与答案同表分列**——「判分前不下发答案」
    这道防泄题闸的执行点是出口不是存储：工具回执逐字段拼装、永不带 answer/
    analysis（tests 钉死），DB 里答案一直躺着（判分腿要从这里对答案）。
    kp_ref 外键 RESTRICT 与 mastery 同形制：题引用的节点不许被单删。
    user_id/exam_type 冗余携带（13.6 条款2 老规矩：隔离过滤免 join）。
    embedding 建列留空转——变式去重归后续刀（S5 预建列先例：列有家、腿后到）；
    status 列为首刀预建（第三刀 F-31 报错下架即用 active/reporting，免再迁一次）；
    source uploaded 值预留（用户导真题归后话）。"""
    __tablename__ = "questions"
    __table_args__ = (
        Index("ix_questions_user_kp", "user_id", "kp_ref"),   # 补充二五步判定按这个查存量
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16), default="llm")     # llm/uploaded
    subject: Mapped[str | None] = mapped_column(String(64))
    kp_ref: Mapped[int] = mapped_column(ForeignKey("knowledge_nodes.id", ondelete="RESTRICT"))
    qtype: Mapped[str] = mapped_column(String(8))                      # single/fill（short 归二刀）
    difficulty: Mapped[str] = mapped_column(String(8), default="mid")  # easy/mid/hard
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSONB)                # ["A.…","B.…"]；fill 为空
    answer: Mapped[str] = mapped_column(Text)                          # fill 多可接受答案用｜分隔
    analysis: Mapped[str] = mapped_column(Text)
    pitfall_hint: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))   # 空转位（变式去重后用）
    status: Mapped[str] = mapped_column(String(16), default="active")  # active/reporting（三刀 F-31）
    report_note: Mapped[str | None] = mapped_column(Text)              # 三刀：用户报错原话（核查队列的案卷）
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class QuizAttempt(Base):
    """答题记录（F-28）：**问题即建 pending 行**（user_answer 空）——
    计时起点因此天然落在「题到手那一刻」，duration_sec=判分时刻−created_at，
    不靠模型报时（BR-21 同款：数字归程序）。append-only：重做同题=新行，
    历史事实不覆盖（plan_items 的 done 不许改同一立场）。
    thinking_note/error_pattern_ref 预建空列（PRD 原形在册）——二刀错误沉淀上岗；
    question_id CASCADE：题被删（报错下架的管理腿）其答题史随行消灭，不留孤儿。"""
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        Index("ix_attempts_user_question", "user_id", "question_id"),   # 新鲜度判定：近7天做过没
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_answer: Mapped[str | None] = mapped_column(Text)              # NULL=未判分（pending）
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    thinking_note: Mapped[str | None] = mapped_column(Text)            # 二刀：判分时的思路诊断
    error_pattern_ref: Mapped[int | None] = mapped_column(
        ForeignKey("error_patterns.id", ondelete="SET NULL"))          # 二刀 2b：错题证据链，
        # 模式被删（用户清账）记录留题去 ref——SET NULL：事实（答错过）不该被派生账抹掉
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
        # 三刀 F-31②：题被报错下架，其判分记录标失效（时间戳=审计线，NULL=有效）；
        # 「计入错误模式时排除」= 连续全对统计与沉淀回滚都认这一列
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ErrorPattern(Base):
    """错误模式账（F-29 · PRD 13.4 行 707 · D31 甲）：五类 category 是代码枚举
    （审题/公式/逻辑/习惯/知识漏洞）——归类闸程序执法；「同义模式算不算老毛病」
    才交模型语义判（match_id 只认注入清单里真实存在的 id，编的作废=真值覆盖闸同款）。
    count 归程序加（BR-21），错题证据链=quiz_attempts.error_pattern_ref 反查，
    不另立中间表。resolved 给三刀「已克服」确认留位。"""
    __tablename__ = "error_patterns"
    __table_args__ = (
        Index("ix_error_patterns_user", "user_id", "exam_type", "resolved"),  # 归类腿取未结案清单
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_type: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str | None] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(16))   # 五类枚举在 tools 层闸，DB 不设 CHECK（S4 挂账同款）
    description: Mapped[str] = mapped_column(Text)       # 一句话模式（如「把基期看成现期」）
    count: Mapped[int] = mapped_column(Integer, default=1)
    last_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)   # 三刀「已克服」翻这个位
    tags: Mapped[list | None] = mapped_column(JSONB)                 # 越档归类的「待观察」旗挂这
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EmailCode(Base):
    """邮箱验证码账（S8 首刀 · F-01 · D52 甲）：只存哈希不存明文——和不存明文密码
    同一个理由：库被兜走，码不至于全裸奔。三闸参数 PRD 钉死：10 分钟过期、
    错 5 次作废、单邮箱日限 10 条；used_at=消费章（一码一用，建号同事务盖章）。
    purpose 列预建 'reset' 位——找回密码（F-03/D48）复用同一条腿，免再迁移。
    形借 S6 绑定码三件套（code_expires_at/fail_count），只是投递口 QQ 换邮件。"""
    __tablename__ = "email_codes"
    __table_args__ = (
        Index("ix_email_codes_email", "email", "purpose", "created_at"),  # 日限计数/取最新活码
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(16), default="register")   # register/reset 一腿两用途
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalyticsEvent(Base):
    """埋点账（S8 四刀 · PRD 13.7/24.1 · D55 甲）：append-only 行为流水——
    只记「谁在什么时候干了什么」+小属性（channel 这类），**永不记消息正文与资料内容**
    （PRD 24 章隐私口径焊死在函数层：_track 只收 str/int/bool 形状的 props）。
    服务的判断：激活漏斗（注册→进门→开口）、周活跃（北极星）、事件异常。
    户删账随（CASCADE）——注销的人不留行为流水，隐私口径的尾巴。"""
    __tablename__ = "analytics_events"
    __table_args__ = (
        Index("ix_analytics_event_time", "event", "created_at"),   # 管理页按事件计数/时间窗
        Index("ix_analytics_user_time", "user_id", "created_at"),  # 周活跃：某户近7天有无开口
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(64))
    props: Mapped[dict | None] = mapped_column(JSONB, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── 积分流水账（S8 · D64 甲 · 2026-09-11 用户拍板：积分=资产，进=注册赠送+每日签到，出=对话消耗）──

class PointsLedger(Base):
    """积分的一本流水（usage_logs 同款立场）：**余额不落列，只从流水加总导出**——
    append-only 事实行改不了也赖不掉，任何时刻余额可复算可审计；户主手动发放/扣减
    也走同一本账（kind=adjust），不存在「后台偷偷改数字」的第二扇门。
    kind 五值：bonus 注册赠送 / checkin 每日签到 / streak 连签满 7 天奖 /
    consume 对话消耗（负数）/ adjust 户主调整（正负皆有）——枚举闸在 points.py 写侧，
    DB 不设 CHECK（error_patterns 挂账同款：脏值拦在代码层，库层留改地）。
    day 是账期归属日（服务器本地日，与 usage_logs 同一天钟）：「今天签没签」
    按 (user_id, kind, day) 等值判，不拿 created_at 反推时区（remind_on 血案家法）。"""
    __tablename__ = "points_ledger"
    __table_args__ = (
        Index("ix_points_ledger_user_day", "user_id", "day"),   # 余额/今日消耗/连签回溯都吃这对
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[object] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(Integer)                # 正=进账，负=出账
    note: Mapped[str | None] = mapped_column(Text)              # 人话凭据（「消耗 · GLM-5.3 ×3 · 3421 tokens」）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── 知识缺口账（S9 · W3 刀 2026-10-11：讲义答不上的题，旁路记一笔）──

class KnowledgeGap(Base):
    """用户问了、讲义里没找到（或只擦边）的问题清单——户主补弹药的本子。
    旁账立场（施工图钉死）：写在消费端 tools.search_materials，**不写在
    search() 核心**——/api/search 调试窗狂问不许污染这本账；record_gap
    自吞异常，永不拖垮答题正线。
    两线两职（同币种向量余弦、不许混用）：闸线 REL_THRESHOLD=0.30 裁
    「能不能喂教练」，登记线 GAP_WEAK=0.60 裁「要不要进待补账」。
    top_score 空=zero（向量零分/零命中），有分且低于登记线=weak。
    与 knowledge_mastery.confidence（0~100 整数）是两个币种，互不换算。"""
    __tablename__ = "knowledge_gaps"
    __table_args__ = (
        Index("ix_knowledge_gaps_user_created", "user_id", "created_at"),  # 按户倒序翻账
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)                    # 原句（截 500 字防巨物）
    top_score: Mapped[float | None] = mapped_column(Float)         # 向量腿最高分；空=zero
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web/qq（Conversation 同谱）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


