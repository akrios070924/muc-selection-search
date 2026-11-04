"""离线评测口径（Fusion-v0/v1/v2 同源输入/同源 Gold/同源分母）。

提供：七字段 strict/normalized 匹配、整人/整海报正确率、错误自动放行统计、
P1/P2 队列、失败率、延迟与成本聚合。评测只消费融合产出的 decisions，绝不反向
选择路由——Gold 仅用于离线打分。

本模块不读取任何多模态/Gold 来决定融合策略；`run_fusion_eval` 的调用方负责把
OCR 路线、多模态路线、Gold 按样本对齐后喂进来。
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from .disagreement_tiers import _norm
from .fields import ALL7

# 自动放行类 status：这些决策会把多模态/OCR 值直接选中且**不进复核队列**，
# 若与 Gold 不符即为"错误自动放行"（这是融合策略要严控的指标）。
# 注意：与 field_fusion.AUTO_PASS_STATUSES 同源——field_fusion 从本模块导入，
# 此处是单一事实源，新增 v2 的 "mm_verified_priority" 必须在此登记。
AUTO_PASS_STATUSES = frozenset({
    "same_value", "equiv_automerged", "mm_completed", "ocr_default",
    "mm_verified_priority",
})

# 字段权重无需加权，全部等权（macro = 各字段准确率均值）。


def _match_strict(gold_value: Any, selected_value: Any) -> bool:
    """严格匹配：原值逐字符相等（含 None==None）。"""
    return gold_value == selected_value


def _match_norm(gold_value: Any, selected_value: Any, field_name: str) -> bool:
    """归一化匹配：字段级归一化后相等；None 与空串等价。"""
    gv = _norm(gold_value, field_name)
    sv = _norm(selected_value, field_name)
    return gv == sv and gv != "" or (gv == "" and sv == "")


@dataclass
class RouteMeta:
    """单条路线的运行元数据（用于延迟/成本/分类统计）。"""
    name: str
    kind: str = "test-stub"          # real-api | cache-replay | test-stub
    latency_s: float = 0.0
    cost: float = 0.0
    first_attempt_failure_rate: float = 0.0


@dataclass
class FusionEvalResult:
    policy: str
    denominator_fields: int = 0
    correct_strict: int = 0
    correct_norm: int = 0
    auto_pass_errors: int = 0                 # 自动放行但 Gold 不符的字段数
    field_strict: dict[str, dict] = dc_field(default_factory=dict)
    field_norm: dict[str, dict] = dc_field(default_factory=dict)
    persons_total: int = 0
    persons_correct_norm: int = 0
    posters_total: int = 0
    posters_correct_norm: int = 0
    p1_queue: int = 0
    p2_queue: int = 0
    failure_rate: float = 0.0
    route_meta: list = dc_field(default_factory=list)

    def macro_strict(self) -> float:
        n = sum(v["total"] for v in self.field_strict.values())
        c = sum(v["correct"] for v in self.field_strict.values())
        return (c / n) if n else 0.0

    def macro_norm(self) -> float:
        n = sum(v["total"] for v in self.field_norm.values())
        c = sum(v["correct"] for v in self.field_norm.values())
        return (c / n) if n else 0.0

    def auto_pass_error_ratio(self) -> float:
        return (self.auto_pass_errors / self.denominator_fields) if self.denominator_fields else 0.0

    def to_dict(self) -> dict:
        return {
            "policy": self.policy,
            "macro_strict": round(self.macro_strict(), 4),
            "macro_norm": round(self.macro_norm(), 4),
            "correct_strict": self.correct_strict,
            "correct_norm": self.correct_norm,
            "denominator_fields": self.denominator_fields,
            "auto_pass_errors": self.auto_pass_errors,
            "auto_pass_error_ratio": round(self.auto_pass_error_ratio(), 4),
            "field_strict": self.field_strict,
            "field_norm": self.field_norm,
            "persons_total": self.persons_total,
            "persons_correct_norm": self.persons_correct_norm,
            "person_accuracy_norm": round(self.persons_correct_norm / self.persons_total, 4) if self.persons_total else 0.0,
            "posters_total": self.posters_total,
            "posters_correct_norm": self.posters_correct_norm,
            "poster_accuracy_norm": round(self.posters_correct_norm / self.posters_total, 4) if self.posters_total else 0.0,
            "p1_queue": self.p1_queue,
            "p2_queue": self.p2_queue,
            "failure_rate": round(self.failure_rate, 4),
            "route_meta": [vars(m) for m in self.route_meta],
        }


def evaluate_fusion(
    *,
    policy: str,
    decisions: list[dict],
    gold: dict[str, Any],
    route_meta: list[RouteMeta] | None = None,
    failures: int = 0,
    total_records: int = 0,
) -> FusionEvalResult:
    """对一组融合 decisions 用 Gold 离线打分。

    decisions 每项含：sample_id, person_index, field, ocr_value, multimodal_value,
    selected_value, status, priority, reason。gold 为 {sample_id: [person,...]}。
    评测不读取 Gold 决定融合，只按 (sample_id, person_index, field) 对齐打分。
    """
    result = FusionEvalResult(policy=policy)
    if route_meta:
        result.route_meta = list(route_meta)

    gold_by_sample: dict[str, list] = gold.get("samples", gold.get("sample_results", []))
    gold_map: dict[str, list] = {}
    for s in gold_by_sample:
        gold_map[str(s.get("sample_id"))] = s.get("persons", [])

    # 初始化字段统计
    for f in ALL7:
        result.field_strict[f] = {"total": 0, "correct": 0}
        result.field_norm[f] = {"total": 0, "correct": 0}

    # 按样本/人物聚合，便于算整人/整海报正确率
    person_hits: dict[tuple, bool] = {}
    poster_person_ok: dict[str, list] = {}
    poster_ok: dict[str, bool] = {}

    for d in decisions:
        sid = str(d["sample_id"])
        pi = d["person_index"]
        f = d["field"]
        gpersons = gold_map.get(sid, [])
        gv = gpersons[pi].get(f) if pi < len(gpersons) else None

        # 仅统计 Gold 非空的"可判定"字段（与冻结口径一致：分母 = 非空 Gold 字段数）
        if gv is None:
            continue
        result.denominator_fields += 1
        result.field_strict[f]["total"] += 1
        result.field_norm[f]["total"] += 1

        strict_ok = _match_strict(gv, d["selected_value"])
        norm_ok = _match_norm(gv, d["selected_value"], f)
        if strict_ok:
            result.correct_strict += 1
            result.field_strict[f]["correct"] += 1
        if norm_ok:
            result.correct_norm += 1
            result.field_norm[f]["correct"] += 1

        # 错误自动放行：status 属自动放行且归一化不符
        if d["status"] in AUTO_PASS_STATUSES and not norm_ok:
            result.auto_pass_errors += 1

        # 整人/整海报聚合（基于归一化）
        key = (sid, pi)
        if key not in person_hits:
            nfields = len([x for x in gpersons[pi].values() if x is not None]) if pi < len(gpersons) else 0
            person_hits[key] = (nfields, 0)
        total, correct = person_hits[key]
        person_hits[key] = (total, correct + (1 if norm_ok else 0))

        poster_person_ok.setdefault(sid, [])
        if pi >= len(poster_person_ok[sid]):
            poster_person_ok[sid].append(norm_ok)
        else:
            poster_person_ok[sid][pi] = norm_ok

    # 汇总整人/整海报
    for (sid, pi), (total, correct) in person_hits.items():
        result.persons_total += 1
        if total > 0 and correct == total:
            result.persons_correct_norm += 1
    for sid, lst in poster_person_ok.items():
        result.posters_total += 1
        if lst and all(lst):
            result.posters_correct_norm += 1

    # 复核队列
    for d in decisions:
        if d.get("status") == "review_required":
            if d.get("priority") == "P1":
                result.p1_queue += 1
            elif d.get("priority") == "P2":
                result.p2_queue += 1

    # 失败率（路线抽取/解析失败占记录数比例）
    if total_records:
        result.failure_rate = failures / total_records

    return result
