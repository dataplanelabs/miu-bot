"""SeaweedFS media upload via boto3 S3 API."""

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def get_media_client(endpoint_url: str, access_key: str, secret_key: str) -> "S3Client":
    """Create boto3 S3 client for SeaweedFS."""
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def upload_media(
    client: "S3Client",
    bucket: str,
    workspace_id: str,
    session_id: str,
    file_path: str,
    mime_type: str,
    ttl_days: int = 90,
) -> dict:
    """Upload file to SeaweedFS, return media ref dict.

    Note: This is a synchronous/blocking call. Callers in async context
    should wrap with ``await asyncio.to_thread(upload_media, ...)``.
    """
    p = Path(file_path)
    key = f"{workspace_id}/{session_id}/{uuid4().hex[:12]}{p.suffix}"
    extra_args: dict = {"ContentType": mime_type}
    if ttl_days:
        extra_args["Metadata"] = {"X-Seaweedfs-Ttl": f"{ttl_days * 24}h"}
    client.upload_file(str(p), bucket, key, ExtraArgs=extra_args)
    return {"key": key, "mime": mime_type, "size": p.stat().st_size}
