"""Common utilities shared across Beacon runtime modules.

This package provides centralized configuration management and shared utilities
used by device_runtime, evidence_runtime, dispatch_runtime, and reporting.

Key Components:
    CONFIG: Global ServerConfig instance loaded from environment variables.
    ServerConfig: Dataclass defining all server runtime configuration parameters.

Usage:
    >>> from app.common import CONFIG
    >>> registry = DeviceRegistry(max_devices=CONFIG.max_devices)
"""
from .config import CONFIG, ServerConfig

__all__ = ['CONFIG', 'ServerConfig']
