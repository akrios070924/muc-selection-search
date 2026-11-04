"""Fusion-v0 / v1 / v2 字段融合策略（Issue #17 阶段 3–4，单测与评测共用）。

设计原则（用户约束，2026-10-24）：
1. **v1 完整继承**：等价归一(auto-merge)、可核验缺失补全(ocr_missing→mm_completed)、
   冲突复核(conflict→P1)、近似保留(near→P2)、非法值回退(invalid→fallback)。
2. **v2 仅在证据充分时引入受约束的多模态优先**：只对候选强项字段 college/major，
   且证据可独立核验（multimodal 取值能在 OCR 源文本中找到真实 span、字段类型合法、
   归属人物一致）时，才让多模态值优先；否则退化为 v1 行为。
3. **安全护栏（v1/v2 共用）**：
   - 城市不得以省份代替：city 字段若多模态补全值是省级（"省"结尾），不自动补全，转 P1。
   - 学历不推断：education 字段若补全值不在学历枚举，不自动补全，转 P1。
   - 专业近似但语义不同须保留冲突：near 分支永不自动合并，仅进 P2。
   - 无可信证据 → P1 人工复核，绝不冒险自动放行。
   - 运行时**绝不读取 Gold** 来选择路由；Gold 只在 evaluation 阶段离线打分。
4. **修复历史 v2 模拟偏差**：历史 v2 模拟未完整继承 v1（直接按字段覆盖 OCR），
   本实现让 v2 复用 v1 的逐分支处理逻辑，仅在 conflict×强项字段 这一处叠加受约束优先。

状态机（status，用于 auto-pass 统计）：
- ocr_default            OCR 直接采用（v0 全量；或 mm 缺失/非法）
- equiv_automerged       归一化等价，自动合并
- mm_completed           多模态补全 OCR 缺失（已通过安全护栏）
- mm_verified_priority   v2 强项字段 + 证据可核验 + 多模态优先（自动放行）
- review_required        P1/P2 复核（不自动放行）
其中前四类属 AUTO_PASS_STATUSES（见 evaluation）。

数据模型：
- 每条 route 样本：{"sample_id": str, "persons": [ {field: value, ...}, ... ]}
- 多模态样本可额外带 "_evidence": { "<person_idx>": {field: span_str} } 或
  在 person 内嵌 "_evidence": {field: span}；用于 v2 证据核验。
- source_texts：可选 {"sample_id": [per_person_ocr_text, ...]}，OCR 源文本，
  供 v2 独立核验多模态取值是否真来自可信内容；缺失则 v2 退化为 v1（保守）。
"""

from __future__ import annotations

from typing import Any, Optional

from .fields import (
    FIELDS,
    EDUCATION_ENUM,
    PROVINCE_SUFFIX_RE,
    value_invalid_reason,
    normalize,
)
from .disagreement_tiers import _tier, _norm
from .evaluation import AUTO_PASS_STATUSES  # 单一事实源（含 mm_verified_priority）

# 融合策略标签
POLICY_V0 = "v0"  # OCR 基线（完全忽略多模态）
POLICY_V1 = "v1"  # 分歧分档融合
POLICY_V2 = "v2"  # v1 + 受约束多模态优先（强项字段）
ALL_POLICIES = (POLICY_V0, POLICY_V1, POLICY_V2)

# v2 候选强项字段（仅这些字段在冲突时可尝试多模态优先）
STRONG_FIELDS = ("college", "major")


# --------------------------------------------------------------------------- #
# 安全护栏：字段级补全合法性
# --------------------------------------------------------------------------- #
def _completion_safe(field: str, value: Any) -> bool:
    """多模态补全 OCR 缺失/非法时，该值是否可安全自动采用。

    - city：省级（"省"结尾）不得作为城市补全 → 不安全。
    - education：不在学历枚举 → 不安全。
    - 其余字段：类型合法即为安全（type 合法性在调用方用 value_invalid_reason 判定）。
    """
    if value is None:
        return False
    if field == "city" and PROVINCE_SUFFIX_RE.search(str(value)):
        return False
    if field == "education" and str(value) not in EDUCATION_ENUM:
        return False
    return True


