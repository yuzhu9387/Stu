from uuid import uuid4

import pytest

from recipe_agent.infrastructure.storage.s3 import S3ObjectStore


class RecordingS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def put_object(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


@pytest.mark.asyncio
async def test_upload_returns_private_object_key_instead_of_public_url() -> None:
    household_id = uuid4()
    client = RecordingS3Client()
    store = S3ObjectStore(bucket="recipe-agent", client=client)

    object_key = await store.put(
        household_id=household_id,
        filename="Family Soup.jpg",
        content_type="image/jpeg",
        body=b"image",
    )

    assert object_key.startswith(f"households/{household_id}/")
    assert object_key.endswith("family-soup.jpg")
    assert not object_key.startswith("http")
    assert client.calls[0]["Bucket"] == "recipe-agent"
