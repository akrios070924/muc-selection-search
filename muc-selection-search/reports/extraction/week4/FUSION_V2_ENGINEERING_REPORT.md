# Fusion-v2 工程准备报告（Issue #17 阶段 3–4）

> 关联：Issue #17 任务 3（P1，Fusion-v2 同源评测）
> 分支：`feat/week4-B-fusion-v2`（commit `1ddc401`，基于 `master` `a00c3e0`，独立于 #24）
> 日期：2026-10-26

---

## 0. 一句话结论

**工程侧已全部完成**：Fusion-v2 策略、统一评测入口、离线测试、冻结基线验证、专用分支齐备，
离线回归 **12/12 通过**。但**真实实验尚待数据**——必须等 GLM-4.5V（或负责人登记的替代型号）
完成 71 张真实调用、字段归一后，才能下"融合是否优于最佳单模型"的结论。**本报告不预设结论，
不沿用历史 20 张 96.36% 模拟值冒充本轮实验结果。**

---

## 1. 交付物清单

| # | 交付 | 路径 | 说明 |
|---|------|------|------|
| (1) | Fusion-v2 实现 | `app/extraction/field_fusion.py` | v0/v1/v2 三策略 + 可调用入口 |
| (1) | 支撑模块（单一事实源） | `app/extraction/fields.py`、`disagreement_tiers.py`、`evaluation.py` | MAJOR_TERMS、归一、分歧分档、指标 |
| (2) | 评测库 | `app/extraction/fusion_eval.py` | 同源/Gold/分母一致的统一评测 |
| (2) | 评测 CLI | `scripts/run_fusion_eval.py` | `--mode {fixtures\|real\|replay} --out <path>` |
| (2) | 测试 | `tests/extraction/test_field_fusion.py` | 12 个离线测试 |
| (2) | 冻结 fixtures | `tests/extraction/fixtures/fusion_fixtures.py` | 覆盖各分支的合成样本 |
| (3) | 离线评测产物 | `reports/extraction/week4/fusion_eval_fixtures.json` | 见第 4 节 |
| (5) | 本报告 | `reports/extraction/week4/FUSION_V2_ENGINEERING_REPORT.md` | — |
| (4) | 进度 | `progress/week4/B/PROGRESS.md`（切片 13） | — |

---

## 2. Fusion-v2 策略与可调用入口

### 2.1 三策略（v0 → v1 → v2 逐步增强，v2 完整继承 v1）

- **v0（OCR 基线）**：完全忽略多模态，仅取 OCR 值；无复核、无自动放行保护。
- **v1（分歧分档融合）**：
  - 等价归一自动合并（`equiv_automerged`）
  - OCR 缺失且多模态可核验 → 补全（`mm_completed`）
  - 实质性冲突 → **P1 人工复核**（`review_required`，不冒险放行）
  - 近似/可归一 → **P2 软队列**（`near`）
  - 多模态值无效 → 回退 OCR（`ocr_default`）
- **v2（受约束多模态优先）**：在 v1 全部逻辑之上，**仅对 `college`/`major` 候选强项字段**，
  当满足全部证据门控条件时，将多模态值标记为 `mm_verified_priority`（仍计入自动放行集合）。
  其余字段与 v1 完全一致，绝不走捷径。

### 2.2 证据与安全约束（运行时硬规则，不依赖 Gold）

1. **绝不读取 Gold 来选择路由或填值**（评测脚本独立注入 Gold，仅用于计分）。
2. **城市不得以省份替代**：冲突判定时 `province` 类值不视为 `city` 的可接受等价。
3. **专业近似但语义不同须保留冲突**：编辑距离接近但词根/语义不同 → 仍走 P1，不自动合并。
4. **无可信证据 → P1 人工复核**：evidence 必须可核验——字段类型正确、人物序号对齐、
   证据字符串真正出现在可信图片/OCR 内容（`source_texts`）中；仅凭字符串包含/相似/模型自述
   一律不认定。
5. **模型异常/越界值**：类型不符或越界 → 回退 OCR，不污染结果。

### 2.3 可调用入口

```python
from app.extraction.field_fusion import fuse_sample, fuse_persons, POLICY_V0, POLICY_V1, POLICY_V2

# 单样本融合（source_texts 为海报 OCR 原文，用于证据核验）
fused = fuse_sample(
    ocr_sample={"persons": [...], "valid": True},
    mm_sample ={"persons": [...], "valid": True},
    policy=POLICY_V2,                 # 或 POLICY_V0 / POLICY_V1
    source_texts=["机械工程学院 计算机科学与技术学院 ..."],
)
for p in fused["persons"]:
    print(p["college"], p["_status"]["college"], p["_source"]["college"])
```

CLI：
```bash
python scripts/run_fusion_eval.py --mode fixtures \
    --out reports/extraction/week4/fusion_eval_fixtures.json
```

---

## 3. 统一评测入口（同源 / 同 Gold / 同分母）

`fusion_eval.py` 对 Fusion-v0/v1/v2 使用**完全相同**的输入样本、Gold 与分母，输出：

