"""Fusion-v0/v1/v2 冻结合成 fixtures（Issue #17 阶段 4 离线先行）。

覆盖分支：等价归一、缺失补全（安全/不安全-城市省级/学历枚举）、多模态弃权、
近似保留(P2)、冲突(v1→P1 / v2 强项可核验→优先 / v2 强项不可核验→P1)、
非法值回退、模型异常(结构性字符)、人物对齐。

这些 fixture 锁定的只是「策略与契约正确」，不代表新 71 张上的准确率提升；
真实实验待 GLM-4.5V 真实调用数据到位后再跑统一评测。
"""

from __future__ import annotations

from typing import Any

# 每个样本：ocr_persons, multimodal_persons, source_texts(per person), gold_persons
# 字段只填与分支相关的；其余留空(None)。Gold 仅用于离线打分。

FIXTURES: dict[str, dict] = {
    # 等价归一 + 安全补全(city 非省级补全)
    "S1_norm_and_safe_complete": {
        "ocr_persons": [
            {"cohort": "2025届", "city": None, "education": "本科"},
        ],
        "mm_persons": [
            {"cohort": "2025届", "city": "临沂市", "education": "本科",
             "_evidence": {"city": "临沂市"}},
        ],
        "source_texts": ["...临沂市计算机学院2025届本科..."],
        "gold": [{"cohort": "2025届", "city": "临沂市", "education": "本科"}],
    },
    # 不安全补全：city 省级替代 / 学历非枚举 → 转 P1
    "S2_unsafe_complete": {
        "ocr_persons": [{"city": None, "education": None}],
        "mm_persons": [{"city": "山东省", "education": "学士"}],
        "source_texts": ["山东省 学士"],
        "gold": [{"city": "临沂市", "education": "本科"}],
    },
    # 近似保留：major 汉语言文学/汉语言文字学 → near → P2，绝不自动合并
    "S3_near": {
        "ocr_persons": [{"major": "汉语言文学"}],
        "mm_persons": [{"major": "汉语言文字学"}],
        "source_texts": ["汉语言文学 汉语言文字学"],
        "gold": [{"major": "汉语言文学"}],
    },
    # 冲突：education 本科/硕士(v1/v2 均 P1)；college 强项可核验 → v2 优先
    "S4_conflict_verified": {
        "ocr_persons": [{"education": "本科", "college": "计算机学院"}],
        "mm_persons": [
            {"education": "硕士", "college": "计算机科学与技术学院",
             "_evidence": {"college": "计算机科学与技术学院"}},
        ],
        "source_texts": ["计算机科学与技术学院 本科 硕士"],
        "gold": [{"education": "本科", "college": "计算机科学与技术学院"}],
    },
    # 冲突：college 强项但无 source/evidence → v2 退化为 P1（不冒险放行）
    "S4b_conflict_unverified": {
        "ocr_persons": [{"college": "计算机学院"}],
        "mm_persons": [{"college": "计算机科学与技术学院"}],
        "source_texts": None,  # 无源文本可核验
        "gold": [{"college": "计算机科学与技术学院"}],
    },
    # v0 基线：忽略多模态。city ocr 错 mm 对 → v0 自动放行错误；v1/v2 转 P1
    "S5_v0_baseline": {
        "ocr_persons": [{"education": "本科", "city": "潍坊市"}],
        "mm_persons": [{"education": "博士", "city": "青岛市"}],
        "source_texts": ["本科 青岛 潍坊"],
        "gold": [{"education": "本科", "city": "青岛市"}],
    },
    # 非法值回退 + 模型异常
    "S6_invalid": {
        "ocr_persons": [
            {"major": "@@@##", "college": "###"},   # ocr 非法
            {"major": "软件工程", "college": "<<x>>"},  # mm 非法
        ],
        "mm_persons": [
            {"major": "软件工程", "college": "@@@"},   # mm 合法 / 非法
            {"major": "<<garbage>>", "college": "自动化"},  # mm 非法 / 合法
        ],
        "source_texts": ["软件工程 自动化"],
        "gold": [
            {"major": "软件工程", "college": "自动化"},
            {"major": "软件工程", "college": "自动化"},
        ],
    },
    # 两人物对齐 + 强项可核验(person0, 真冲突) vs 不可核验(person1)
    "S7_two_persons": {
        "ocr_persons": [
            {"college": "机械学院"},          # 误读为机械学院
            {"college": "电子学院"},
        ],
        "mm_persons": [
            {"college": "软件工程学院", "_evidence": {"college": "软件工程学院"}},
            {"college": "电子与信息工程学院"},
        ],
        "source_texts": ["软件工程学院 机械", "电子 信息"],
        "gold": [
            {"college": "软件工程学院"},
            {"college": "电子与信息工程学院"},
        ],
    },
}


