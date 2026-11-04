"""分歧分档（Fusion-v1/v2 与冻结分析共用，单一事实源）。

分档口径（Issue #17 阶段3，2026-10-16 统一）：
- ocr_missing：OCR 为空、多模态有值 → 候选补全
- mm_missing ：多模态弃权（空）、OCR 有值 → 维持 OCR
- norm_equal：语义等价（归一化全等 或 互相包含）→ 自动归一合并
- near      ：高相似但非等价（如 汉语言文字学/汉语言文学）→ 保留冲突进低优先级抽查
- conflict  ：真冲突 → 维持 OCR 进高优先级复核

`_tier` 是运行时融合与 `reports/extraction/week3/disagreement_tiers.json` 登记分析的
同一实现；冻结分析登记的「106→17、91.27%→95.64%」必须由本函数同口径复现，
回归测试锁定两者一致。
"""

from __future__ import annotations

from .fields import normalize


def _norm(value, field: str) -> str:
    """字段级归一化：先通用去噪，再按字段剥业务后缀。

    - grade：剥 "级"（2020级 → 2020）
    - cohort：剥 "届"（2025届 → 2025）
    - city ：剥尾部 市/区/县（临沂市 → 临沂；但"山东省临沂"靠包含关系处理）
    - 其余字段只做通用去噪。
    """
    s = normalize(value)
    if not s:
        return ""
    if field == "grade":
        s = s.rstrip("级")
    elif field == "cohort":
        s = s.rstrip("届")
    elif field == "city":
        s = s.rstrip("市区县")
    return s


def _levenshtein(a: str, b: str) -> int:
    """标准编辑距离（两字符串均较短，无需优化）。"""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[lb]


def _contains(na: str, nb: str) -> bool:
    return bool(na) and bool(nb) and (na in nb or nb in na)


def _equiv(a, b, field: str) -> bool:
    """两值是否语义等价：归一化全等 或 互相包含。"""
    if a is None or b is None:
        return False
    na, nb = _norm(a, field), _norm(b, field)
    if na == nb:
        return True
    return _contains(na, nb)


def _near(a, b, field: str) -> bool:
    """高相似但非等价：归一化长度均 ≥ 4 且编辑距离 ≤ 2。

    命中只表示"疑似同一实体，需人工确认"，绝不自动合并。
    用于 major（汉语言文字学/汉语言文学，距离 1）等近似专业；
    短字符串（如 city 临沂/潍坊，长 2）不进 near，直接判 conflict。
    """
    if a is None or b is None:
        return False
    na, nb = _norm(a, field), _norm(b, field)
    if not na or not nb:
        return False
    if len(na) < 4 or len(nb) < 4:
        return False
    return _levenshtein(na, nb) <= 2


def _tier(ocr_value, multimodal_value, field: str) -> str:
    """对一对 (OCR值, 多模态值) 分档。

    注意参数顺序固定为 (ocr_value, multimodal_value)；ocr_missing / mm_missing
    据此区分方向。两者皆空视为无分歧（norm_equal）。
    """
    ov, mv = ocr_value, multimodal_value
    if ov is None and mv is None:
        return "norm_equal"
    if ov is None:
        return "ocr_missing"
    if mv is None:
        return "mm_missing"
    if _equiv(ov, mv, field):
        return "norm_equal"
    if _near(ov, mv, field):
        return "near"
    return "conflict"
