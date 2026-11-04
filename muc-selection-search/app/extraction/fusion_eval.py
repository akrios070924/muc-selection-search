"""Fusion-v0/v1/v2 统一评测入口（同源输入 / 同源 Gold / 同源分母）。

对比 v0(OCR 基线)、v1(分歧分档)、v2(受约束多模态优先) 在同一份
(OCR 路线, 多模态路线, Gold) 上的表现，输出：
- 七字段 strict / normalized 准确率
- 整人 / 整海报 正确率（normalized）
- 错误自动放行数 与 比例（AUTO_PASS 状态但 Gold 不符）
- P1 / P2 复核队列规模
- 失败率、延迟、成本（来自 route_meta）

本模块只消费融合产出的 decisions 与 Gold 做离线打分；融合策略本身不读取 Gold。
"""

from __future__ import annotations

from typing import Any, Optional

from .field_fusion import run_all_policies, ALL_POLICIES
from .evaluation import evaluate_fusion, RouteMeta


def run_fusion_eval(
    *,
    ocr_samples: list[dict],
    multimodal_samples: list[dict],
    gold: dict,
    source_texts_by_sample: Optional[dict[str, list[str]]] = None,
    route_meta: Optional[list[RouteMeta]] = None,
    failures: int = 0,
    total_records: int = 0,
) -> dict[str, dict]:
    """对三策略分别融合 + 评测，返回 {policy: result_dict}。"""
    policies_decisions = run_all_policies(
        ocr_samples=ocr_samples,
        multimodal_samples=multimodal_samples,
        source_texts_by_sample=source_texts_by_sample,
    )
    out: dict[str, dict] = {}
    for p in ALL_POLICIES:
        res = evaluate_fusion(
            policy=p,
            decisions=policies_decisions[p],
            gold=gold,
            route_meta=route_meta,
            failures=failures,
            total_records=total_records,
        )
        out[p] = res.to_dict()
    return out


def summarize(report: dict[str, dict]) -> dict:
    """抽取三策略关键指标对照（用于报告/打印）。"""
    rows = {}
    for p, r in report.items():
        rows[p] = {
            "macro_strict": r["macro_strict"],
            "macro_norm": r["macro_norm"],
            "auto_pass_errors": r["auto_pass_errors"],
            "auto_pass_error_ratio": r["auto_pass_error_ratio"],
            "person_accuracy_norm": r["person_accuracy_norm"],
            "poster_accuracy_norm": r["poster_accuracy_norm"],
            "p1_queue": r["p1_queue"],
            "p2_queue": r["p2_queue"],
            "failure_rate": r["failure_rate"],
        }
    return rows