def _verifiable(mm_value: Any, evidence: Optional[str], source_text: Optional[str]) -> bool:
    """v2 强项字段优先前的独立证据核验。

    要求（全部满足才返回 True）：
    1. 多模态取值类型合法（无结构性字符/超长/非 CJK 数字等）。
    2. 存在可核验证据串，且该证据串确实出现在 OCR 源文本中（独立核验，
       而非模型自述"根据图片"之类的空泛声明）。
    3. 多模态取值的核心片段也能在 OCR 源文本中找到（取值本身有来源支撑）。

    任何一项缺失/无法核验 → 返回 False，调用方据此退化为 v1（转 P1）。
    """
    if value_invalid_reason(mm_value):
        return False
    if not evidence or not source_text:
        return False
    ev = normalize(evidence)
    src = normalize(source_text)
    if not ev or not src:
        return False
    # 证据串须真实出现在源文本（防止模型自述证据）
    if ev not in src:
        return False
    # 取值核心片段须能在源文本核验（取归一化值的较长半段，至少 2 字）
    mv = normalize(mm_value)
    if len(mv) < 2 or mv not in src:
        return False
    return True


# --------------------------------------------------------------------------- #
# 单字段融合
# --------------------------------------------------------------------------- #
def fuse_field(
    *,
    field: str,
    ocr_value: Any,
    multimodal_value: Any,
    policy: str,
    evidence: Optional[str] = None,
    source_text: Optional[str] = None,
) -> dict:
    """对单个 (field, ocr, multimodal) 三元组做融合，返回一条 decision。

    decision 字段：field, ocr_value, multimodal_value, selected_value,
    status, priority(可选 "P1"/"P2"/None), reason。
    """
    ocr_bad = bool(value_invalid_reason(ocr_value))
    mm_bad = bool(value_invalid_reason(multimodal_value))

    # ---- v0：纯 OCR 基线，完全忽略多模态 ----
    if policy == POLICY_V0:
        return {
            "field": field,
            "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": ocr_value,
            "status": "ocr_default",
            "priority": None,
            "reason": "v0-ocr-baseline",
        }

    # ---- 非法值回退（v1/v2 共用）----
    if ocr_bad and not mm_bad:
        # OCR 非法 + 多模态合法 → 补全（仍需安全护栏）
        if _completion_safe(field, multimodal_value):
            return {
                "field": field, "ocr_value": ocr_value,
                "multimodal_value": multimodal_value,
                "selected_value": multimodal_value, "status": "mm_completed",
                "priority": None, "reason": "ocr-invalid-mm-valid",
            }
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": multimodal_value, "status": "review_required",
            "priority": "P1", "reason": "ocr-invalid-mm-unsafe-completion",
        }
    if not ocr_bad and mm_bad:
        # 多模态非法 → 维持 OCR
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": ocr_value, "status": "ocr_default",
            "priority": None, "reason": "mm-invalid-keep-ocr",
        }
    if ocr_bad and mm_bad:
        # 双非法 → 复核
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": None, "status": "review_required",
            "priority": "P1", "reason": "both-invalid",
        }

    # ---- 双方取值合法：进入分歧分档 ----
    tier = _tier(ocr_value, multimodal_value, field)

    if tier == "norm_equal":
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": ocr_value, "status": "equiv_automerged",
            "priority": None, "reason": "norm-equal",
        }

    if tier == "ocr_missing":
        # OCR 缺失、多模态有值 → 补全（安全护栏）
        if _completion_safe(field, multimodal_value):
            return {
                "field": field, "ocr_value": ocr_value,
                "multimodal_value": multimodal_value,
                "selected_value": multimodal_value, "status": "mm_completed",
                "priority": None, "reason": "ocr-missing-mm-completes",
            }
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": multimodal_value, "status": "review_required",
            "priority": "P1", "reason": "ocr-missing-mm-unsafe-completion",
        }

    if tier == "mm_missing":
        # 多模态弃权 → 维持 OCR
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": ocr_value, "status": "ocr_default",
            "priority": None, "reason": "mm-missing-keep-ocr",
        }

    if tier == "near":
        # 近似但非等价：绝不自动合并，进低优先级抽查（v1/v2 一致）
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": ocr_value, "status": "review_required",
            "priority": "P2", "reason": "near-keep-ocr",
        }

    # tier == "conflict"
    if policy == POLICY_V1:
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": ocr_value, "status": "review_required",
            "priority": "P1", "reason": "conflict-v1-keep-ocr",
        }

    # policy == v2：受约束多模态优先（仅强项字段 + 证据可核验）
    if field in STRONG_FIELDS and _verifiable(multimodal_value, evidence, source_text):
        return {
            "field": field, "ocr_value": ocr_value,
            "multimodal_value": multimodal_value,
            "selected_value": multimodal_value, "status": "mm_verified_priority",
            "priority": None, "reason": "v2-strong-field-verified-priority",
        }
    # 不满足优先条件 → 退化为 v1 行为（conflict→P1）
    return {
        "field": field, "ocr_value": ocr_value,
        "multimodal_value": multimodal_value,
        "selected_value": ocr_value, "status": "review_required",
        "priority": "P1", "reason": "conflict-v2-fallback-p1",
    }


