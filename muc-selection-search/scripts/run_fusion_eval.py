#!/usr/bin/env python3
"""Fusion-v0/v1/v2 统一评测脚本（CLI 入口 / 可复现运行命令）。

用法：
  # 1) 离线冻结合成 fixtures（无需真实数据，验证策略与契约）
  python scripts/run_fusion_eval.py --mode fixtures \
      --out reports/extraction/week4/fusion_eval_fixtures.json

  # 2) 真实/缓存回放评测（待 GLM-4.5V 真实数据到位后）
  python scripts/run_fusion_eval.py --mode live \
      --ocr reports/extraction/week4/ocr_route.json \
      --mm  reports/extraction/week4/glm_chain/glm_chain_check.json \
      --gold data/gold/gold_71.json \
      --source reports/extraction/week4/ocr_source_texts.json \
      --ocr-kind cache-replay --mm-kind real-api \
      --out reports/extraction/week4/fusion_eval_live.json

说明：
- 三策略(v0/v1/v2)共享同一份 (OCR, 多模态, Gold)，分母一致，可横向对比。
- route 分类(real-api / cache-replay / test-stub)写入 route_meta，明确区分
  真实调用、缓存回放与测试桩，不混入准确率结论。
- 脚本绝不读取 Gold 选择融合路由；Gold 只在打分阶段使用。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许以脚本方式直接运行：把项目根加入 sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.extraction.fusion_eval import run_fusion_eval, summarize  # noqa: E402
from app.extraction.evaluation import RouteMeta  # noqa: E402

# 冻结合成 fixtures（离线先行）
from tests.extraction.fixtures.fusion_fixtures import (  # noqa: E402
    load_fusion_fixtures,
)


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _to_route_meta(args) -> list[RouteMeta]:
    return [
        RouteMeta(name="ocr", kind=getattr(args, "ocr_kind", "cache-replay")),
        RouteMeta(name="multimodal", kind=getattr(args, "mm_kind", "real-api")),
    ]


def _run_fixtures(args) -> dict:
    ocr_samples, mm_samples, src, gold = load_fusion_fixtures()
    meta = [RouteMeta(name="ocr", kind="test-stub"),
            RouteMeta(name="multimodal", kind="test-stub")]
    report = run_fusion_eval(
        ocr_samples=ocr_samples,
        multimodal_samples=mm_samples,
        gold=gold,
        source_texts_by_sample=src,
        route_meta=meta,
    )
    return report


def _run_live(args) -> dict:
    ocr = _load_json(args.ocr)
    mm = _load_json(args.mm)
    gold = _load_json(args.gold)
    ocr_samples = ocr.get("sample_results") or ocr.get("samples") or []
    mm_samples = mm.get("records") or mm.get("sample_results") or mm.get("samples") or []
    src = None
    if args.source:
        src = _load_json(args.source)
    meta = _to_route_meta(args)
    report = run_fusion_eval(
        ocr_samples=ocr_samples,
        multimodal_samples=mm_samples,
        gold=gold,
        source_texts_by_sample=src,
        route_meta=meta,
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Fusion-v0/v1/v2 统一评测")
    ap.add_argument("--mode", choices=["fixtures", "live"], default="fixtures")
    ap.add_argument("--ocr", help="OCR 路线结果 JSON")
    ap.add_argument("--mm", help="多模态路线结果 JSON")
    ap.add_argument("--gold", help="Gold JSON")
    ap.add_argument("--source", help="OCR 源文本 JSON（v2 证据核验用）")
    ap.add_argument("--ocr-kind", choices=["real-api", "cache-replay", "test-stub"],
                    default="cache-replay")
    ap.add_argument("--mm-kind", choices=["real-api", "cache-replay", "test-stub"],
                    default="real-api")
    ap.add_argument("--out", required=True, help="评测报告输出路径")
    args = ap.parse_args()

    if args.mode == "fixtures":
        report = _run_fixtures(args)
    else:
        if not (args.ocr and args.mm and args.gold):
            print("--mode live 需要 --ocr/--mm/--gold", file=sys.stderr)
            return 2
        report = _run_live(args)

    summary = summarize(report)
    # route_meta 在 eval 结果中已是 vars() 后的 dict 列表
    route_meta_list = report.get("v0", {}).get("route_meta", [])
    out_doc = {
        "mode": args.mode,
        "route_meta": {m["name"]: m["kind"] for m in route_meta_list},
        "summary": summary,
        "full": report,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_doc, f, ensure_ascii=False, indent=2)

    # 打印简明对照
    print("=" * 64)
    print(f"Fusion 评测（mode={args.mode}）")
    print("=" * 64)
    header = f"{'policy':<6}{'strict':>9}{'norm':>9}{'autoErr':>9}{'auto%':>8}{'P1':>5}{'P2':>5}{'pers%':>8}{'post%':>8}"
    print(header)
    for p in ("v0", "v1", "v2"):
        s = summary[p]
        print(f"{p:<6}{s['macro_strict']*100:>8.2f}{s['macro_norm']*100:>9.2f}"
              f"{s['auto_pass_errors']:>9}{s['auto_pass_error_ratio']*100:>7.2f}"
              f"{s['p1_queue']:>5}{s['p2_queue']:>5}"
              f"{s['person_accuracy_norm']*100:>8.2f}{s['poster_accuracy_norm']*100:>8.2f}")
    print(f"\n报告已写入: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
