# MUC Selection Search

项目说明：多模态信息抽取与选调研项目

## 项目结构
```
muc-selection-search/
├── app/                          # 应用核心代码
│   └── extraction/               # 抽取模块
│       ├── week4_rules.py        # Week4 规则定义
│       ├── week4_metrics.py      # 指标计算
│       ├── glm_chain_check.py     # GLM 链路检查工具
│       └── ...
├── data/                         # 数据目录
│   ├── source_materials/         # 原始素材
│   │   └── posters/             # 海报图片
│   └── gold/                    # Gold 标注数据
├── reports/                      # 报告输出
│   └── extraction/               # 抽取相关报告
│       └── week4/                # Week4 阶段报告
├── progress/                     # 进度记录
│   └── week4/                    # Week4 进度
└── evidence/                     # 证据文件
    └── week4/                    # Week4 证据
```

## 主要功能
- PaddleOCR 本地 OCR 处理
- 百度在线 OCR 调用
- GLM 多模态模型集成
- Gold 标准数据对照评测
- 三路线性能对比分析

## 运行命令
```bash
# GLM 全量检查
python -m app.extraction.glm_chain_check --n 71

# 指标计算
python -m app.extraction.week4_metrics --raw reports/extraction/week4/glm_chain/glm_chain_check.json --out metrics_glm_chain_check.json

# 三路线对比
python -m app.extraction.week4_metrics --compare
```