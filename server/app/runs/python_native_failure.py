"""Python-native 失败分类。

本模块把协议错误码或 response 中已有的 `failure_classification` 规范成报告可用
的结构化原因，供预期失败断言和最终 report 使用。
"""

from __future__ import annotations

from typing import Any


class FailureClassifier:
    """把运行错误映射为稳定的 failure classification。"""

    def classify(self, error: dict[str, Any] | None) -> dict[str, Any] | None:
        """优先使用上游分类；缺失时按 Beacon 约定错误码补齐。"""
        if error is None:
            return None
        classification = error.get("failure_classification")
        if isinstance(classification, dict):
            return classification
        code = error.get("code")
        if code == 401:
            return {
                "category": "sdk_error",
                "reason": "invalid_token",
            }
        if code == 402:
            return {
                "category": "environment",
                "reason": "permission_denied",
            }
        if code == 404:
            return {
                "category": "runtime_dependency",
                "source": "runtime",
                "reason": "device_unavailable",
            }
        if code == 488:
            return {
                "category": "unsupported",
                "source": "agent",
                "reason": "unsupported_target",
            }
        return None


def failure_classification(error: dict[str, Any] | None) -> dict[str, Any] | None:
    """函数式入口，避免调用方关心 classifier 实例生命周期。"""
    return FailureClassifier().classify(error)
