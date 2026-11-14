"""
Person 3 (Spare / Later path): Amazon Rekognition Face Liveness helpers.
Only used if a mask or hard video gets through CPU checks during testing.

Usage:
  python -m identity.liveness setup
"""
import argparse
import json

import boto3
from botocore.exceptions import ClientError

from .config import AWS_REGION, LIVENESS_CONFIDENCE_THRESHOLD

POOL_NAME = "hid_liveness"
ROLE_NAME = "hid-liveness-unauth"


def _rek():
    return boto3.client("rekognition", region_name=AWS_REGION)


def create_liveness_session() -> dict:
    """Create a Face Liveness session and return its SessionId."""
    resp = _rek().create_face_liveness_session()
    return {"session_id": resp["SessionId"]}


def get_liveness_result(
    session_id: str,
    threshold: float = LIVENESS_CONFIDENCE_THRESHOLD,
) -> dict:
    """
    Fetch Face Liveness results.
    Returns confidence, is_live, status, and reference_image_bytes
    (for running SearchFacesByImage on the verified live frame).
    """
    resp = _rek().get_face_liveness_session_results(SessionId=session_id)
    confidence = float(resp.get("Confidence", 0.0))
    status = resp.get("Status", "UNKNOWN")
    ref_bytes = resp.get("ReferenceImage", {}).get("Bytes")
    return {
        "session_id": session_id,
        "status": status,
        "confidence": confidence,
        "is_live": status == "SUCCEEDED" and confidence >= threshold,
        "reference_image_bytes": ref_bytes,
    }


def _denied(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in ("AccessDenied", "AccessDeniedException")


def _find_pool_id(cog, name: str) -> str | None:
    token = None
    while True:
        kwargs = {"MaxResults": 60}
        if token:
            kwargs["NextToken"] = token
        page = cog.list_identity_pools(**kwargs)
        for pool in page.get("IdentityPools", []):
            if pool.get("IdentityPoolName") == name:
                return pool["IdentityPoolId"]
        token = page.get("NextToken")
        if not token:
            return None


def setup_liveness_auth() -> dict:
    """Create the Cognito identity pool and guest role the kiosk uses to stream Face Liveness.

    Hand Person 1 the returned identity_pool_id and region. The guest role can call
    rekognition:StartFaceLivenessSession only.
    """
    cog = boto3.client("cognito-identity", region_name=AWS_REGION)
    iam = boto3.client("iam")
    pool_id = _find_pool_id(cog, POOL_NAME)
    if not pool_id:
        created = cog.create_identity_pool(
            IdentityPoolName=POOL_NAME,
            AllowUnauthenticatedIdentities=True,
        )
        pool_id = created["IdentityPoolId"]
    cog.update_identity_pool(
        IdentityPoolId=pool_id,
        IdentityPoolName=POOL_NAME,
        AllowUnauthenticatedIdentities=True,
    )

    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": "cognito-identity.amazonaws.com"},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {"cognito-identity.amazonaws.com:aud": pool_id},
                    "ForAnyValue:StringLike": {"cognito-identity.amazonaws.com:amr": "unauthenticated"},
                },
            }
        ],
    }
    try:
        iam.get_role(RoleName=ROLE_NAME)
        iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code == "NoSuchEntity":
            try:
                iam.create_role(
                    RoleName=ROLE_NAME,
                    AssumeRolePolicyDocument=json.dumps(trust),
                    Description="Unauthenticated guests for HID Face Liveness",
                )
            except ClientError as create_exc:
                if _denied(create_exc):
                    raise RuntimeError(
                        "WSParticipantRole cannot create the Face Liveness guest role. "
                        "The identity pool exists, but the kiosk cannot stream until an admin "
                        f"creates {ROLE_NAME} and allows rekognition:StartFaceLivenessSession."
                    ) from create_exc
                raise
        elif _denied(exc):
            raise RuntimeError(
                "WSParticipantRole cannot read or update the Face Liveness guest role."
            ) from exc
        else:
            raise

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "rekognition:StartFaceLivenessSession",
                "Resource": "*",
            }
        ],
    }
    try:
        iam.put_role_policy(
            RoleName=ROLE_NAME,
            PolicyName="hid-liveness-start",
            PolicyDocument=json.dumps(policy),
        )
        role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
    except ClientError as exc:
        if _denied(exc):
            raise RuntimeError(
                "WSParticipantRole cannot attach rekognition:StartFaceLivenessSession "
                f"to {ROLE_NAME}."
            ) from exc
        raise

    cog.set_identity_pool_roles(
        IdentityPoolId=pool_id,
        Roles={"unauthenticated": role_arn},
    )
    return {
        "identity_pool_id": pool_id,
        "region": AWS_REGION,
        "role_arn": role_arn,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HID Face Liveness guest auth")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="Create the Cognito identity pool and guest role")
    args = parser.parse_args()
    if args.cmd == "setup":
        result = setup_liveness_auth()
        print(
            "Hand Person 1: "
            f"identity_pool_id={result['identity_pool_id']} region={result['region']}"
        )


if __name__ == "__main__":
    main()
