#!/usr/bin/env python3
"""
Week4 指标计算工具
支持 PaddleOCR、百度、GLM 三路线的指标计算和对比
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import dataclasses
from dataclasses import dataclass
import argparse


@dataclass
class RouteRaw:
    """原始路线数据"""
    route_name: str
    sample_results: List[Dict[str, Any]]
    rules: str


@dataclass
class MetricResult:
    """指标结果"""
    route_name: str
    macro_avg: float
    normalized_avg: float
    strict_avg: float
    whole_match_strict: int
    whole_match_norm: int
    whole_match_total: int
    person_match: int
    person_match_total: int
    hallucinations: int
    field_metrics: Dict[str, Dict[str, float]]
    elapsed_s: float


def load_route_raw(path: Path) -> RouteRaw:
    """加载路线原始数据"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    
    # 处理 GLM 数据格式（records 键）
    if "records" in data:
        sample_results = []
        for record in data["records"]:
            sample_results.append({
                "sample_id": record["sample_id"],
                "persons": record["persons"],
                "gold_persons": record["gold_persons"],
                "valid": record["valid"],
                "elapsed_s": record.get("elapsed_s", 0)
            })
        return RouteRaw(
            route_name=data.get("route", Path(path).stem),
            sample_results=sample_results,
            rules=data.get("rules", "")
        )
    else:
        # 处理标准格式（sample_results 键）
        return RouteRaw(
            route_name=data.get("route", Path(path).stem),
            sample_results=data["sample_results"],
            rules=data.get("rules", "")
        )


def calculate_metrics(route_raw: RouteRaw) -> MetricResult:
    """计算指标"""
    sample_results = route_raw.sample_results
    
    # 初始化统计
    total_samples = len(sample_results)
    valid_samples = sum(1 for r in sample_results if r["valid"])
    
    if total_samples == 0:
        return MetricResult(
            route_name=route_raw.route_name,
            macro_avg=0.0,
            normalized_avg=0.0,
            strict_avg=0.0,
            whole_match_strict=0,
            whole_match_norm=0,
            whole_match_total=total_samples,
            person_match=0,
            person_match_total=0,
            hallucinations=0,
            field_metrics={},
            elapsed_s=0.0
        )
    
    # 计算字段指标
    field_metrics = {}
    field_names = ["cohort", "education", "major", "city", "position_or_unit", "grade", "college"]
    
    for field in field_names:
        field_metrics[field] = calculate_field_metrics(sample_results, field)
    
    # 计算整体指标
    macro_avg = sum(field_metrics[field]["macro_avg"] for field in field_names) / len(field_names)
    normalized_avg = sum(field_metrics[field]["normalized_avg"] for field in field_names) / len(field_names)
    strict_avg = sum(field_metrics[field]["strict_avg"] for field in field_names) / len(field_names)
    
    # 计算整张匹配
    whole_match_strict = 0
    whole_match_norm = 0
    
    for result in sample_results:
        if result["valid"] and len(result["persons"]) > 0:
            # 检查整张是否匹配
            persons_match = len(result["persons"]) == len(result["gold_persons"])
            
            if persons_match:
                # 检查每个字段是否匹配
                all_fields_match_strict = True
                all_fields_match_norm = True
                
                for ai_person, gold_person in zip(result["persons"], result["gold_persons"]):
                    for field in field_names:
                        ai_value = ai_person.get(field, "")
                        gold_value = gold_person.get(field, "")
                        
                        # 严格匹配
                        if ai_value != gold_value:
                            all_fields_match_strict = False
                        
                        # 归一化匹配（去除空格和标点）
                        if normalize_field_value(ai_value) != normalize_field_value(gold_value):
                            all_fields_match_norm = False
                
                if all_fields_match_strict:
                    whole_match_strict += 1
                if all_fields_match_norm:
                    whole_match_norm += 1
    
    # 计算人员匹配
    person_match = 0
    person_match_total = 0
    
    for result in sample_results:
        if result["valid"] and len(result["persons"]) > 0 and len(result["gold_persons"]) > 0:
            person_match_total += len(result["gold_persons"])
            
            for gold_person in result["gold_persons"]:
                matched = False
                for ai_person in result["persons"]:
                    # 检查姓名是否匹配
                    if gold_person.get("name", "") == ai_person.get("name", ""):
                        matched = True
                        break
                
                if matched:
                    person_match += 1
    
    # 计算幻觉
    hallucinations = 0
    for result in sample_results:
        if result["valid"]:
            # 统计 AI 有但 Gold 没有的信息
            for ai_person in result["persons"]:
                for gold_person in result["gold_persons"]:
                    # 检查是否是同一个人的不同表述
                    if ai_person.get("name", "") == gold_person.get("name", ""):
                        break
                else:
                    # 没有找到匹配的 Gold 人员，认为是幻觉
                    hallucinations += 1
    
    # 计算总耗时
    total_elapsed = sum(r.get("elapsed_s", 0) for r in sample_results)
    
    return MetricResult(
        route_name=route_raw.route_name,
        macro_avg=macro_avg,
        normalized_avg=normalized_avg,
        strict_avg=strict_avg,
        whole_match_strict=whole_match_strict,
        whole_match_norm=whole_match_norm,
        whole_match_total=total_samples,
        person_match=person_match,
        person_match_total=person_match_total,
        hallucinations=hallucinations,
        field_metrics=field_metrics,
        elapsed_s=total_elapsed
    )


