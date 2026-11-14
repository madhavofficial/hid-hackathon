"""
Person 3: Face collection & S3 enrollment for HID Build Beyond.

Usage:
  python -m identity.enroll setup
  python -m identity.enroll add <person_id> <image_path> --phone +919876543210
  python -m identity.enroll list
  python -m identity.enroll remove <person_id>
"""
import argparse
import mimetypes
import re
from pathlib import Path
import boto3
from botocore.exceptions import ClientError

from .config import AWS_REGION, COLLECTION_ID, PEOPLE_TABLE, S3_BUCKET, S3_PREFIX

PERSON_ID_RE = re.compile(r"^[A-Za-z0-9_.\-:]+$")
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _clients():
    s3 = boto3.client("s3", region_name=AWS_REGION)
    rek = boto3.client("rekognition", region_name=AWS_REGION)
    return s3, rek


def require_person_id(person_id: str) -> str:
    person_id = (person_id or "").strip()
    if not person_id or len(person_id) > 255 or not PERSON_ID_RE.fullmatch(person_id):
        raise ValueError(
            "person_id must be letters, digits, or . _ - : "
            f"(Rekognition ExternalImageId). Got {person_id!r}."
        )
    return person_id


def require_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if not PHONE_RE.fullmatch(phone):
        raise ValueError(f"phone must be E.164, for example +919876543210. Got {phone!r}.")
    return phone


def ensure_bucket(bucket: str = S3_BUCKET) -> str:
    s3, _ = _clients()
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchBucket"):
            if AWS_REGION == "us-east-1":
                s3.create_bucket(Bucket=bucket)
            else:
                s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": AWS_REGION},
                )
        else:
            raise
    return bucket


def ensure_collection(collection_id: str = COLLECTION_ID) -> str:
    _, rek = _clients()
    try:
        rek.describe_collection(CollectionId=collection_id)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            rek.create_collection(CollectionId=collection_id)
        else:
            raise
    return collection_id


def ensure_people_table(table_name: str = PEOPLE_TABLE) -> str:
    ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
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
    return table_name


def save_phone(person_id: str, phone: str, table_name: str = PEOPLE_TABLE) -> None:
    person_id = require_person_id(person_id)
    phone = require_phone(phone)
    ensure_people_table(table_name)
    boto3.resource("dynamodb", region_name=AWS_REGION).Table(table_name).put_item(
        Item={"person_id": person_id, "phone": phone}
    )


