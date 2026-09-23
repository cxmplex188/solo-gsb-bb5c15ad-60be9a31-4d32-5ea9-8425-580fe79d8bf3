"""跨领域共享的基础模型与工具：数值常量、有限数校验、通用余额视图。"""
from __future__ import annotations

import math
from typing import Annotated

from pydantic import BaseModel, Field

# Floating point tolerance for balance comparisons.
EPS = 1e-9


def _is_finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _coerce_finite_number(value, field_name: str, label: str | None = None):
    """before 校验：拒绝 NaN/Infinity 及字符串转换后的非有限值。

    数值字符串（如 "10"、"1e3"）会被显式转成 float 交由后续类型校验，
    与 pydantic lax 模式对 float 字段的字符串容忍保持一致；"NaN" /
    "Infinity" 等可被 float() 解析但结果非有限的输入在此被拒绝；
    无法解析的字符串原样返回，交由 pydantic 产生标准的类型错误。
    label 给出面向用户的字段描述，缺省使用 field_name。
    """
    if isinstance(value, str):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return value
    if not _is_finite_number(value):
        raise ValueError(f"{label or field_name} 必须是有限数值")
    return value


class BucketBalance(BaseModel):
    """链上单个桶在某次扣减判定时的余额视图。"""

    before: Annotated[float, Field(description="判定时刻（补充之后、扣减之前）的余额")]
    after: Annotated[float, Field(description="扣减之后的余额；被拒绝时与 before 相同")]


