# Identity and step-up

The full brief is in the root README, section "Person 3, identity and step-up".

Run these from the repo root, with AWS credentials in the environment or in `.env`.

```bash
python -m identity.enroll setup
python -m identity.enroll add alice photos/alice.jpg --phone +919876543210
python -m identity.enroll list
python -m identity.otp send --person-id alice
python -m identity.otp verify 123456 --person-id alice
python -m identity.liveness setup
```

Hand this to Person 2:

| | |
|---|---|
| Collection id | `hid-faces` (or `REKOGNITION_COLLECTION_ID`) |
| S3 bucket | `hid-hackathon-enrolled-533267095467` |
| Person id | The `person_id` passed to `add`. That is the Rekognition `ExternalImageId`. |
| OTP check | `verify_otp(otp, person_id)` returns `True` (`valid`) or `False` (`invalid`). |

`person_id` has no default. Person 2 must pass the id returned by `SearchFacesByImage`. Do not call `verify_otp` when the visitor was not asked for a code. A DynamoDB failure raises. It does not look like a wrong code.

Enrolling the same person again indexes the new photo first. The previous face and S3 photo stay if that index fails. On success, the old face and the old photo are removed, including a different file extension. A `.pending` upload is not treated as the saved photo. `remove` deletes the face, the S3 photo, and the stored phone.

`verify_otp` checks that `person_id` is in the `hid-faces` collection before it checks the code. An unknown id raises. A wrong code returns `False`.

If the account is in the SNS SMS sandbox, the destination number must be verified in the SNS console. `otp send` checks that before it stores a code. If this role cannot read sandbox status, the send continues and a failed `sns.publish` still deletes the stored code and raises.

The SMS code is not returned to the caller. Before a code is stored, `otp send` checks the SMS sandbox and the monthly spend limit. A spend limit of 0 is raised to $1 when this role is allowed to do that. If the role cannot read those settings, the send continues. A failed `sns.publish` still deletes the stored code. The error says whether the block was the sandbox, the spend limit, or a missing origination identity.

A photo that fails the AUTO quality bar is indexed once more with the quality filter off. If that also finds no face, the pending upload is deleted and the previous face stays. The error says the previous enrollment is unchanged.

`python -m identity.liveness setup` creates Cognito identity pool `hid_liveness` and guest role `hid-liveness-unauth`, which may call `rekognition:StartFaceLivenessSession`. Hand Person 1 the printed `identity_pool_id` and `us-east-1`. Person 1 still mounts the Amplify camera component.