# --------------------------------------------------------------------------- #
# 样本级 / 数据集级融合
# --------------------------------------------------------------------------- #
def _person_evidence(multimodal_person: dict, person_idx: int, field: str) -> Optional[str]:
    """从多模态 person 抽取某字段的证据串（兼容两种内嵌结构）。"""
    ev = multimodal_person.get("_evidence")
    if isinstance(ev, dict):
        # 形式一：person 内 "_evidence": {field: span}
        if field in ev:
            return ev[field]
        # 形式二：样本级 "_evidence": {"<person_idx>": {field: span}}
        sub = ev.get(str(person_idx)) or ev.get(person_idx)
        if isinstance(sub, dict):
            return sub.get(field)
    return None


def fuse_sample(
    *,
    sample_id: str,
    ocr_persons: list[dict],
    multimodal_persons: list[dict],
    policy: str,
    source_texts: Optional[list[str]] = None,
) -> list[dict]:
    """融合单个样本的所有人物×字段，返回 decision 列表（带 sample_id/person_index）。"""
    decisions: list[dict] = []
    n = max(len(ocr_persons), len(multimodal_persons))
    for pi in range(n):
        ocr_p = ocr_persons[pi] if pi < len(ocr_persons) else {}
        mm_p = multimodal_persons[pi] if pi < len(multimodal_persons) else {}
        src = source_texts[pi] if (source_texts and pi < len(source_texts)) else None
        for f in FIELDS:
            ocr_v = ocr_p.get(f)
            mm_v = mm_p.get(f)
            ev = _person_evidence(mm_p, pi, f)
            d = fuse_field(
                field=f, ocr_value=ocr_v, multimodal_value=mm_v,
                policy=policy, evidence=ev, source_text=src,
            )
            d["sample_id"] = sample_id
            d["person_index"] = pi
            decisions.append(d)
    return decisions


def fuse_dataset(
    *,
    ocr_samples: list[dict],
    multimodal_samples: list[dict],
    policy: str,
    source_texts_by_sample: Optional[dict[str, list[str]]] = None,
) -> list[dict]:
    """融合整个数据集。ocr_samples / multimodal_samples 均为
    {"sample_id":..., "persons":[...]} 列表；按 sample_id 对齐。"""
    mm_by_id = {str(s.get("sample_id")): s for s in multimodal_samples}
    out: list[dict] = []
    for ocr in ocr_samples:
        sid = str(ocr.get("sample_id"))
        mm = mm_by_id.get(sid, {"sample_id": sid, "persons": []})
        src = (source_texts_by_sample or {}).get(sid)
        out.extend(fuse_sample(
            sample_id=sid,
            ocr_persons=ocr.get("persons", []),
            multimodal_persons=mm.get("persons", []),
            policy=policy,
            source_texts=src,
        ))
    return out


def run_all_policies(
    *,
    ocr_samples: list[dict],
    multimodal_samples: list[dict],
    source_texts_by_sample: Optional[dict[str, list[str]]] = None,
) -> dict[str, list[dict]]:
    """对 v0/v1/v2 三策略分别融合，返回 {policy: decisions}。"""
    return {
        p: fuse_dataset(
            ocr_samples=ocr_samples,
            multimodal_samples=multimodal_samples,
            policy=p,
            source_texts_by_sample=source_texts_by_sample,
        )
        for p in ALL_POLICIES
    }
