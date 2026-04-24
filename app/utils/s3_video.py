"""
S3 upload and presigned URL helpers for recorded videos.
Uses boto3; credentials via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or IAM role.
Supports S3-compatible backends (e.g. Backblaze B2) via endpoint_url.
"""

import logging

log = logging.getLogger(__name__)


def upload_video(
    local_path: str,
    bucket: str,
    key: str,
    content_type: str,
    region: str | None = None,
    endpoint_url: str | None = None,
) -> bool:
    """Upload a file to an S3 or S3-compatible storage bucket.

    Credentials are read from the environment (``AWS_ACCESS_KEY_ID`` /
    ``AWS_SECRET_ACCESS_KEY``) or an attached IAM role.

    Args:
        local_path: Absolute path to the file to upload.
        bucket: Target S3 bucket name.
        key: Destination object key within the bucket.
        content_type: MIME type of the file (e.g. ``"video/mp4"``).
        region: AWS region name, or ``None`` to use the default.
        endpoint_url: Custom S3-compatible endpoint URL (e.g. Backblaze B2),
            or ``None`` for the standard AWS endpoint.

    Returns:
        ``True`` on success, ``False`` if the upload raises an exception.
    """
    try:
        import boto3

        extra = {"region_name": region} if region else {}
        if endpoint_url is not None:
            extra["endpoint_url"] = endpoint_url
        client = boto3.client("s3", **extra)
        with open(local_path, "rb") as f:
            client.upload_fileobj(
                f,
                bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        log.info("s3_video: uploaded %s to s3://%s/%s", local_path, bucket, key)
        return True
    except Exception as e:
        log.exception("s3_video: upload failed for %s: %s", key, e)
        return False


def get_presigned_url(
    bucket: str,
    key: str,
    region: str | None = None,
    expiry_seconds: int = 3600,
    endpoint_url: str | None = None,
) -> str | None:
    """Generate a presigned GET URL for an S3 object.

    Args:
        bucket: S3 bucket name.
        key: Object key within the bucket.
        region: AWS region name, or ``None`` for the default.
        expiry_seconds: How long (in seconds) the URL is valid for.
            Defaults to 3600 (1 hour).
        endpoint_url: Custom S3-compatible endpoint URL, or ``None`` for
            the standard AWS endpoint.

    Returns:
        A presigned HTTPS URL string, or ``None`` if URL generation fails.
    """
    try:
        import boto3

        extra = {"region_name": region} if region else {}
        if endpoint_url is not None:
            extra["endpoint_url"] = endpoint_url
        client = boto3.client("s3", **extra)
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry_seconds,
        )
        return url
    except Exception as e:
        log.warning("s3_video: presigned url failed for %s: %s", key, e)
        return None
