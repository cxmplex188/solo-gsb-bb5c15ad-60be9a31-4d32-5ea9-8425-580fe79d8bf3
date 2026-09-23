"""令牌桶 capacity/refill_rate 非有限数值（NaN/Infinity）拒绝的回归测试。

所有令牌桶类接口（/simulate、/queue-simulate、/route-simulate、
/debt-simulate，以及复用 BucketSpec/ForecastBucket 的分析与规划入口
/forecast、/plan-initial-balances、/usage-report、/fairness-report、
/debt-diff）都必须在进入模拟前拒绝这些参数，统一返回 HTTP 422
（{"detail": [...]}），不得产生 NaN 余额、500 或部分状态；
capacity<=0、refill_rate<0 的既有规则保持不变；正常有限值（含数字字符串）
保持可用。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import BucketSpec
from app.models.analysis.forecast import ForecastBucket

client = TestClient(app)
JSON_HEADERS = {"content-type": "application/json"}

# 各端点的合法基线载荷（用于正常有限值回归与字段替换）
SIM_PAYLOAD = {
    "buckets": [{"id": "A", "capacity": 10, "refill_rate": 1}],
    "requests": [{"id": "r1", "timestamp": 0, "cost": 4, "chain": ["A"]}],
}
QUEUE_PAYLOAD = {
    "buckets": [{"id": "A", "capacity": 10, "refill_rate": 1}],
    "requests": [
        {"id": "r1", "timestamp": 0, "cost": 4, "chain": ["A"], "deadline": 5}
    ],
}
ROUTE_PAYLOAD = {
    "buckets": [{"id": "A", "capacity": 10, "refill_rate": 0}],
    "requests": [{"id": "r1", "timestamp": 0, "cost": 4, "chains": [["A"]]}],
}
DEBT_PAYLOAD = {
    "buckets": [{"id": "A", "capacity": 10, "refill_rate": 1, "debt_limit": 5}],
    "requests": [{"id": "r1", "timestamp": 0, "cost": 4, "chain": ["A"]}],
}
FORECAST_PAYLOAD = {
    "now": 0,
    "cost": 4,
    "chain": ["A"],
    "buckets": [{"id": "A", "capacity": 10, "refill_rate": 1, "balance": 10}],
}
USAGE_PAYLOAD = {**SIM_PAYLOAD, "window_seconds": 10}
FAIRNESS_PAYLOAD = {
    "buckets": [{"id": "A", "capacity": 10, "refill_rate": 1}],
    "requests": [
        {
            "id": "r1",
            "timestamp": 0,
            "cost": 4,
            "chain": ["A"],
            "principal": "p1",
        }
    ],
    "window_seconds": 10,
}
DEBT_DIFF_PAYLOAD = {
    "baseline": {
        "buckets": [{"id": "A", "capacity": 10, "refill_rate": 1, "debt_limit": 5}],
        "requests": [{"id": "r1", "timestamp": 0, "cost": 4, "chain": ["A"]}],
    },
    "candidate": {
        "buckets": [{"id": "A", "capacity": 8, "refill_rate": 1, "debt_limit": 5}],
        "requests": [{"id": "r1", "timestamp": 0, "cost": 4, "chain": ["A"]}],
    },
}

# (path, 合法载荷, 桶字段在载荷中的路径片段)
ENDPOINTS = [
    ("/simulate", SIM_PAYLOAD, ("buckets", 0)),
    ("/queue-simulate", QUEUE_PAYLOAD, ("buckets", 0)),
    ("/route-simulate", ROUTE_PAYLOAD, ("buckets", 0)),
    ("/debt-simulate", DEBT_PAYLOAD, ("buckets", 0)),
    ("/forecast", FORECAST_PAYLOAD, ("buckets", 0)),
    ("/plan-initial-balances", SIM_PAYLOAD, ("buckets", 0)),
    ("/usage-report", USAGE_PAYLOAD, ("buckets", 0)),
    ("/fairness-report", FAIRNESS_PAYLOAD, ("buckets", 0)),
]

# 直接写进 JSON 文本的非有限令牌（Python json 模块默认接受）
RAW_TOKENS = ["NaN", "Infinity", "-Infinity"]
# 经字符串转数值后仍非有限的输入
STRING_TOKENS = ["NaN", "Infinity", "-Infinity", "nan", "inf", "-inf"]


def _set(payload, path, value):
    obj = json.loads(json.dumps(payload))
    node = obj
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return obj


def _build_raw_text(payload, path, token):
    """构造目标字段为裸 NaN/Infinity 令牌的 JSON 文本。

    Python 的 json 模块允许解析这些 JS 风格令牌（json.loads 默认接受），
    但无法用 json.dumps 产出，因此手工拼接该字段，其余部分正常序列化。
    """

    def emit(node, remaining):
        if not remaining:
            return token
        key = remaining[0]
        rest = remaining[1:]
        if isinstance(key, int):
            items = []
            for index, item in enumerate(node):
                items.append(emit(item, rest) if index == key else json.dumps(item))
            return "[" + ",".join(items) + "]"
        items = []
        for name, value in node.items():
            if name == key:
                items.append(json.dumps(name) + ":" + emit(value, rest))
            else:
                items.append(json.dumps(name) + ":" + json.dumps(value))
        return "{" + ",".join(items) + "}"

    return emit(payload, list(path))


def _assert_422(response, field):
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body, dict)
    detail = body["detail"]
    assert isinstance(detail, list) and detail
    # 至少存在一条指向目标桶字段的错误
    assert any(field in e["loc"] for e in detail), detail
    # 整个响应必须可被标准 JSON 解析（无裸 NaN/Infinity 泄漏到响应体）
    json.loads(response.text)
    sanitized = (
        response.text.replace('"NaN"', "")
        .replace('"Infinity"', "")
        .replace('"-Infinity"', "")
    )
    assert "NaN" not in sanitized
    assert "Infinity" not in sanitized


@pytest.mark.parametrize("path,payload,bucket_path", ENDPOINTS)
@pytest.mark.parametrize("field", ["capacity", "refill_rate"])
@pytest.mark.parametrize("token", RAW_TOKENS)
def test_raw_json_non_finite_tokens_rejected_with_422(
    path, payload, bucket_path, field, token
):
    # capacity 的负无穷与正数无限都无意义；refill_rate 同理
    obj = _set(payload, bucket_path + (field,), token)
    raw = _build_raw_text(obj, bucket_path + (field,), token)
    response = client.post(path, content=raw, headers=JSON_HEADERS)
    _assert_422(response, field)


@pytest.mark.parametrize("path,payload,bucket_path", ENDPOINTS)
@pytest.mark.parametrize("field", ["capacity", "refill_rate"])
@pytest.mark.parametrize("token", STRING_TOKENS)
def test_string_coerced_non_finite_values_rejected_with_422(
    path, payload, bucket_path, field, token
):
    obj = _set(payload, bucket_path + (field,), token)
    response = client.post(path, content=json.dumps(obj), headers=JSON_HEADERS)
    _assert_422(response, field)


@pytest.mark.parametrize("field", ["capacity", "refill_rate"])
def test_bucket_spec_model_rejects_non_finite_numbers(field):
    base = {"id": "A", "capacity": 10, "refill_rate": 1}
    for value in (float("nan"), float("inf"), float("-inf")):
        data = dict(base)
        data[field] = value
        with pytest.raises(ValueError):
            BucketSpec.model_validate(data)

    # 字符串形式同样在模型层被拒绝
    for token in ("NaN", "Infinity", "-Infinity", "inf"):
        data = dict(base)
        data[field] = token
        with pytest.raises(ValueError):
            BucketSpec.model_validate(data)

    # 有限值与数字字符串保持可用
    good = dict(base)
    good[field] = 0 if field == "refill_rate" else 5
    assert BucketSpec.model_validate(good)
    good[field] = "0" if field == "refill_rate" else "5"
    assert BucketSpec.model_validate(good)


def test_forecast_bucket_model_rejects_non_finite_numbers():
    base = {"id": "A", "capacity": 10, "refill_rate": 1, "balance": 10}
    for field, value in [
        ("capacity", float("nan")),
        ("capacity", float("inf")),
        ("refill_rate", float("nan")),
        ("refill_rate", float("inf")),
        ("refill_rate", float("-inf")),
    ]:
        data = dict(base)
        data[field] = value
        with pytest.raises(ValueError):
            ForecastBucket.model_validate(data)


@pytest.mark.parametrize("path,payload,_bucket_path", ENDPOINTS)
def test_finite_values_still_accepted(path, payload, _bucket_path):
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    json.loads(response.text)


@pytest.mark.parametrize("path,payload,bucket_path", ENDPOINTS)
@pytest.mark.parametrize("numeric_string", ["10", "1.5", "1e3", "0.0"])
def test_numeric_string_fields_still_coerced(path, payload, bucket_path, numeric_string):
    # refill_rate=0 合法、capacity 必须为正：仅在正值样本上替换
    field = "refill_rate" if numeric_string == "0.0" else "capacity"
    obj = _set(payload, bucket_path + (field,), numeric_string)
    if field == "capacity":
        # /forecast 的 balance 不能超过 capacity
        if path == "/forecast":
            obj["buckets"][0]["balance"] = 0
    response = client.post(path, json=obj)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path,payload,bucket_path", ENDPOINTS)
def test_existing_sign_rules_preserved(path, payload, bucket_path):
    # capacity <= 0 仍被拒绝
    obj = _set(payload, bucket_path + ("capacity",), 0)
    response = client.post(path, json=obj)
    assert response.status_code == 422
    assert any(
        e["loc"][-1] == "capacity" and "正数" in e["msg"]
        for e in response.json()["detail"]
    )
    # refill_rate < 0 仍被拒绝
    obj = _set(payload, bucket_path + ("refill_rate",), -0.5)
    if path == "/forecast":
        obj["buckets"][0]["balance"] = 0
    response = client.post(path, json=obj)
    assert response.status_code == 422
    assert any(
        e["loc"][-1] == "refill_rate" and "非负" in e["msg"]
        for e in response.json()["detail"]
    )


def test_debt_diff_nested_non_finite_rejected_with_loc():
    # candidate 内的非有限桶参数必须在回放前被拒绝，且 loc 指向 candidate
    obj = json.loads(json.dumps(DEBT_DIFF_PAYLOAD))
    obj["candidate"]["buckets"][0]["capacity"] = "Infinity"
    response = client.post("/debt-diff", json=obj)
    assert response.status_code == 422
    locs = [tuple(e["loc"]) for e in response.json()["detail"]]
    assert any(loc[:3] == ("body", "candidate", "buckets") for loc in locs), locs


def test_non_numeric_string_is_standard_type_error():
    obj = json.loads(json.dumps(SIM_PAYLOAD))
    obj["buckets"][0]["capacity"] = "not-a-number"
    response = client.post("/simulate", json=obj)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(e["loc"][-1] == "capacity" for e in detail)
    json.loads(response.text)
