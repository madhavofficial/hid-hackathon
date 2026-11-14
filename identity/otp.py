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


def _sms_sandbox_block_reason(sns, phone_number: str) -> str | None:
    """Return an error string when the sandbox will reject this number.

    Returns None when the account is not in the sandbox, the number is verified,
    or this role cannot read sandbox status. The caller then uses sns.publish.
    """
    try:
        status = sns.get_sms_sandbox_account_status()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "AccessDeniedException":
            return None
        raise
    if not status.get("IsInSandbox"):
        return None

    token = None
    while True:
        kwargs = {"NextToken": token} if token else {}
        try:
            page = sns.list_sms_sandbox_phone_numbers(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "AccessDeniedException":
                return None
            raise
        for number in page.get("PhoneNumbers", []):
            if number.get("PhoneNumber") == phone_number and number.get("Status") == "Verified":
                return None
        token = page.get("NextToken")
        if not token:
            break
    return (
        f"{phone_number} is not a verified SNS SMS sandbox number. "
        "Verify it in the SNS console before sending."
    )


def _denied(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "AccessDeniedException"


def _sms_spend_block_reason(sns) -> str | None:
    """Raise the spend limit from 0 when this role is allowed to. Otherwise explain why."""
    try:
        attrs = sns.get_sms_attributes(attributes=["MonthlySpendLimit"])
    except ClientError as exc:
        if _denied(exc):
            return None
        raise
    raw = (attrs.get("attributes") or {}).get("MonthlySpendLimit")
    try:
        limit = float(raw) if raw not in (None, "") else 0.0
    except ValueError:
        limit = 0.0
    if limit > 0:
        return None
    try:
        sns.set_sms_attributes(attributes={"MonthlySpendLimit": "1"})
    except ClientError as exc:
        if _denied(exc):
            return (
                "SNS monthly spend limit is 0 and this role cannot raise it. "
                "Set MonthlySpendLimit in the SNS console, then retry."
            )
        raise
    return None


def _publish_failure(exc: ClientError) -> BaseException:
    message = exc.response.get("Error", {}).get("Message", "")
    low = message.lower()
    if "origination" in low or "sender id" in low or "no identity" in low:
        return ValueError(
            "SNS has no origination identity for this destination. "
            "In the SNS console, add a toll-free number or sender ID, then retry. "
            f"AWS said: {message}"
        )
    if "spend" in low or "monthly" in low or "quota" in low:
        return ValueError(
            "SNS monthly spend limit blocked the text. "
            "Raise MonthlySpendLimit in the SNS console, then retry. "
            f"AWS said: {message}"
        )
    return exc


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
    sandbox_reason = _sms_sandbox_block_reason(sns, phone_number)
    if sandbox_reason:
        raise ValueError(sandbox_reason)
    spend_reason = _sms_spend_block_reason(sns)
    if spend_reason:
        raise ValueError(spend_reason)
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
    except ClientError as exc:
        table.delete_item(Key={"person_id": person_id})
        raise _publish_failure(exc) from exc

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
    from .config import COLLECTION_ID
    from .enroll import list_enrolled, require_person_id

    person_id = require_person_id(person_id)
    if otp is None or str(otp).strip() == "":
        raise ValueError("otp is required. Do not call verify_otp on the first visit.")

    enrolled_ids = {
        face["person_id"]
        for face in list_enrolled(COLLECTION_ID)
        if face.get("person_id")
    }
    if person_id not in enrolled_ids:
        raise ValueError(f"{person_id} is not enrolled in collection {COLLECTION_ID}.")

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