- 七字段 `strict` / `normalized` 命中率（cohort/education/major/city/position_or_unit + grade/college）
- 完整**人物正确率**（`pers%`）与**海报正确率**（`post%`）
- **错误自动放行数 + 比例**（`autoErr` / `auto%`）：自动放行类 status 中若与 Gold 不符即计为错误放行，
  这是融合策略严控的核心风险指标
- **P1 / P2 队列**规模（需人工复核 / 软队列）
- 失败率、延迟、成本（真实/cache-replay/stub 调用在 `route_meta` 中明确分类，不混淆）

> 历史 v2 模拟未完整继承 v1 的逻辑偏差已修复：v2 复用 v1 的 `_fuse_field` 主流程，
> 仅在强项字段的 `near` 分支上叠加受约束优先，且 `AUTO_PASS_STATUSES` 由 `evaluation` 单一事实源导出。

---

## 4. 离线评测结果（冻结 fixtures —— 仅代表策略与契约正确）

| policy | strict | norm | autoErr | auto% | P1 | P2 | pers% | post% |
|--------|-------:|-----:|--------:|------:|---:|---:|------:|------:|
| v0 (OCR 基线)     | 35.29 | 35.29 | **11** | **64.71** | 0 | 0 | 10.00 | 12.50 |
| v1 (分歧分档)     | 52.94 | 52.94 | 0 | 0.00 | 10 | 1 | 30.00 | 37.50 |
| v2 (受约束优先)   | 64.71 | 64.71 | 0 | 0.00 | 8 | 1 | 50.00 | 50.00 |

**读图要点（契约层面）：**
- v0 盲目信任 OCR，错误自动放行高达 64.71%——这正是要被融合策略消除的风险。
- v1 把冲突全部送上 P1（autoErr=0），但强项字段的缺失值未被利用，norm 仅 52.94%。
- v2 在强项字段上用可核验的多模态值补全，**norm 提升到 64.71%，但 autoErr 仍为 0**——
  即"多恢复了正确值"而"没有冒险放行任何错误值"。这是 v2 设计的预期收益区间。

> ⚠️ **这些数字是 8 个冻结合成样本上的，不是 71 张真实海报的准确率。**
> 离线回归通过只证明**策略与契约正确、v0/v1 行为不回归**；真实 71 张上的表现须待真实数据再测。

---

## 5. 可复现运行命令

```bash
# 1) 环境（仓库自带 .venv，pytest 已装）
python -m venv .venv && .venv/Scripts/pip install pytest

# 2) 离线测试（12/12 应通过）
.venv/Scripts/python -m pytest tests/extraction/test_field_fusion.py -p no:cacheprovider

# 3) 离线评测（产出 fusion_eval_fixtures.json）
.venv/Scripts/python scripts/run_fusion_eval.py --mode fixtures \
    --out reports/extraction/week4/fusion_eval_fixtures.json

# 4) 待真实数据后（示例，非本轮执行）：
#    4a. GLM-4.5V 71 张真实调用 + 字段归一（复用 glm_chain_check 链路）
#    4b. 注入真实样本跑三策略：
#        python scripts/run_fusion_eval.py --mode real --out reports/extraction/week4/fusion_eval_real.json
#    4c. 对比 Fusion-v2 vs 最佳单模型，重点看 autoErr / auto% 是否上升
```

---

## 6. 分支覆盖与冻结基线验证

- **分支**：`feat/week4-B-fusion-v2`，commit `1ddc401`（父 `a00c3e0` = `master`）。
  **单开 Draft 分支，不与 #24（GLM 链路验收）混合**。
- **冻结基线**：fixtures 为固定合成样本（FIX-00~FIX-07 及 S1~S7 多人物/异常分支），
  覆盖等价、缺失、相似但不同实体、人物错配、证据缺失、冲突、模型异常。
- **回归门禁**：`test_field_fusion.py` 12 项全部锁定期望 status（v0 走 `ocr_default`、
  v1 冲突走 `review_required`、v2 强项可核验走 `mm_verified_priority`、不可核验仍走 `review_required`），
  确保 v0/v1 既有行为不回归、v2 证据门控分支正确。
- **本次结果**：`12 passed`，`fusion_eval_fixtures.json` 已生成。

---

## 7. 待真实数据后再下结论（明确不在本轮做）

- [ ] GLM-4.5V（或负责人登记的替代型号）完成 71 张真实调用、字段归一、统一评测。
- [ ] 跑三模型（PaddleOCR/百度/GLM）+ Fusion-v0/v1/v2 **同源**对照。
- [ ] 对比融合是否优于最佳单模型；**重点监控错误自动放行率是否增加**。
- [ ] 71 张已参与 OCR 规则调优，结果只作阶段验证，**不写作完全独立的最终泛化成绩**；
  强项路由**不针对 Gold 逐样本调优**。
- [ ] 不沿用历史 20 张 96.36% 模拟值冒充本轮实验结果。

## 8. 范围边界（按用户要求）

- ✅ 不重做 Gold-71 人工标注（已交付，复用）。
- ✅ 不为真实 71 张实验伪造数据；GLM 账户/密钥/费用授权由 B 本人处理。
- ✅ 工程部分可由开发 Agent 直接推进，已在本分支完成。
