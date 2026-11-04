#!/usr/bin/env python3
"""
多模态适配器
用于统一不同多模态模型的接口
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
import dataclasses
from dataclasses import dataclass


@dataclass
class ExtractionResult:
    """抽取结果"""
    persons: List[Dict[str, Any]]
    valid: bool
    tokens_captured: Optional[int] = None
    cost: Optional[float] = None
    elapsed_s: Optional[float] = None
    error: Optional[str] = None


class MultimodalAdapter:
    """多模态适配器基类"""
    
    def __init__(self, model: str = "glm-4v-flash"):
        self.model = model
        self.client = None
        
    def _make_capturing_client(self):
        """创建带 token 捕获的客户端"""
        # 这里应该根据具体模型实现
        # 对于 GLM，我们需要创建一个能够捕获 token 使用情况的客户端
        try:
            import requests
            session = requests.Session()
            # 这里可以添加 token 捕获逻辑
            return session
        except ImportError:
            raise ImportError("requests library is required for GLM adapter")
    
    def extract_from_image(self, image_path: str) -> ExtractionResult:
        """从图片中抽取信息"""
        raise NotImplementedError("Subclasses must implement this method")


class GLMAdapter(MultimodalAdapter):
    """GLM 多模态适配器"""
    
    def __init__(self, model: str = "glm-4v-flash", api_key: Optional[str] = None):
        super().__init__(model)
        self.api_key = api_key or os.getenv("GLM_API_KEY")
        self.client = self._make_capturing_client()
        
    def _make_capturing_client(self):
        """创建带 token 捕获的 GLM 客户端"""
        try:
            import requests
            from openai import OpenAI
            
            # 创建 OpenAI 兼容的客户端
            client = OpenAI(
                api_key=self.api_key,
                base_url="https://open.bigmodel.cn/api/paas/v4"
            )
            
            # 包装原始方法以捕获 token
            original_create = client.chat.completions.create
            
            def capturing_create(*args, **kwargs):
                start_time = time.time()
                try:
                    response = original_create(*args, **kwargs)
                    elapsed_time = time.time() - start_time
                    
                    # 计算 token 使用量
                    total_tokens = 0
                    if response.usage:
                        total_tokens = response.usage.total_tokens
                    
                    return response, total_tokens, elapsed_time
                except Exception as e:
                    elapsed_time = time.time() - start_time
                    raise e
            
            client.chat.completions.create = capturing_create
            return client
            
        except ImportError:
            raise ImportError("openai library is required for GLM adapter")
    
    def extract_from_image(self, image_path: str) -> ExtractionResult:
        """从图片中抽取信息"""
        if not os.path.exists(image_path):
            return ExtractionResult(
                persons=[],
                valid=False,
                error=f"Image not found: {image_path}"
            )
        
        try:
            # 读取图片文件
            with open(image_path, "rb") as image_file:
                image_data = image_file.read()
            
            # 构造提示词
            prompt = """
请从这张海报图片中抽取人员信息，提取以下字段：
1. 姓名 (name)
2. 职位/职务 (position_or_unit)  
3. 单位/机构 (organization)
4. 学历 (education)
5. 专业 (major)
6. 年级 (grade)
7. 学院 (college)
8. 届别 (cohort)
9. 城市 (city)

请严格按照以下 JSON 格式返回：
{
  "persons": [
    {
      "name": "姓名",
      "position_or_unit": "职位/职务",
      "organization": "单位/机构", 
      "education": "学历",
      "major": "专业",
      "grade": "年级",
      "college": "学院",
      "cohort": "届别",
      "city": "城市"
    }
  ]
}

如果图片中没有人员信息，请返回空数组。
"""
            
            # 调用 GLM API
            response, total_tokens, elapsed_time = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data.hex()}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.1
            )
            
            # 解析响应
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                try:
                    result_data = json.loads(content)
                    persons = result_data.get("persons", [])
                    
                    return ExtractionResult(
                        persons=persons,
                        valid=True,
                        tokens_captured=total_tokens,
                        cost=self._calculate_cost(total_tokens),
                        elapsed_s=elapsed_time
                    )
                except json.JSONDecodeError:
                    return ExtractionResult(
                        persons=[],
                        valid=False,
                        error=f"Failed to parse JSON response: {content}",
                        tokens_captured=total_tokens,
                        cost=self._calculate_cost(total_tokens),
                        elapsed_s=elapsed_time
                    )
            else:
                return ExtractionResult(
                    persons=[],
                    valid=False,
                    error="No response choices returned",
                    tokens_captured=total_tokens,
                    cost=self._calculate_cost(total_tokens),
                    elapsed_s=elapsed_time
                )
                
        except Exception as e:
            return ExtractionResult(
                persons=[],
                valid=False,
                error=str(e)
            )
    
    def _calculate_cost(self, tokens: int) -> float:
        """计算成本（假设 GLM 定价）"""
        # 这里应该使用实际的 GLM 定价
        # 假设每 1K tokens 成本为 0.01 元
        return (tokens / 1000) * 0.01


class BaiduAdapter(MultimodalAdapter):
    """百度多模态适配器"""
    
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        super().__init__("baidu")
        self.api_key = api_key or os.getenv("BAIDU_API_KEY")
        self.secret_key = secret_key or os.getenv("BAIDU_SECRET_KEY")
        self.client = self._make_capturing_client()
    
    def _make_capturing_client(self):
        """创建百度客户端"""
        try:
            import requests
            session = requests.Session()
            return session
        except ImportError:
            raise ImportError("requests library is required for Baidu adapter")
    
    def extract_from_image(self, image_path: str) -> ExtractionResult:
        """从图片中抽取信息"""
        # 实现百度多模态 API 调用
        # 这里需要根据实际的百度 API 实现
        return ExtractionResult(
            persons=[],
            valid=False,
            error="Baidu adapter not implemented yet"
        )


def create_adapter(model: str = "glm-4v-flash", **kwargs) -> MultimodalAdapter:
    """创建适配器工厂函数"""
    if model.startswith("glm"):
        return GLMAdapter(model=model, **kwargs)
    elif model.startswith("baidu"):
        return BaiduAdapter(**kwargs)
    else:
        raise ValueError(f"Unsupported model: {model}")


if __name__ == "__main__":
    # 测试适配器
    adapter = create_adapter("glm-4v-flash")
    result = adapter.extract_from_image("test_image.jpg")
    print(f"Extracted {len(result.persons)} persons")
    print(f"Valid: {result.valid}")
    if result.error:
        print(f"Error: {result.error}")