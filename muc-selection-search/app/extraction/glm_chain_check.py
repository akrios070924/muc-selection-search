#!/usr/bin/env python3
"""
GLM 多模态链路检查工具
用于验证 GLM 模型在海报抽取任务中的表现
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
import sys

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.extraction.multimodal_adapter import MultimodalAdapter
from app.extraction.multimodal_adapter import ExtractionResult
import requests


class GLMChainChecker:
    """GLM 链路检查器"""
    
    def __init__(self, model: str = "glm-4v-flash"):
        self.model = model
        self.adapter = MultimodalAdapter(model=model)
        
    def _make_capturing_client(self):
        """创建带 token 捕获的客户端"""
        # 使用 requests 库创建客户端
        session = requests.Session()
        
        # 创建适配器，注入 token 捕获逻辑
        capturing_client = self.adapter._make_capturing_client()
        return capturing_client
        
    def check_sample(self, sample_id: str, image_path: str, gold_persons: List[Dict] = None) -> Dict[str, Any]:
        """检查单个样本"""
        start_time = time.time()
        
        try:
            # 使用适配器进行抽取
            result: ExtractionResult = self.adapter.extract_from_image(image_path)
            
            elapsed_time = time.time() - start_time
            
            # 构造返回结果
            check_result = {
                "sample_id": sample_id,
                "persons": result.persons,
                "gold_persons": gold_persons or [],
                "valid": result.valid,
                "elapsed_s": elapsed_time,
                "call_kind": "real",
                "model": self.model,
                "error": None,
                "tokens_captured": result.tokens_captured if hasattr(result, 'tokens_captured') else None,
                "cost": result.cost if hasattr(result, 'cost') else None
            }
            
            return check_result
            
        except Exception as e:
            elapsed_time = time.time() - start_time
            return {
                "sample_id": sample_id,
                "persons": [],
                "gold_persons": gold_persons or [],
                "valid": False,
                "elapsed_s": elapsed_time,
                "call_kind": "real",
                "model": self.model,
                "error": str(e),
                "tokens_captured": None,
                "cost": None
            }
    
    def check_batch(self, sample_ids: List[str], image_dir: str, gold_data: Dict = None, max_retries: int = 3) -> List[Dict[str, Any]]:
        """批量检查样本"""
        results = []
        
        for sample_id in sample_ids:
            image_path = os.path.join(image_dir, f"target_{sample_id}.jpg")
            if not os.path.exists(image_path):
                # 尝试其他扩展名
                for ext in ['.png', '.jpeg', '.JPG']:
                    alt_path = os.path.join(image_dir, f"target_{sample_id}{ext}")
                    if os.path.exists(alt_path):
                        image_path = alt_path
                        break
            
            gold_persons = None
            if gold_data and sample_id in gold_data:
                gold_persons = gold_data.get(sample_id, [])
            
            # 重试机制
            result = None
            for attempt in range(max_retries):
                try:
                    result = self.check_sample(sample_id, image_path, gold_persons)
                    if result["error"] is None or attempt == max_retries - 1:
                        break
                    time.sleep(2 ** attempt)  # 指数退避
                except Exception as e:
                    if attempt == max_retries - 1:
                        result = {
                            "sample_id": sample_id,
                            "persons": [],
                            "gold_persons": gold_persons or [],
                            "valid": False,
                            "elapsed_s": 0,
                            "call_kind": "real",
                            "model": self.model,
                            "error": f"Retry failed: {str(e)}",
                            "tokens_captured": None,
                            "cost": None
                        }
                    time.sleep(2 ** attempt)
            
            results.append(result)
            
            # 打印进度
            print(f"Processed {len(results)}/{len(sample_ids)}: {sample_id} - {'✓' if result['error'] is None else '✗'}")
        
        return results
    
    def save_results(self, results: List[Dict[str, Any]], output_path: str):
        """保存结果"""
        output_data = {
            "route": "glm_chain",
            "model": self.model,
            "records": results,
            "total_samples": len(results),
            "valid_samples": sum(1 for r in results if r["valid"]),
            "total_elapsed_s": sum(r["elapsed_s"] for r in results),
            "total_tokens": sum(r.get("tokens_captured", 0) for r in results if r.get("tokens_captured")),
            "total_cost": sum(r.get("cost", 0) for r in results if r.get("cost"))
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"Results saved to: {output_path}")
        print(f"Summary: {output_data['valid_samples']}/{output_data['total_samples']} valid, "
              f"Elapsed: {output_data['total_elapsed_s']:.2f}s, "
              f"Tokens: {output_data['total_tokens']}, Cost: ¥{output_data['total_cost']:.4f}")


def load_manifest(manifest_path: str) -> Dict[str, Any]:
    """加载 manifest 文件"""
    with open(manifest_path, 'r', encoding='utf-8') as f:
        data = []
        for line in f:
            if line.strip():
                parts = line.strip().split(',')
                if len(parts) >= 3:
                    data.append({
                        'file_path': parts[0],
                        'sha256': parts[1],
                        'dataset_split': parts[2],
                        'seen_in_old20': parts[3] if len(parts) > 3 else 'false'
                    })
        return {'samples': data}


def load_gold_data(gold_path: str) -> Dict[str, List[Dict]]:
    """加载 Gold 数据"""
    try:
        with open(gold_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {item['sample_id']: item['persons'] for item in data}
    except FileNotFoundError:
        return {}


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='GLM 多模态链路检查')
    parser.add_argument('--n', type=int, default=71, help='检查样本数量')
    parser.add_argument('--manifest', type=str, default='data/source_materials/manifest.csv', help='manifest 文件路径')
    parser.add_argument('--gold', type=str, default='data/gold/gold_71.json', help='Gold 数据路径')
    parser.add_argument('--output', type=str, default='reports/extraction/week4/glm_chain/glm_chain_check.json', help='输出路径')
    parser.add_argument('--model', type=str, default='glm-4v-flash', help='GLM 模型')
    
    args = parser.parse_args()
    
    # 创建检查器
    checker = GLMChainChecker(model=args.model)
    
    # 加载数据
    print("Loading manifest...")
    manifest = load_manifest(args.manifest)
    
    print("Loading gold data...")
    gold_data = load_gold_data(args.gold)
    
    # 筛选样本
    new_holdout_samples = [s for s in manifest['samples'] if s['dataset_split'] == 'new_holdout']
    sample_ids = [s['file_path'].split('/')[-1].replace('target_', '').replace('.jpg', '').replace('.png', '') 
                  for s in new_holdout_samples[:args.n]]
    
    print(f"Checking {len(sample_ids)} samples: {sample_ids}")
    
    # 执行检查
    results = checker.check_batch(sample_ids, 'data/source_materials/posters', gold_data)
    
    # 保存结果
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    checker.save_results(results, args.output)


if __name__ == "__main__":
    main()