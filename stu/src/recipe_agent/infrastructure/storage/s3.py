"""S3-compatible private object storage."""

import re
from typing import Protocol
from uuid import UUID, uuid4


class AsyncS3Client(Protocol):
    async def put_object(self, **kwargs: object) -> object: ...


class S3ObjectStore:
    def __init__(self, *, bucket: str, client: AsyncS3Client) -> None:
        self._bucket = bucket
        self._client = client

    async def put(
        self,
        *,
        household_id: UUID,
        filename: str,
        content_type: str,
        body: bytes,
    ) -> str:
        safe_filename = _safe_filename(filename)
        object_key = f"households/{household_id}/{uuid4()}/{safe_filename}"
        await self._client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=body,
            ContentType=content_type,
        )
        return object_key


def _safe_filename(filename: str) -> str:
    normalized = re.sub(r"[^a-z0-9.]+", "-", filename.casefold()).strip("-.")
    return normalized or "upload"
