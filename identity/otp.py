"""
Person 3: Amazon SNS one-time code (OTP) step-up verification.

Usage:
  python -m identity.otp setup
  python -m identity.otp send --person-id alice
  python -m identity.otp send --person-id alice --phone +919876543210
  python -m identity.otp verify 123456 --person-id alice
"""
import argparse
import secrets
import time
import boto3
from botocore.exceptions import ClientError

from .config import AWS_REGION, OTP_MAX_ATTEMPTS, OTP_TABLE, OTP_TTL_SECONDS


def _clients():
    ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
    sns = boto3.client("sns", region_name=AWS_REGION)
    return ddb, sns


def ensure_otp_table(table_name: str = OTP_TABLE) -> str:
    ddb, _ = _clients()
    client = ddb.meta.client
    try:
        client.describe_table(TableName=table_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        table = ddb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "person_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "person_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        try:
            client.update_time_to_live(
                TableName=table_name,
                TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"},
            )
        except ClientError:
            pass
    return table_name


def send_otp(
    person_id: str,
    phone_number: str | None = None,
    table_name: str = OTP_TABLE,
    ttl_seconds: int = OTP_TTL_SECONDS,
) -> dict:
    """Generate a 6-digit OTP, store it, and send it by SMS.

    The code is not included in the return value. Person 2 should only
    learn whether a later check is valid or invalid.
    """
    from .enroll import get_phone, require_person_id, require_phone

    person_id = require_person_id(person_id)
    if phone_number:
        phone_number = require_phone(phone_number)
    else:
        phone_number = get_phone(person_id)
    if not phone_number:
        raise ValueError(
            f"No phone stored for {person_id}. Enroll with --phone or pass --phone."
        )

    ddb, sns = _clients()
    ensure_otp_table(table_name)

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = int(time.time()) + ttl_seconds
    table = ddb.Table(table_name)
    table.put_item(
        Item={
            "person_id": person_id,
            "code": code,
            "expires_at": expires_at,
            "attempts": 0,
        }
    )

    try:
        sns.publish(
            PhoneNumber=phone_number,
            Message=f"HID Kiosk verification code: {code}. Valid for {ttl_seconds // 60} min.",
            MessageAttributes={
                "AWS.SNS.SMS.SMSType": {
                    "DataType": "String",
                    "StringValue": "Transactional",
                }
            },
        )
    except ClientError:
        table.delete_item(Key={"person_id": person_id})
        raise

    return {
        "person_id": person_id,
        "sns_sent": True,
        "expires_at": expires_at,
    }


def verify_otp(
    otp: str | None,
    person_id: str,
    table_name: str = OTP_TABLE,
    max_attempts: int = OTP_MAX_ATTEMPTS,
) -> bool:
    """Return True when the code matches. Return False when it does not.

    person_id must be the enrolled ExternalImageId from SearchFacesByImage.
    Raises ValueError when otp or person_id is missing. Raises ClientError
    when DynamoDB cannot be read, so a broken table is not treated as a wrong code.
    """
    from .enroll import require_person_id

    person_id = require_person_id(person_id)
    if otp is None or str(otp).strip() == "":
        raise ValueError("otp is required. Do not call verify_otp on the first visit.")

    ddb, _ = _clients()
    table = ddb.Table(table_name)
    resp = table.get_item(Key={"person_id": person_id})
    item = resp.get("Item")
    if not item:
        return False

    if int(item.get("expires_at", 0)) < int(time.time()):
        table.delete_item(Key={"person_id": person_id})
        return False

    if str(item.get("code", "")).strip() != str(otp).strip():
        attempts = int(item.get("attempts", 0)) + 1
        if attempts >= max_attempts:
            table.delete_item(Key={"person_id": person_id})
        else:
            table.update_item(
                Key={"person_id": person_id},
                UpdateExpression="SET attempts = :attempts",
                ExpressionAttributeValues={":attempts": attempts},
            )
        return False

    table.delete_item(Key={"person_id": person_id})
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="HID Hackathon SNS OTP helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="Create DynamoDB OTP table")

    send_p = sub.add_parser("send", help="Send an OTP via SNS")
    send_p.add_argument("--person-id", required=True, help="Enrolled ExternalImageId, e.g. alice")
    send_p.add_argument("--phone", help="E.164 number. Optional when enroll stored one.")

    ver_p = sub.add_parser("verify", help="Verify an OTP code")
    ver_p.add_argument("code")
    ver_p.add_argument("--person-id", required=True, help="Same id used at enrollment")

    args = parser.parse_args()
    if args.cmd == "setup":
        print(f"Ready: DynamoDB table={ensure_otp_table()}, region={AWS_REGION}")
    elif args.cmd == "send":
        print(send_otp(args.person_id, phone_number=args.phone))
    elif args.cmd == "verify":
        ok = verify_otp(args.code, person_id=args.person_id)
        print("valid" if ok else "invalid")


if __name__ == "__main__":
    main()
