"""
S3 upload and presigned URL helpers for recorded videos.
Uses boto3; credentials via AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY or IAM role.
Supports S3-compatible backends (e.g. Backblaze B2) via endpoint_url.
"""

import logging

log = logging.getLogger(__name__)


def upload_video(local_path, bucket, key, content_type, region=None, endpoint_url=None):
    """
    Upload a file to S3 (or S3-compatible storage). Returns True on success, False on failure.
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


def get_presigned_url(bucket, key, region=None, expiry_seconds=3600, endpoint_url=None):
    """
    Return a presigned GET URL for the S3 object, or None on failure.
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