def load_fusion_fixtures() -> tuple[list[dict], list[dict], dict[str, list[str]], dict]:
    """返回 (ocr_samples, mm_samples, source_texts_by_sample, gold_dict)。

    gold_dict = {"sample_results": [{"sample_id": sid, "persons": [...]}]}
    与 evaluation.evaluate_fusion 的 gold 入参格式一致。
    """
    ocr_samples: list[dict] = []
    mm_samples: list[dict] = []
    source_texts_by_sample: dict[str, list[str]] = {}
    gold_samples: list[dict] = []

    for idx, (sid, spec) in enumerate(FIXTURES.items()):
        sample_id = f"FIX-{idx:02d}"
        ocr_samples.append({"sample_id": sample_id, "persons": spec["ocr_persons"]})
        mm_samples.append({"sample_id": sample_id, "persons": spec["mm_persons"]})
        if spec["source_texts"]:
            source_texts_by_sample[sample_id] = spec["source_texts"]
        gold_samples.append({"sample_id": sample_id, "persons": spec["gold"]})

    gold = {"sample_results": gold_samples}
    return ocr_samples, mm_samples, source_texts_by_sample, gold


# 便于测试断言的「期望分支命中」速查：
# (policy, sample_id, person_index, field, expected_status)
EXPECTED: list[tuple[str, str, int, str, str]] = [
    # v0：纯 OCR 基线
    ("v0", "FIX-00", 0, "cohort", "ocr_default"),
    ("v0", "FIX-00", 0, "city", "ocr_default"),
    ("v0", "FIX-05", 0, "education", "ocr_default"),
    ("v0", "FIX-05", 0, "city", "ocr_default"),
    # v1：完整继承分支
    ("v1", "FIX-00", 0, "cohort", "equiv_automerged"),
    ("v1", "FIX-00", 0, "city", "mm_completed"),
    ("v1", "FIX-00", 0, "education", "equiv_automerged"),
    ("v1", "FIX-01", 0, "city", "review_required"),       # 省级替代 → P1
    ("v1", "FIX-01", 0, "education", "review_required"),   # 非枚举 → P1
    ("v1", "FIX-02", 0, "major", "review_required"),       # near → P2
    ("v1", "FIX-03", 0, "education", "review_required"),   # conflict → P1
    ("v1", "FIX-03", 0, "college", "review_required"),     # conflict → P1
    ("v1", "FIX-04", 0, "college", "review_required"),     # 强项但无源 → P1
    ("v1", "FIX-05", 0, "education", "review_required"),   # conflict → P1
    ("v1", "FIX-05", 0, "city", "review_required"),        # conflict → P1
    ("v1", "FIX-06", 0, "major", "mm_completed"),          # ocr 非法 → 补全
    ("v1", "FIX-06", 0, "college", "review_required"),     # 双非法 → P1
    ("v1", "FIX-06", 1, "major", "ocr_default"),           # mm 非法 → 维持 ocr
    ("v1", "FIX-06", 1, "college", "mm_completed"),        # ocr 非法 → 补全
    ("v1", "FIX-07", 0, "college", "review_required"),     # 强项可核验? v1 一律 P1
    ("v1", "FIX-07", 1, "college", "review_required"),
    # v2：v1 + 受约束多模态优先（仅强项可核验时）
    ("v2", "FIX-00", 0, "cohort", "equiv_automerged"),
    ("v2", "FIX-00", 0, "city", "mm_completed"),
    ("v2", "FIX-00", 0, "education", "equiv_automerged"),
    ("v2", "FIX-01", 0, "city", "review_required"),
    ("v2", "FIX-01", 0, "education", "review_required"),
    ("v2", "FIX-02", 0, "major", "review_required"),       # near 永不自动合并
    ("v2", "FIX-03", 0, "education", "review_required"),   # 非强项 → P1
    ("v2", "FIX-03", 0, "college", "mm_verified_priority"),  # 强项 + 可核验 → 优先
    ("v2", "FIX-04", 0, "college", "review_required"),     # 强项但无源 → 退 P1
    ("v2", "FIX-05", 0, "education", "review_required"),
    ("v2", "FIX-05", 0, "city", "review_required"),
    ("v2", "FIX-06", 0, "major", "mm_completed"),
    ("v2", "FIX-06", 0, "college", "review_required"),
    ("v2", "FIX-06", 1, "major", "ocr_default"),
    ("v2", "FIX-06", 1, "college", "mm_completed"),
    ("v2", "FIX-07", 0, "college", "mm_verified_priority"),  # person0 可核验
    ("v2", "FIX-07", 1, "college", "review_required"),       # person1 无证据 → P1
]