def calculate_field_metrics(sample_results: List[Dict[str, Any]], field: str) -> Dict[str, float]:
    """计算字段级别的指标"""
    total_samples = len(sample_results)
    if total_samples == 0:
        return {
            "macro_avg": 0.0,
            "normalized_avg": 0.0,
            "strict_avg": 0.0,
            "total": 0,
            "correct": 0
        }
    
    correct_macro = 0
    correct_norm = 0
    correct_strict = 0
    total_field = 0
    
    for result in sample_results:
        if result["valid"] and len(result["persons"]) > 0 and len(result["gold_persons"]) > 0:
            for ai_person, gold_person in zip(result["persons"], result["gold_persons"]):
                ai_value = ai_person.get(field, "")
                gold_value = gold_person.get(field, "")
                
                total_field += 1
                
                # 严格匹配
                if ai_value == gold_value:
                    correct_strict += 1
                
                # 归一化匹配
                if normalize_field_value(ai_value) == normalize_field_value(gold_value):
                    correct_norm += 1
                
                # 宏观匹配（非空即正确）
                if ai_value != "" or gold_value != "":
                    if ai_value == gold_value:
                        correct_macro += 1
    
    if total_field == 0:
        return {
            "macro_avg": 0.0,
            "normalized_avg": 0.0,
            "strict_avg": 0.0,
            "total": 0,
            "correct": 0
        }
    
    return {
        "macro_avg": correct_macro / total_field,
        "normalized_avg": correct_norm / total_field,
        "strict_avg": correct_strict / total_field,
        "total": total_field,
        "correct": correct_strict
    }


def normalize_field_value(value: str) -> str:
    """归一化字段值"""
    if not value:
        return ""
    return value.strip().lower().replace(" ", "").replace(",", "").replace(".", "")


def format_metrics(metrics: MetricResult) -> str:
    """格式化指标输出"""
    output = []
    output.append(f"=== {metrics.route_name} ===")
    output.append(f"宏平均: {metrics.macro_avg:.2%}")
    output.append(f"归一化平均: {metrics.normalized_avg:.2%}")
    output.append(f"严格平均: {metrics.strict_avg:.2%}")
    output.append(f"整张全对 (strict): {metrics.whole_match_strict}/{metrics.whole_match_total} ({metrics.whole_match_strict/metrics.whole_match_total:.2%})")
    output.append(f"整张全对 (norm): {metrics.whole_match_norm}/{metrics.whole_match_total} ({metrics.whole_match_norm/metrics.whole_match_total:.2%})")
    output.append(f"人员匹配: {metrics.person_match}/{metrics.person_match_total} ({metrics.person_match/metrics.person_match_total:.2%})")
    output.append(f"幻觉数量: {metrics.hallucinations}")
    output.append(f"总耗时: {metrics.elapsed_s:.2f}s")
    output.append("")
    
    # 字段指标
    output.append("字段指标:")
    for field, field_metric in metrics.field_metrics.items():
        output.append(f"  {field}: {field_metric['strict_avg']:.2%} ({field_metric['correct']}/{field_metric['total']})")
    
    return "\n".join(output)


