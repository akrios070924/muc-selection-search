"""选调研抽取字段字典与通用归一化工具（Issue #17 / Fusion-v0/v1/v2 共用）。

这是 Fusion 系列与评测脚本的单一事实源之一：任何字段口径变更都必须从这里出发，
保证「运行时融合」「分档分析」「离线评测」三处口径不会漂移。
"""

from __future__ import annotations

import re

# 七字段（与 evaluation.ALL7 / field_fusion.FIELDS 同一集合，顺序无关）
FIELDS = ("cohort", "grade", "education", "college", "major", "city", "position_or_unit")

# 评测口径的七字段（与 FIELDS 相同的冻结集合，专供评测脚本逐字段遍历）
ALL7 = FIELDS

# 学历枚举（多模态词典硬校验目标；不在枚举即 review_required，不拦截路由）
EDUCATION_ENUM = frozenset({"本科", "硕士", "博士", "大专", "研究生", "中专", "高中"})

# 届别格式：20XX届
COHORT_RE = re.compile(r"^\d{4}届$")

# 专业后缀（"XX专业" 记为命中专业词典——只记录，不作门）
MAJOR_SUFFIX_RE = re.compile(r"专业$")

# 本地专业词典（覆盖不完整，仅 34 条；命中只记录信号，未命中不等于非法）。
# 历史登记：20 样本 43 个多模态 major 取值里 21 个不在词典，硬门会误杀真实分歧。
MAJOR_TERMS = (
    "法学", "法律", "汉语言文学", "汉语言文字学", "计算机科学与技术", "软件工程",
    "计算机技术", "电子信息", "电子信息工程", "通信工程", "会计学", "财务管理",
    "工商管理", "公共管理", "行政管理", "经济学", "金融学", "国际经济与贸易",
    "贸易经济", "市场营销", "人力资源管理", "思想政治教育", "政治学与行政学",
    "社会学", "社会工作", "心理学", "应用心理学", "数学与应用数学", "统计学",
    "物理学", "化学", "生物学", "英语", "日语", "新闻学", "广播电视学",
    "历史学", "考古学", "哲学", "宗教学", "逻辑学", "机械工程", "电气工程",
    "土木工程", "水利工程", "环境工程", "环境科学", "医学", "临床医学",
    "药学", "护理学", "农学", "园艺", "林学", "动物医学", "建筑学",
)

MAJOR_TERM_SET = frozenset(MAJOR_TERMS)

# 城市不得被省份替代：多模态若只给到省级（以"省"结尾且无下级市），不得作为
# 城市的晋级证据（Fusion-v2 强项路由的硬性护栏）。
PROVINCE_SUFFIX_RE = re.compile(r"省$")

# 值形态上限：语料实测最长 16（position_or_unit），留足余量只拦明显垃圾。
MAX_VALUE_LEN = 64
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_PLAIN_NUMERIC_RE = re.compile(r"^\d{1,6}$")
_STRUCTURAL_CHARS = frozenset('{}[]<>\\"')


def normalize(value) -> str:
    """通用归一化：去空白/全角空格/中文标点并小写。

    只承担"去噪"语义，不做业务字段改写（业务改写在 disagreement_tiers._norm）。
    """
    if value is None:
        return ""
    return re.sub(r"[\s\u3000，。、“”‘’（）()\[\]{}]", "", str(value)).lower()


def value_invalid_reason(value) -> str:
    """值形态硬校验。返回空串表示合法，否则返回可直接落进审计的原因。

    与 field_fusion._value_invalid_reason 同源（这里直接复用逻辑，避免漂移）。
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return f"value_type:{type(value).__name__}"
    text = value.strip()
    if not text:
        return ""  # 空串等同缺失，不算非法
    if len(text) > MAX_VALUE_LEN:
        return "value_too_long"
    if any(ch in _STRUCTURAL_CHARS for ch in text):
        return "value_has_structural_chars"
    if any(ord(ch) < 0x20 for ch in text):
        return "value_has_control_char"
    if _CJK_RE.search(text) or _PLAIN_NUMERIC_RE.match(text):
        return ""
    return "value_not_cjk_or_numeric"
