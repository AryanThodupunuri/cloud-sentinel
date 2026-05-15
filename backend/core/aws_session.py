"""
AWS session helpers for CloudSentinel v2
- get_assumed_role_session(role_arn, external_id) -> boto3.Session
- validate_assumed_role(role_arn, external_id) -> dict

This module intentionally never persists raw AWS credentials.
"""
from datetime import datetime
import boto3
import botocore


def get_assumed_role_session(role_arn: str, external_id: str = None) -> boto3.Session:
    """Assume the provided role and return a boto3.Session using temporary creds.

    Raises botocore.exceptions.ClientError on failure.
    """
    sts_client = boto3.client("sts")
    assume_kwargs = {
        "RoleArn": role_arn,
    "RoleSessionName": "CloudSentinelSession",
    }
    if external_id:
        assume_kwargs["ExternalId"] = external_id

    resp = sts_client.assume_role(**assume_kwargs)
    creds = resp["Credentials"]

    # Create a new session with temporary credentials
    session = boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds.get("SessionToken"),
    )
    return session


def validate_assumed_role(role_arn: str, external_id: str = None) -> dict:
    """Validate that we can assume the role and return caller identity info.

    Returns a dict with keys: account_id, arn, user_id, status (bool), error(optional)
    """
    try:
        session = get_assumed_role_session(role_arn, external_id)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        return {
            "account_id": identity.get("Account"),
            "arn": identity.get("Arn"),
            "user_id": identity.get("UserId"),
            "status": True,
        }
    except botocore.exceptions.ClientError as e:
        return {"status": False, "error": str(e)}
    except Exception as e:
        return {"status": False, "error": str(e)}
