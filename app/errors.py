"""结构化请求校验错误。"""
from __future__ import annotations

import math
from typing import Any


def _sanitize_non_finite(value: Any) -> Any:
    """把错误结构中无法 JSON 序列化的非有限浮点（NaN/Infinity）替换为字符串标记。

    校验器对 NaN/Infinity 输入抛出 ValueError 时，pydantic 会把原始输入放进
    错误的 input 字段回显；json.dumps 默认无法序列化这些值，会把本应返回的
    422 变成 500。这里递归替换为 "NaN"/"Infinity"/"-Infinity"，其余值原样返回。
    """
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return value
    if isinstance(value, dict):
        return {key: _sanitize_non_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_non_finite(item) for item in value]
    return value


class RequestValidationErrors(Exception):
    """跨字段校验收集到的一组错误。

    FastAPI 通过 app 中注册的异常处理器把它渲染成 HTTP 422。
    """

    def __init__(self, errors: list[dict]):
        self.errors = errors
        super().__init__(str(errors))
