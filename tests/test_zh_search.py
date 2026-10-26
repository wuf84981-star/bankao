# ============================================================
# S9 中文分词腿离线单测（zh_tokenizer + search 融合）
#
# 断言主线（三条，全是真机踩过的坑）：
#① 专名保整词：「基期量」不许被切成「基期/量」——切碎了这块讲义就永远
#    检索不到（jieba 自带词典无此词，靠 CUSTOM_WORDS 灌进去）；
# ② 停用词不入查询：「的/了/怎么」这类虚词剔掉，否则命中一整片无关块；
#    但英文数字必须留（GDP、3.5%、729 题号是公考检索的真入口）；
# ③ tsquery拼装安全：分词后只可能出现字母数字与 CJK，拼不出
#    tsquery 的运算符语法（'&' ':' '!'），注入不进来。
#
# 铁律：本文件零 DB 零电厂——纯函数断言，绝不因测试烧用户的钱。
# ============================================================
from backend.search import rrf_fuse
from backend.zh_tokenizer import STOPWORDS, cut_words, ts_input, tsquery_from


# ── ① 专名保整词 ──

def test_专名不被切碎():
    """公考核心专名必须整词进索引——切碎则检索彻底失效。"""
    assert "基期量" in cut_words("基期量怎么计算")
    assert "现期量" in cut_words("现期量除以1加增长率等于基期量吗")
    assert "增长贡献率" in cut_words("资料分析的增长贡献率怎么算")
    assert "隔年增长" in cut_words("隔年增长率怎么求")


def test_专名不被误拆():
    """回归防线：jieba 自带词典会把「基期量」切成「基期/量」
    （实测分词输出：基期/量/怎么/计算）。这条断言守着自定义词典别被误删。"""
    words = cut_words("基期量")
    assert words == ["基期量"], f"「基期量」被切成了 {words}——自定义词典失效"


# ── ② 停用词与虚词剔除，英文数字保留 ──

def test_停用词被剔除():
    """虚词不进查询串——留着会让 tsquery 命中一大片无关块。"""
    words = cut_words("基期量怎么计算")
    assert "怎么" not in words
    assert "的" not in words
    assert "什么" not in cut_words("这是什么题型")


def test_英文数字保留():
    """资料分析靠字母与数字检索——GDP、3.5%、729 必须在。"""
    words = cut_words("GDP增长3.5%是什么概念")
    assert "gdp" in words# 大小写归一：避免 GDP 与 gdp 分成两套词项
    assert "3.5%" in words


def test_空输入不炸():
    """空串与纯虚词串都必须安全返回——不抛异常、不产出坏SQL。"""
    assert ts_input("") == ""
    assert tsquery_from("   ") == ""
    assert ts_input("的了和是在") == ""      # 纯停用词 → 空分词串（该块不进索引）


# ── ③ tsquery 拼装安全与正确性 ──

def test_查询串用OR():
    """默认 OR：问句普遍是「X 怎么算」这种多成分结构，
    AND 语义会要求同块全含这些词，讲义里没人这么写 → 候选清空。"""
    q = tsquery_from("基期量怎么计算")
    assert " | " in q
    assert " & " not in q


def test_查询串可注入字符被挡():
    """分词后只允许字母数字与 CJK，拼不出 tsquery 运算符语法。"""
    q = tsquery_from("基期量 | 恶意 & 注入 : !")
    # 所有运算符都成了普通词项的一部分，或被分词器切掉，不会成为语法
    assert ":" not in q
    assert "!" not in q
    # 且每个片段都是纯词（可安全 OR 连接）
    for term in q.split(" | "):
        assert term.strip() == term
        assert all(ch.isalnum() or ord(ch) > 0x2E80 for ch in term)


def test_停用词表非空且含关键虚词():
    """停用词表自身的完整性——空表等于过滤失效（静默退化，最难发现）。"""
    assert len(STOPWORDS) > 20
    for w in ("的", "了", "怎么", "什么", "请问"):
        assert w in STOPWORDS


# ── RRF 三腿融合（融合骨架零改动，但要证明三腿确实等价于多腿）──

def test_三腿融合与两腿等价_并集情形():
    """三腿传进 rrf_fuse 应正常合议——腿数从 2 变 3 是骨架的本职能力。
    验证：一块若在三腿都排第 1，分数 = 3/(60+1)，高于只排第 1 的一块。"""
    three = rrf_fuse([[10, 20], [10, 30], [10, 40]])
    top_id, top_score = three[0]
    assert top_id == 10, "三腿都排第一的块必须胜出"
    assert top_score == round(3 / 61, 6)


def test_融合纯函数不碰库():
    """rrf_fuse 是纯函数（离线可测）——签名不该被这次改造改坏。
    注意它默认只返 TOP_K=3 条（D82 乙定案 2026-10-18，评测裁决，PRD v2.11），
    传 6 个 id 进来只出 3 条是正确行为，不是漏块。"""
    out = rrf_fuse([[1, 2, 3], [4, 5, 6]])
    assert len(out) == 3, "融合后按 TOP_K 截断到 3 条（v2.11 口径）"
    assert all(isinstance(cid, int) for cid, _ in out)
    # 缺席腿零贡献：块 1 只在第一腿排第 1，分数应低于两腿都排第 1 的块
    scores = dict(out)
    assert scores[1] == round(1 / 61, 6), "单腿第 1 名只拿一份贡献"
    assert scores[4] == round(1 / 61, 6), "第二腿第 1 名同样一份，两块同分"
    # 排序按分降序（1 与 4 同分时按 id 升序稳定排序；第 3 席给次档的块 2）
    assert [cid for cid, _ in out] == [1, 4, 2]


def test_融合可显式传top_k():
    """融合层不写死条数——调用方能要几条给几条（聊天腿随 TOP_K=3，
    调试窗等显式要数的各给各的）。"""
    assert len(rrf_fuse([[1, 2, 3], [4, 5, 6]], top_k=10)) == 6