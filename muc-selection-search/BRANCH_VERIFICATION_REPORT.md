# Fusion-v2 分支验证报告

## 1. 分支状态确认 ✅

- **分支名**: `feat/week4-B-fusion-v2`
- **HEAD SHA**: `ac10b93b8d7eb8c9ea8ca56dbd455eac604dfaef`
- **基线 SHA**: `a00c3e0d9b406f5c894fba56ac17635478f6583a` (master)
- **merge-base**: `a00c3e0d9b406f5c894fba56ac17635478f6583a`
- **分支基于**: master (非 PR #23 或 PR #24，独立开发分支)

## 2. 提交历史

```
ac10b93 docs(extraction): Fusion-v2 分支验证报告与打包文件
76d5b1b docs(extraction): Fusion-v2 工程报告与进度切片13 (Issue #17 阶段3-4)
1ddc401 feat(extraction): Fusion-v2 工程实现与统一评测基础设施 (Issue #17 阶段3-4)
a00c3e0 docs(memory): 更新GLM全量对照任务完成记录
4eebd7c feat(extraction): 完成GLM-4.5-Flash全量对照与三路线报告
```

## 3. 变更文件清单

### 核心实现文件
- `app/extraction/field_fusion.py` - Fusion-v0/v1/v2 三策略实现
- `app/extraction/fields.py` - 支撑模块（MAJOR_TERMS/归一等）
- `app/extraction/disagreement_tiers.py` - 分歧分档逻辑
- `app/extraction/evaluation.py` - 评估指标和自动放行状态

### 评测基础设施
- `app/extraction/fusion_eval.py` - 统一评测库
- `scripts/run_fusion_eval.py` - 评测 CLI 脚本
- `reports/extraction/week4/fusion_eval_fixtures.json` - 冻结基线评测结果

### 测试套件
- `tests/extraction/test_field_fusion.py` - 12 个离线测试
- `tests/extraction/fixtures/fusion_fixtures.py` - 冻结合成样本
- `tests/__init__.py`, `tests/extraction/__init__.py`, `tests/extraction/fixtures/__init__.py` - 测试包结构

### 权威交付报告
- `reports/extraction/week4/FUSION_V2_ENGINEERING_REPORT.md` - 完整工程报告

### 遗传文件（继承自父提交）
- `app/extraction/glm_chain_check.py` - GLM 链路检查工具
- `app/extraction/multimodal_adapter.py` - 多模态适配器
- `app/extraction/week4_metrics.py` - 指标计算工具
- `reports/extraction/week4/glm_chain/glm_chain_check.json` - GLM 全量记录
- `reports/extraction/week4/route_comparison_v3.json` - 三路线对照
- `README.md`, `.gitignore` 等

## 4. Git 状态检查

- ✅ **工作区状态**: 仅 `.workbuddy/memory/2026-10-24.md` 和 `FUSION_V2_ENGINEERING_REPORT.md` 未提交（前者为本地记忆，后者已提交）
- ✅ **Git 对象完整性**: `fsck --full` 通过
- ✅ **空白字符检查**: `diff --check` 通过
- ✅ **HEAD 验证**: `rev-parse --verify HEAD` 成功

## 5. 全量测试结果 ✅

```
================================ test session starts =================================
collected 12 items
tests/extraction/test_field_fusion.py ............  [100%]
================================ 12 passed in 0.37s =================================
```

## 6. 冻结基线评测结果

```
================================================================
policy   strict     norm  autoErr   auto%   P1   P2   pers%   post%
v0       35.29    35.29       11  64.71    0    0   10.00   12.50
v1       52.94    52.94        0   0.00   10    1   30.00   37.50
v2       64.71    64.71        0   0.00    8    1   50.00   50.00
```

## 7. .gitignore 检查

- `PROGRESS.md` 被 `.gitignore` 忽略（B 白名单边界，仅本地辅助记录）
- 所有工程交付物均已提交到 Git
- 无文件遗漏

## 8. Git Bundle 文件详情

- **文件名**: `feat-week4-B-fusion-v2.bundle`
- **HEAD SHA**: `ac10b93b8d7eb8c9ea8ca56dbd455eac604dfaef`
- **大小**: 62.3 MB
- **验证结果**: ✅ 完整历史，包含所有提交
- **包含内容**: 
  - Fusion-v2 完整实现
  - 测试套件和评测脚本
  - 权威交付报告
  - 所有依赖文件

## 9. 使用说明

### 恢复分支
```bash
# 在具备 GitHub 权限的本地仓库
git clone <your-repo-url>
cd <repo-dir>
git bundle pull ../feat-week4-B-fusion-v2.bundle
git checkout feat/week4-B-fusion-v2
```

### 推送到远程
```bash
git push origin feat/week4-B-fusion-v2
gh pr create --title "Fusion-v2 工程实现与统一评测基础设施 (Issue #17 阶段3-4)" \
             --body "$(cat reports/extraction/week4/FUSION_V2_ENGINEERING_REPORT.md)"
```

## 10. 已知限制

- ⚠️ **真实准确率待评测**: 离线测试结果仅代表策略与契约正确，不能作为真实模型效果
- ⚠️ **需要 GLM API Key**: 真实数据对照需要 GLM-4.5V（或负责人登记的替代型号）71 张真实调用
- ⚠️ **不包含 Gold-71 重做**: 复用已有人工标注，不新增人工标注
- ⚠️ **沙箱环境限制**: 当前无 remote，需在具备权限的环境推送

## 11. 下一步

1. 在具备 GitHub 权限的环境恢复分支
2. 创建 Draft PR
3. 待 GLM API Key 就绪后，执行真实数据对照
4. 更新报告中的真实准确率数据

---
*生成时间: 2026-10-24*
*分支: feat/week4-B-fusion-v2*