def compare_routes(metrics_list: List[MetricResult]) -> str:
    """对比多条路线的指标"""
    output = []
    output.append("=== 三路线对比 ===")
    output.append("")
    
    # 表头
    output.append(f"{'路线':<15} {'宏平均':<10} {'归一化':<10} {'严格':<10} {'整张全对':<15} {'人员匹配':<12} {'幻觉':<8}")
    output.append("-" * 80)
    
    # 数据行
    for metrics in metrics_list:
        whole_match_strict_pct = f"{metrics.whole_match_strict}/{metrics.whole_match_total}"
        person_match_pct = f"{metrics.person_match}/{metrics.person_match_total}"
        
        output.append(f"{metrics.route_name:<15} "
                     f"{metrics.macro_avg:<10.2%} "
                     f"{metrics.normalized_avg:<10.2%} "
                     f"{metrics.strict_avg:<10.2%} "
                     f"{whole_match_strict_pct:<15} "
                     f"{person_match_pct:<12} "
                     f"{metrics.hallucinations:<8}")
    
    output.append("")
    
    # 字段对比
    output.append("字段对比:")
    field_names = ["cohort", "education", "major", "city", "position_or_unit", "grade", "college"]
    
    for field in field_names:
        output.append(f"  {field}:")
        for metrics in metrics_list:
            field_metric = metrics.field_metrics[field]
            output.append(f"    {metrics.route_name}: {field_metric['strict_avg']:.2%} ({field_metric['correct']}/{field_metric['total']})")
        output.append("")
    
    return "\n".join(output)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Week4 指标计算')
    parser.add_argument('--raw', type=str, help='原始数据文件路径')
    parser.add_argument('--out', type=str, help='输出指标文件路径')
    parser.add_argument('--compare', action='store_true', help='对比模式')
    parser.add_argument('--routes', nargs='+', default=['paddleocr', 'baidu', 'glm'], help='要对比的路线')
    
    args = parser.parse_args()
    
    if args.compare:
        # 对比模式
        metrics_list = []
        
        for route in args.routes:
            # 查找对应的指标文件
            metric_file = f"reports/extraction/week4/metrics_{route}.json"
            if route == 'glm':
                metric_file = "reports/extraction/week4/metrics_glm_chain_check.json"
            
            if os.path.exists(metric_file):
                with open(metric_file, 'r', encoding='utf-8') as f:
                    metrics_data = json.load(f)
                
                metrics = MetricResult(
                    route_name=metrics_data['route_name'],
                    macro_avg=metrics_data['macro_avg'],
                    normalized_avg=metrics_data['normalized_avg'],
                    strict_avg=metrics_data['strict_avg'],
                    whole_match_strict=metrics_data['whole_match_strict'],
                    whole_match_norm=metrics_data['whole_match_norm'],
                    whole_match_total=metrics_data['whole_match_total'],
                    person_match=metrics_data['person_match'],
                    person_match_total=metrics_data['person_match_total'],
                    hallucinations=metrics_data['hallucinations'],
                    field_metrics=metrics_data['field_metrics'],
                    elapsed_s=metrics_data['elapsed_s']
                )
                
                metrics_list.append(metrics)
                print(f"Loaded metrics for {route}")
            else:
                print(f"Metrics file not found: {metric_file}")
        
        # 输出对比结果
        comparison_result = compare_routes(metrics_list)
        print(comparison_result)
        
        # 保存对比结果
        if args.out:
            with open(args.out, 'w', encoding='utf-8') as f:
                f.write(comparison_result)
            print(f"Comparison saved to: {args.out}")
    
    elif args.raw:
        # 单个路线计算模式
        route_raw = load_route_raw(Path(args.raw))
        metrics = calculate_metrics(route_raw)
        
        # 输出结果
        print(format_metrics(metrics))
        
        # 保存结果
        if args.out:
            metrics_data = {
                'route_name': metrics.route_name,
                'macro_avg': metrics.macro_avg,
                'normalized_avg': metrics.normalized_avg,
                'strict_avg': metrics.strict_avg,
                'whole_match_strict': metrics.whole_match_strict,
                'whole_match_norm': metrics.whole_match_norm,
                'whole_match_total': metrics.whole_match_total,
                'person_match': metrics.person_match,
                'person_match_total': metrics.person_match_total,
                'hallucinations': metrics.hallucinations,
                'field_metrics': metrics.field_metrics,
                'elapsed_s': metrics.elapsed_s
            }
            
            os.makedirs(os.path.dirname(args.out), exist_ok=True)
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(metrics_data, f, ensure_ascii=False, indent=2)
            
            print(f"Metrics saved to: {args.out}")
    else:
        print("Please specify either --raw or --compare")


if __name__ == "__main__":
    main()