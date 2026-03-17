"""MinIO client — object storage for Artifacts.

Reference: SYSTEM_DESIGN.md §1.6, §3.7.1, §6.12
"""

from __future__ import annotations

import io
import logging
import os
from typing import BinaryIO
from uuid import UUID

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

ARTIFACTS_BUCKET = "artifacts"


class MinIOClient:
    """Thin wrapper around minio.Minio for daemon Artifact storage.

    Path convention: artifacts/{job_id}/{step_id}/{filename}
    or artifacts/{job_id}/{filename} for Job-level artifacts.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool = False,
    ) -> None:
        self._endpoint = endpoint or os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        self._access_key = access_key or os.environ.get("MINIO_ROOT_USER", "minioadmin")
        self._secret_key = secret_key or os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")
        self._secure = secure

        self._client = Minio(
            self._endpoint,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=self._secure,
        )

    def ensure_bucket(self) -> None:
        """Create the artifacts bucket if it doesn't exist."""
        if not self._client.bucket_exists(ARTIFACTS_BUCKET):
            self._client.make_bucket(ARTIFACTS_BUCKET)
            logger.info("Created MinIO bucket: %s", ARTIFACTS_BUCKET)

    def build_path(
        self,
        job_id: UUID,
        filename: str,
        step_id: UUID | None = None,
    ) -> str:
        """Build a MinIO object path following the convention."""
        if step_id:
            return f"{job_id}/{step_id}/{filename}"
        return f"{job_id}/{filename}"

    def upload_bytes(
        self,
        path: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload bytes to MinIO. Returns the minio_path."""
        stream = io.BytesIO(data)
        self._client.put_object(
            ARTIFACTS_BUCKET,
            path,
            stream,
            length=len(data),
            content_type=content_type,
        )
        logger.info("Uploaded %d bytes to %s/%s", len(data), ARTIFACTS_BUCKET, path)
        return path

    def upload_stream(
        self,
        path: str,
        stream: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload a file-like stream to MinIO. Returns the minio_path."""
        self._client.put_object(
            ARTIFACTS_BUCKET,
            path,
            stream,
            length=length,
            content_type=content_type,
        )
        logger.info("Uploaded stream (%d bytes) to %s/%s", length, ARTIFACTS_BUCKET, path)
        return path

    def download_bytes(self, path: str) -> bytes:
        """Download an object as bytes."""
        response = self._client.get_object(ARTIFACTS_BUCKET, path)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def download_stream(self, path: str):
        """Download an object as a streaming response. Caller must close."""
        return self._client.get_object(ARTIFACTS_BUCKET, path)

    def stat(self, path: str) -> dict:
        """Get object metadata (size, content-type, etc.)."""
        stat = self._client.stat_object(ARTIFACTS_BUCKET, path)
        return {
            "size": stat.size,
            "content_type": stat.content_type,
            "last_modified": stat.last_modified,
            "etag": stat.etag,
        }

    def exists(self, path: str) -> bool:
        """Check if an object exists."""
        try:
            self._client.stat_object(ARTIFACTS_BUCKET, path)
            return True
        except S3Error:
            return False

    def delete(self, path: str) -> None:
        """Delete an object."""
        self._client.remove_object(ARTIFACTS_BUCKET, path)
        logger.info("Deleted %s/%s", ARTIFACTS_BUCKET, path)

    def list_objects(self, prefix: str) -> list[str]:
        """List object keys under a prefix."""
        objects = self._client.list_objects(ARTIFACTS_BUCKET, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]

    def presigned_url(self, path: str, expires_hours: int = 1) -> str:
        """Generate a presigned download URL."""
        from datetime import timedelta
        return self._client.presigned_get_object(
            ARTIFACTS_BUCKET, path, expires=timedelta(hours=expires_hours)
        )

    def healthy(self) -> bool:
        """Quick health check — can we list buckets?"""
        try:
            self._client.list_buckets()
            return True
        except Exception:
            return False
