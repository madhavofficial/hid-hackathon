# Identity and step-up

The full brief is in the root README, section "Person 3, identity and step-up".

Run these from the repo root, with AWS credentials in the environment or in `.env`.

```bash
python -m identity.enroll setup
python -m identity.enroll add alice photos/alice.jpg --phone +919876543210
python -m identity.enroll list
python -m identity.otp send --person-id alice
python -m identity.otp verify 123456 --person-id alice
```

Hand this to Person 2:

| | |
|---|---|
| Collection id | `hid-faces` (or `REKOGNITION_COLLECTION_ID`) |
| S3 bucket | `hid-hackathon-enrolled-533267095467` |
| Person id | The `person_id` passed to `add`. That is the Rekognition `ExternalImageId`. |
| OTP check | `verify_otp(otp, person_id)` returns `True` (`valid`) or `False` (`invalid`). |

`person_id` has no default. Person 2 must pass the id returned by `SearchFacesByImage`. Do not call `verify_otp` when the visitor was not asked for a code. A DynamoDB failure raises. It does not look like a wrong code.

Enrolling the same person again replaces the previous face. `remove` deletes the face, the S3 photo, and the stored phone.

The SMS code is not returned to the caller. If SNS cannot send, the stored code is deleted and the error is raised. The colored-light check still needs the kiosk Cognito wiring. It is not part of this step.
