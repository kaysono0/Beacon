"""Artifact 引用与元数据存储，以及 Observation 接入。"""

import asyncio
import json
import uuid
from pathlib import Path

from app.observations.observation_ingress import artifact_observation
from app.observations.observation_service import ObservationService


class ArtifactStore:
    """服务端内存 artifact 索引。

    本类只保存 artifact 引用和元数据，不内联大文件内容。
    """

    def __init__(self, observation_service: ObservationService | None = None) -> None:
        self._artifacts: dict[str, dict] = {}
        self._observation_service = observation_service
        self._lock = asyncio.Lock()

    async def put(self, node_id: str, artifact_type: str, path: str, metadata: dict) -> str:
        artifact_id = f"artifact-{uuid.uuid4().hex}"
        artifact = {
            "artifact_id": artifact_id,
            "node_id": node_id,
            "artifact_type": artifact_type,
            "path": path,
            "metadata": metadata,
        }
        if self._observation_service is not None:
            await self._observation_service.ingest(artifact_observation(artifact))
        async with self._lock:
            self._artifacts[artifact_id] = artifact
        return artifact_id

    async def get(self, artifact_id: str) -> dict:
        async with self._lock:
            return self._artifacts[artifact_id]

    async def query(
        self,
        run_id: str | None = None,
        case_id: str | None = None,
        step_id: str | None = None,
        node_id: str | None = None,
        artifact_type: str | None = None,
    ) -> list[dict]:
        async with self._lock:
            artifacts = list(self._artifacts.values())
        return [
            artifact
            for artifact in artifacts
            if (node_id is None or artifact.get("node_id") == node_id)
            and (artifact_type is None or artifact.get("artifact_type") == artifact_type)
            and _artifact_metadata_matches(artifact, "run_id", run_id)
            and _artifact_metadata_matches(artifact, "case_id", case_id)
            and _artifact_metadata_matches(artifact, "step_id", step_id)
        ]


class JsonlArtifactStore(ArtifactStore):
    """JSONL artifact 索引。

    只保存 artifact 引用和 metadata，不复制或内联 artifact 文件内容。
    """

    def __init__(self, path: str | Path, observation_service: ObservationService | None = None) -> None:
        super().__init__(observation_service=observation_service)
        self._path = Path(path)
        self._load()

    async def put(self, node_id: str, artifact_type: str, path: str, metadata: dict) -> str:
        artifact_id = f"artifact-{uuid.uuid4().hex}"
        artifact = {
            "artifact_id": artifact_id,
            "node_id": node_id,
            "artifact_type": artifact_type,
            "path": path,
            "metadata": metadata,
        }
        if self._observation_service is not None:
            await self._observation_service.ingest(artifact_observation(artifact))
        async with self._lock:
            self._append_locked(artifact)
            self._artifacts[artifact_id] = artifact
        return artifact_id

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                artifact = json.loads(line)
            except json.JSONDecodeError:
                self._quarantine_bad_line(line)
                continue
            if not self._is_valid_artifact(artifact):
                self._quarantine_bad_line(line)
                continue
            artifact_id = artifact.get("artifact_id")
            self._artifacts[artifact_id] = artifact

    def _is_valid_artifact(self, artifact: object) -> bool:
        return (
            isinstance(artifact, dict)
            and isinstance(artifact.get("artifact_id"), str)
            and isinstance(artifact.get("node_id"), str)
            and isinstance(artifact.get("artifact_type"), str)
            and isinstance(artifact.get("path"), str)
            and isinstance(artifact.get("metadata"), dict)
        )

    def _quarantine_bad_line(self, line: str) -> None:
        quarantine_path = Path(f"{self._path}.corrupt")
        quarantine_path.parent.mkdir(parents=True, exist_ok=True)
        with quarantine_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")

    def _append_locked(self, artifact: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(artifact, ensure_ascii=False, sort_keys=True) + "\n")


def _artifact_metadata_matches(artifact: dict, key: str, expected: str | None) -> bool:
    if expected is None:
        return True
    metadata = artifact.get("metadata", {})
    return isinstance(metadata, dict) and metadata.get(key) == expected
