"""Centralized configuration management for Beacon server.

All runtime configuration is managed through ServerConfig dataclass.
Configuration can be loaded from environment variables with sensible defaults.

Usage:
    >>> from app.common.config import CONFIG
    >>> print(CONFIG.max_devices)
    100
"""
from dataclasses import dataclass
import os


@dataclass
class ServerConfig:
    """Server runtime configuration.

    Attributes:
        max_devices: Maximum number of devices that can register simultaneously.
        pending_request_ttl_ms: Pending request time-to-live in milliseconds.
        default_port: Default HTTP/WebSocket server port.
        auth_token: Authentication token for API and WebSocket access.
        enable_test_endpoints: Enable fault injection and test-only APIs.
        report_dir: Directory for test reports and artifacts.
        server_log_store: Server log store backend, either memory or jsonl.
        server_log_jsonl_path: JSONL path used when server_log_store is jsonl.
        server_log_jsonl_max_bytes: Rotate JSONL file after this size; 0 disables rotation.
        server_log_jsonl_max_files: Number of rotated JSONL files to keep.
        server_log_jsonl_retention_ms: Skip expired JSONL records on load; 0 disables retention filtering.
        server_log_jsonl_quarantine_corrupt: Quarantine corrupt JSONL lines when rebuilding the store.
        server_runtime_store: Server runtime metadata store backend, either memory or jsonl.
        server_runtime_jsonl_dir: Directory for runtime metadata JSONL files.
        server_protocol_version: Protocol version advertised in register/reconnect responses.
        max_pending_per_device: Maximum in-flight requests per device; 0 disables the limit.
        connection_diagnostics_max_events: Maximum retained connection diagnostics events.
        target_case_timeout_ms: Target Runner case timeout.
        target_token_grace_ms: Runner credential expiry grace after case timeout.
        target_reset_timeout_ms: Target pre/final Agent reset timeout.
    """
    max_devices: int = 100
    pending_request_ttl_ms: int = 60000
    default_port: int = 8000
    auth_token: str = ""
    enable_test_endpoints: bool = False
    report_dir: str = "reports/latest"
    server_log_store: str = "memory"
    server_log_jsonl_path: str = "reports/latest/server-logs.jsonl"
    server_log_jsonl_max_bytes: int = 0
    server_log_jsonl_max_files: int = 1
    server_log_jsonl_retention_ms: int = 0
    server_log_jsonl_quarantine_corrupt: bool = True
    server_runtime_store: str = "memory"
    server_runtime_jsonl_dir: str = "reports/latest/server-runtime"
    server_protocol_version: int = 1
    max_pending_per_device: int = 64
    connection_diagnostics_max_events: int = 10000
    target_case_timeout_ms: int = 180000
    target_token_grace_ms: int = 10000
    target_reset_timeout_ms: int = 5000

    @classmethod
    def from_env(cls) -> 'ServerConfig':
        """Load configuration from environment variables.

        Environment variables:
            BEACON_MAX_DEVICES: Maximum concurrent devices (default: 100)
            BEACON_PENDING_TTL_MS: Pending request TTL in ms (default: 60000)
            BEACON_PORT: Server port (default: 8000)
            BEACON_AUTH_TOKEN: Authentication token (default: "")
            BEACON_ENABLE_TEST_ENDPOINTS: Enable test APIs (default: false)
            BEACON_REPORT_DIR: Report directory (default: reports/latest)
            BEACON_SERVER_LOG_STORE: Server log store backend (default: memory)
            BEACON_SERVER_LOG_JSONL_PATH: Server JSONL log path (default: reports/latest/server-logs.jsonl)
            BEACON_SERVER_LOG_JSONL_MAX_BYTES: Rotate JSONL file after this size; 0 disables rotation
            BEACON_SERVER_LOG_JSONL_MAX_FILES: Number of rotated JSONL files to keep (default: 1)
            BEACON_SERVER_LOG_JSONL_RETENTION_MS: Skip expired JSONL records on load; 0 disables retention
            BEACON_SERVER_LOG_JSONL_QUARANTINE_CORRUPT: Quarantine corrupt JSONL lines (default: true)
            BEACON_SERVER_RUNTIME_STORE: Server runtime metadata store backend (default: memory)
            BEACON_SERVER_RUNTIME_JSONL_DIR: Runtime metadata JSONL directory
            BEACON_SERVER_PROTOCOL_VERSION: Protocol version hint (default: 1)
            BEACON_MAX_PENDING_PER_DEVICE: Per-device pending limit; 0 disables the limit
            BEACON_CONNECTION_DIAGNOSTICS_MAX_EVENTS: Retained connection diagnostics events
            BEACON_TARGET_CASE_TIMEOUT_MS: Target Runner case timeout in ms
            BEACON_TARGET_TOKEN_GRACE_MS: Runner credential expiry grace in ms
            BEACON_TARGET_RESET_TIMEOUT_MS: Target Agent reset timeout in ms

        Returns:
            ServerConfig instance populated from environment or defaults.
        """
        return cls(
            max_devices=int(os.getenv('BEACON_MAX_DEVICES', '100')),
            pending_request_ttl_ms=int(os.getenv('BEACON_PENDING_TTL_MS', '60000')),
            default_port=int(os.getenv('BEACON_PORT', '8000')),
            auth_token=os.getenv('BEACON_AUTH_TOKEN', ''),
            enable_test_endpoints=os.getenv('BEACON_ENABLE_TEST_ENDPOINTS', 'false').lower() == 'true',
            report_dir=os.getenv('BEACON_REPORT_DIR', 'reports/latest'),
            server_log_store=os.getenv('BEACON_SERVER_LOG_STORE', 'memory'),
            server_log_jsonl_path=os.getenv('BEACON_SERVER_LOG_JSONL_PATH', 'reports/latest/server-logs.jsonl'),
            server_log_jsonl_max_bytes=int(os.getenv('BEACON_SERVER_LOG_JSONL_MAX_BYTES', '0')),
            server_log_jsonl_max_files=int(os.getenv('BEACON_SERVER_LOG_JSONL_MAX_FILES', '1')),
            server_log_jsonl_retention_ms=int(os.getenv('BEACON_SERVER_LOG_JSONL_RETENTION_MS', '0')),
            server_log_jsonl_quarantine_corrupt=(
                os.getenv('BEACON_SERVER_LOG_JSONL_QUARANTINE_CORRUPT', 'true').lower() == 'true'
            ),
            server_runtime_store=os.getenv('BEACON_SERVER_RUNTIME_STORE', 'memory'),
            server_runtime_jsonl_dir=os.getenv(
                'BEACON_SERVER_RUNTIME_JSONL_DIR',
                'reports/latest/server-runtime',
            ),
            server_protocol_version=int(os.getenv('BEACON_SERVER_PROTOCOL_VERSION', '1')),
            max_pending_per_device=int(os.getenv('BEACON_MAX_PENDING_PER_DEVICE', '64')),
            connection_diagnostics_max_events=int(os.getenv('BEACON_CONNECTION_DIAGNOSTICS_MAX_EVENTS', '10000')),
            target_case_timeout_ms=int(os.getenv('BEACON_TARGET_CASE_TIMEOUT_MS', '180000')),
            target_token_grace_ms=int(os.getenv('BEACON_TARGET_TOKEN_GRACE_MS', '10000')),
            target_reset_timeout_ms=int(os.getenv('BEACON_TARGET_RESET_TIMEOUT_MS', '5000')),
        )


# Global configuration instance loaded from environment
CONFIG = ServerConfig.from_env()