def get_phone(person_id: str, table_name: str = PEOPLE_TABLE) -> str | None:
    person_id = require_person_id(person_id)
    ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
    try:
        ddb.meta.client.describe_table(TableName=table_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return None
        raise
    item = ddb.Table(table_name).get_item(Key={"person_id": person_id}).get("Item")
    if not item:
        return None
    return str(item["phone"])


def delete_phone(person_id: str, table_name: str = PEOPLE_TABLE) -> None:
    person_id = require_person_id(person_id)
    ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
    try:
        ddb.meta.client.describe_table(TableName=table_name)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
            return
        raise
    ddb.Table(table_name).delete_item(Key={"person_id": person_id})


def _is_final_person_object(tail: str, person_id: str) -> bool:
    if ".pending" in tail:
        return False
    return tail == person_id or tail.startswith(person_id + ".")


def _delete_s3_objects(person_id: str, bucket: str) -> None:
    s3, _ = _clients()
    prefix = f"{S3_PREFIX}{person_id}"
    try:
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchBucket"):
            return
        raise
    for obj in resp.get("Contents", []):
        tail = obj["Key"][len(S3_PREFIX):]
        if _is_final_person_object(tail, person_id):
            s3.delete_object(Bucket=bucket, Key=obj["Key"])


def enroll_person(
    person_id: str,
    image_path: str,
    bucket: str = S3_BUCKET,
    collection_id: str = COLLECTION_ID,
    phone: str | None = None,
) -> dict:
    """Upload photo to S3 and index the face with ExternalImageId=person_id."""
    person_id = require_person_id(person_id)
    if phone:
        phone = require_phone(phone)
    path = Path(image_path)
    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {image_path}")

    s3, rek = _clients()
    ensure_bucket(bucket)
    ensure_collection(collection_id)

    ext = path.suffix.lower() or ".jpg"
    final_key = f"{S3_PREFIX}{person_id}{ext}"
    pending_key = f"{S3_PREFIX}{person_id}.pending{ext}"
    content_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"

    s3.upload_file(
        Filename=str(path),
        Bucket=bucket,
        Key=pending_key,
        ExtraArgs={"ContentType": content_type},
    )
    try:
        resp = rek.index_faces(
            CollectionId=collection_id,
            Image={"S3Object": {"Bucket": bucket, "Name": pending_key}},
            ExternalImageId=person_id,
            MaxFaces=1,
            QualityFilter="AUTO",
            DetectionAttributes=["DEFAULT"],
        )
    except ClientError:
        s3.delete_object(Bucket=bucket, Key=pending_key)
        raise

    records = resp.get("FaceRecords", [])
    if not records:
        s3.delete_object(Bucket=bucket, Key=pending_key)
        unindexed = resp.get("UnindexedFaces", [])
        raise ValueError(f"No face indexed for {person_id}. Unindexed: {unindexed}")

    existing = [
        face["face_id"]
        for face in list_enrolled(collection_id)
        if face["person_id"] == person_id
        and face["face_id"]
        and face["face_id"] != records[0]["Face"]["FaceId"]
    ]
    if existing:
        rek.delete_faces(CollectionId=collection_id, FaceIds=existing)
    _delete_s3_objects(person_id, bucket)
    s3.copy_object(
        Bucket=bucket,
        Key=final_key,
        CopySource={"Bucket": bucket, "Key": pending_key},
        ContentType=content_type,
        MetadataDirective="REPLACE",
    )
    s3.delete_object(Bucket=bucket, Key=pending_key)
    s3_key = final_key

    face = records[0]["Face"]
    if phone:
        save_phone(person_id, phone)
    return {
        "person_id": person_id,
        "face_id": face["FaceId"],
        "confidence": face["Confidence"],
        "s3_bucket": bucket,
        "s3_key": s3_key,
        "collection_id": collection_id,
        "phone": phone,
    }


def list_enrolled(collection_id: str = COLLECTION_ID) -> list[dict]:
    _, rek = _clients()
    faces: list[dict] = []
    kwargs = {"CollectionId": collection_id, "MaxResults": 100}
    while True:
        resp = rek.list_faces(**kwargs)
        for face in resp.get("Faces", []):
            faces.append(
                {
                    "person_id": face.get("ExternalImageId"),
                    "face_id": face.get("FaceId"),
                    "confidence": face.get("Confidence"),
                }
            )
        token = resp.get("NextToken")
        if not token:
            break
        kwargs["NextToken"] = token
    return faces


def remove_person(
    person_id: str,
    collection_id: str = COLLECTION_ID,
    bucket: str = S3_BUCKET,
) -> list[str]:
    person_id = require_person_id(person_id)
    _, rek = _clients()
    face_ids = [
        f["face_id"]
        for f in list_enrolled(collection_id)
        if f["person_id"] == person_id and f["face_id"]
    ]
    deleted: list[str] = []
    if face_ids:
        resp = rek.delete_faces(CollectionId=collection_id, FaceIds=face_ids)
        deleted = resp.get("DeletedFaces", [])
    _delete_s3_objects(person_id, bucket)
    delete_phone(person_id)
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="HID Hackathon face enrollment")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup", help="Create S3 bucket and Rekognition collection")

    add_p = sub.add_parser("add", help="Enroll a person photo")
    add_p.add_argument("person_id", help="ExternalImageId, e.g. alice")
    add_p.add_argument("image_path", help="Local path to JPEG/PNG photo")
    add_p.add_argument("--phone", help="E.164 number used for the SMS code, e.g. +919876543210")

    sub.add_parser("list", help="List enrolled faces in the collection")

    rm_p = sub.add_parser("remove", help="Delete a person's faces from collection")
    rm_p.add_argument("person_id")

    args = parser.parse_args()
    if args.cmd == "setup":
        b = ensure_bucket()
        c = ensure_collection()
        print(f"Ready: S3 bucket={b}, Rekognition collection={c}, region={AWS_REGION}")
    elif args.cmd == "add":
        result = enroll_person(args.person_id, args.image_path, phone=args.phone)
        print(result)
    elif args.cmd == "list":
        for item in list_enrolled():
            print(item)
    elif args.cmd == "remove":
        deleted = remove_person(args.person_id)
        print(f"Deleted faces: {deleted}")


if __name__ == "__main__":
    main()
