# Identity and step-up notes for Person 4

This describes the current `POST /check` implementation and the separate
Person 3 identity helpers. The decision API does not expose a separate
identity or OTP status field.

## Identity

`SearchFacesByImage` returns a similarity and, when matched, a Rekognition
`ExternalImageId`. The service treats that external ID as `person_id`. `FaceId`
is not used for the API result or visit row.

- A match is accepted only when a result has an `ExternalImageId` and
  `Similarity` meets `SIMILARITY_THRESHOLD` (default `90`).
- No match is represented internally as no person ID and similarity `0`.
  After quality and liveness checks pass, the API returns
  `decision: "deny"` and `reason: "identity_mismatch"`.
- A low-quality face or low live score takes precedence and returns
  `ask_again` / `low_quality` or `deny` / `spoof`, respectively.

Neither `person_id` nor Rekognition `FaceId` is included in the response or
the `visits` row.

## OTP step-up

An OTP is checked only when the request supplies a non-null `otp`. The service
uses the matched `person_id` to read Person 3's OTP table (`OTP_DYNAMODB_TABLE`,
default `hid_otp_codes`).

- A valid, unexpired OTP is consumed (its OTP-table row is deleted). Processing
  continues through the normal quality, liveness, motion, and identity
  decision; OTP success alone does not guarantee `allow`.
- A wrong, expired, missing-from-table, or supplied OTP without a matched
  person returns `decision: "deny"` and `reason: "otp_failed"`.
- An expired or successfully used code is deleted. Wrong codes increment
  `attempts`; the row is deleted once `OTP_MAX_ATTEMPTS` is reached (default
  `5`).
- `otp: null` means no OTP check; it is not an OTP failure.
- The OTP/code is not copied into the visit record. The service does not write
  a separate OTP verification event. It writes the resulting visit decision
  and reason to the `visits` table; therefore an OTP success is not
  independently distinguishable there if later checks produce another
  outcome.

## Face Liveness

Person 3 has separate Rekognition Face Liveness helpers which return
`session_id`, `status`, `confidence`, `is_live`, and a reference image. They
are not called by Person 2's `/check` endpoint, and these fields are not
included in Person 2 responses or visit rows. Person 2 uses the local ONNX
anti-spoof score instead.

## Current `/check` responses

Every successful analysis response has this shape:

```json
{
  "decision": "allow",
  "reason": "live_and_match",
  "scores": {
    "spoof": 0.97,
    "similarity": 96.4,
    "sharpness": 78.0
  },
  "elapsed_ms": 640
}
```

This example indicates an enrolled identity match and passed decision checks.
The response does not say whether OTP was supplied or valid.

Example for a wrong or expired supplied OTP:

```json
{
  "decision": "deny",
  "reason": "otp_failed",
  "scores": {
    "spoof": 0.97,
    "similarity": 96.4,
    "sharpness": 78.0
  },
  "elapsed_ms": 640
}
```

Example for a live, good-quality stranger who does not match the collection:

```json
{
  "decision": "deny",
  "reason": "identity_mismatch",
  "scores": {
    "spoof": 0.97,
    "similarity": 0.0,
    "sharpness": 78.0
  },
  "elapsed_ms": 640
}
```

These are illustrative dummy values. Scores are not calibrated accuracy
guarantees. For the visit-table fields and configuration, see
[`README.md`](./README.md).
