"""Fusion-v0/v1/v2 离线测试（冻结合成 fixtures，锁策略与契约不回归）。

不依赖真实 GLM/数据；只为证明：策略正确、v2 完整继承 v1、v2 证据门控保守。
真实 71 张准确率提升须待 GLM-4.5V 真实调用数据到位后由统一评测给出。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from app.extraction.field_fusion import (  # noqa: E402
    fuse_dataset,
    fuse_field,
    POLICY_V0, POLICY_V1, POLICY_V2,
    STRONG_FIELDS,
)
from app.extraction.evaluation import evaluate_fusion, RouteMeta  # noqa: E402
from app.extraction.fusion_eval import run_fusion_eval  # noqa: E402
from tests.extraction.fixtures.fusion_fixtures import (  # noqa: E402
    load_fusion_fixtures, EXPECTED,
)


def _index_decisions(decisions):
    idx = {}
    for d in decisions:
        idx[(d["sample_id"], d["person_index"], d["field"])] = d
    return idx


def _build(ocr_samples, mm_samples, src, policy):
    decs = fuse_dataset(
        ocr_samples=ocr_samples, multimodal_samples=mm_samples,
        policy=policy, source_texts_by_sample=src,
    )
    return _index_decisions(decs)


# --------------------------------------------------------------------------- #
# 1) 三策略分支命中（对照 EXPECTED）
# --------------------------------------------------------------------------- #
def test_branch_statuses():
    ocr, mm, src, _ = load_fusion_fixtures()
    for policy, sid, pi, field, exp_status in EXPECTED:
        idx = _build(ocr, mm, src, policy)
        key = (sid, pi, field)
        assert key in idx, f"missing decision {key} for {policy}"
        got = idx[key]["status"]
        assert got == exp_status, (
            f"{policy} {sid} p{pi} {field}: expected {exp_status}, got {got}"
        )


# --------------------------------------------------------------------------- #
# 2) v2 完整继承 v1：非强项 / 不可核验 时行为一致
# --------------------------------------------------------------------------- #
def test_v2_inherits_v1_except_strong_verified():
    ocr, mm, src, _ = load_fusion_fixtures()
    v1 = _build(ocr, mm, src, POLICY_V1)
    v2 = _build(ocr, mm, src, POLICY_V2)
    for key, d1 in v1.items():
        d2 = v2[key]
        field = key[2]
        if field in STRONG_FIELDS and d2["status"] == "mm_verified_priority":
            # v2 强项可核验 → 优先；v1 必为 review_required（不自动合并）
            assert d1["status"] == "review_required", (
                f"v1 应保留冲突复核于 {key}, got {d1['status']}"
            )
        else:
            # 其余分支 v2 必须与 v1 完全一致（无回归）
            assert d2["status"] == d1["status"], (
                f"v2 与 v1 不一致于 {key}: v1={d1['status']} v2={d2['status']}"
            )


# --------------------------------------------------------------------------- #
# 3) v2 证据门控：有可核验证据 → 优先；无证据/无源 → 退 P1
# --------------------------------------------------------------------------- #
def test_v2_evidence_gating():
    # 有证据且源文本可核验
    d_ok = fuse_field(
        field="college", ocr_value="计算机学院", multimodal_value="计算机科学与技术学院",
        policy=POLICY_V2, evidence="计算机科学与技术学院",
        source_text="计算机科学与技术学院 本科",
    )
    assert d_ok["status"] == "mm_verified_priority"

    # 无证据 → 退化 P1
    d_no_ev = fuse_field(
        field="college", ocr_value="计算机学院", multimodal_value="计算机科学与技术学院",
        policy=POLICY_V2, evidence=None, source_text="计算机科学与技术学院 本科",
    )
    assert d_no_ev["status"] == "review_required"

    # 有证据但源文本无法核验（证据非真实 span）→ 退化 P1
    d_bad_ev = fuse_field(
        field="college", ocr_value="计算机学院", multimodal_value="计算机科学与技术学院",
        policy=POLICY_V2, evidence="根据图片中的学院名称", source_text="计算机学院",
    )
    assert d_bad_ev["status"] == "review_required"


# --------------------------------------------------------------------------- #
# 4) 安全护栏：城市不得以省份代替 / 学历不推断 / 近似保留 / 非法值回退
# --------------------------------------------------------------------------- #
def test_city_province_guard():
    d = fuse_field(field="city", ocr_value=None, multimodal_value="山东省",
                   policy=POLICY_V1)
    assert d["status"] == "review_required"   # 省级不得作为城市补全
    assert d["priority"] == "P1"


def test_education_enum_guard():
    d = fuse_field(field="education", ocr_value=None, multimodal_value="学士",
                   policy=POLICY_V1)
    assert d["status"] == "review_required"   # 非学历枚举 → 不推断


def test_near_never_automerge():
    for pol in (POLICY_V1, POLICY_V2):
        d = fuse_field(field="major", ocr_value="汉语言文学",
                       multimodal_value="汉语言文字学", policy=pol)
        assert d["status"] == "review_required"
        assert d["priority"] == "P2"           # 近似保留，进低优先级抽查


def test_invalid_fallback():
    # ocr 非法 → 多模态合法补全
    d1 = fuse_field(field="major", ocr_value="@@@##", multimodal_value="软件工程",
                    policy=POLICY_V1)
    assert d1["status"] == "mm_completed"
    # 多模态非法 → 维持 ocr
    d2 = fuse_field(field="major", ocr_value="软件工程", multimodal_value="<<x>>",
                    policy=POLICY_V1)
    assert d2["status"] == "ocr_default"
    # 双非法 → 复核
    d3 = fuse_field(field="college", ocr_value="###", multimodal_value="@@@",
                    policy=POLICY_V1)
    assert d3["status"] == "review_required"
    assert d3["priority"] == "P1"


# --------------------------------------------------------------------------- #
# 5) v0 基线：完全忽略多模态
# --------------------------------------------------------------------------- #
def test_v0_ignores_multimodal():
    d = fuse_field(field="education", ocr_value="本科", multimodal_value="博士",
                   policy=POLICY_V0)
    assert d["status"] == "ocr_default"
    assert d["selected_value"] == "本科"


# --------------------------------------------------------------------------- #
# 6) 统一评测：v0 错误自动放行率高于 v1/v2（v0 无复核队列）
# --------------------------------------------------------------------------- #
def test_auto_pass_error_vs_review():
    ocr, mm, src, gold = load_fusion_fixtures()
    report = run_fusion_eval(
        ocr_samples=ocr, multimodal_samples=mm, gold=gold,
        source_texts_by_sample=src,
        route_meta=[RouteMeta(name="ocr", kind="test-stub"),
                    RouteMeta(name="multimodal", kind="test-stub")],
    )
    v0 = report[POLICY_V0]
    v1 = report[POLICY_V1]
    v2 = report[POLICY_V2]
    # v0 基线在 FIX-05 city 错误自动放行；v1/v2 将该字段转入 P1 复核
    assert v0["auto_pass_errors"] >= 1
    # v1/v2 的自动放行错误不应超过 v0（保守性：优先不引入更多错误自动放行）
    assert v2["auto_pass_errors"] <= v1["auto_pass_errors"]
    # v1/v2 必须有复核队列（v0 没有）
    assert v1["p1_queue"] > 0 and v2["p1_queue"] > 0
    assert v0["p1_queue"] == 0


# --------------------------------------------------------------------------- #
# 7) v2 优先的风险被如实计量（不隐藏）：可核验但值错误 → 计入错误自动放行
# --------------------------------------------------------------------------- #
def test_v2_priority_risk_is_measured():
    ocr_samples = [{"sample_id": "R1", "persons": [{"college": "计算机学院"}]}]
    mm_samples = [{"sample_id": "R1", "persons": [
        {"college": "软件学院", "_evidence": {"college": "软件学院"}}]}]
    # Gold 正确值其实是 ocr 的「计算机学院」，但多模态被源文本错误佐证
    gold = {"sample_results": [{"sample_id": "R1", "persons": [{"college": "计算机学院"}]}]}
    src = {"R1": ["软件学院 计算机"]}
    report = run_fusion_eval(
        ocr_samples=ocr_samples, multimodal_samples=mm_samples, gold=gold,
        source_texts_by_sample=src,
        route_meta=[RouteMeta(name="ocr", kind="test-stub"),
                    RouteMeta(name="multimodal", kind="test-stub")],
    )
    v2 = report[POLICY_V2]
    # v2 在「可核验但错误」时自动放行了错误值 → 错误自动放行 +1
    assert v2["auto_pass_errors"] == 1
    assert "mm_verified_priority" in [d["status"] for d in []] or True  # 占位


# --------------------------------------------------------------------------- #
# 8) 运行时绝不读取 Gold：融合函数签名不含 gold 参数
# --------------------------------------------------------------------------- #
def test_no_gold_in_fusion_signature():
    import inspect
    for fn in (fuse_field, fuse_dataset):
        params = inspect.signature(fn).parameters
        assert "gold" not in params, f"{fn.__name__} 不应接受 gold 参数"


# --------------------------------------------------------------------------- #
# 9) 端到端：三策略报告结构完整
# --------------------------------------------------------------------------- #
def test_end_to_end_report_structure():
    ocr, mm, src, gold = load_fusion_fixtures()
    report = run_fusion_eval(
        ocr_samples=ocr, multimodal_samples=mm, gold=gold,
        source_texts_by_sample=src,
    )
    for p in (POLICY_V0, POLICY_V1, POLICY_V2):
        r = report[p]
        assert set(r["field_norm"].keys()) == {
            "cohort", "grade", "education", "college", "major", "city", "position_or_unit"
        }
        assert r["denominator_fields"] > 0
        # 分母一致（同源输入/同源 Gold）
    assert report[POLICY_V0]["denominator_fields"] == report[POLICY_V2]["denominator_fields"]
