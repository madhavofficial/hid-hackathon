# HID Hackathon

Build a laptop kiosk that decides, in under 2 seconds, whether the person at the camera is really here and is someone who is allowed in.

This file is the brief. The four of us do not share a chat. Read your section, then stay inside your folder.

## What the judges want

An HID entry kiosk. The same face can be a live person, a printed photo, a phone screen, a video, or a mask. Looking like the right person is not enough. The system has to pass both checks:

1. Liveness. A real person is in front of the camera.
2. Identity. That person is enrolled.

Then it picks one door:

| Decision | When | Example |
|---|---|---|
| `allow` | Live, and the face matches an enrolled person | Alice, clear light, natural movement |
| `ask_again` | The picture is too weak to trust | Alice backlit, face too small, sharpness low |
| `deny` | Spoof, or a live person who is not enrolled | Photo of Alice, or live Bob |

Demonstrate at least two spoof types. For each scenario report how often the decision was right, how often a fake was allowed, how often a real enrolled person was denied, and how long the decision took. The limit is 2 seconds.

## How a visit works

```text
Person
  -> kiosk grabs 2 or 3 JPEGs
  -> POST /check
  -> decision service runs the checks at the same time
  -> allow, deny, or ask_again
  -> one DynamoDB row
  -> scoreboard
```

Alice in normal light is Allow. A phone playing a video of Alice can still match her face, and must be Deny. Live Bob is Deny because he is not enrolled. A dark or blurry Alice is Ask again, then a blink or a code. Do not guess on a bad frame.

The colored-light Face Liveness check and a SageMaker GPU endpoint are not on this path. Use them only if a mask or a hard video gets through the CPU checks during testing.

## Shared contract

`contract/check.example.json` is the payload. Do not invent a second endpoint.

```json
POST /check
{
  "frames": ["<jpeg base64>", "<jpeg base64>"],
  "otp": null
}
```

```json
{
  "decision": "allow",
  "reason": "live_and_match",
  "scores": { "spoof": 0.92, "similarity": 99.1, "sharpness": 80 },
  "elapsed_ms": 640
}
```

`decision` is `allow`, `deny`, or `ask_again`.

`frames` is 2 or 3 JPEG base64 strings, about 480×640, captured about 150 ms apart. A blink retry sends two frames: eyes closed, then eyes open. An OTP retry sends the latest frame plus `otp`.

`reason` is a short string such as `live_and_match`, `spoof`, `identity_mismatch`, `low_quality`, or `otp_failed`.

`scores.spoof` is the local model, higher means more live. `scores.similarity` is the Rekognition match, 0–100. `scores.sharpness` is DetectFaces quality. `elapsed_ms` is the decision-service time, not the time the person spent posing.

If this JSON has to change, that change is its own small pull request into `main` before anyone else builds on it.

## Where the code runs

Write code on your laptop. Push to your branch. The AWS account is only the shared runtime: Rekognition, S3, DynamoDB, SNS, and Cognito.

One account for the demo, so there is one face collection and one visit log.

| | |
|---|---|
| Account | `533267095467` |
| Region | `us-east-1` |
| Role | `WSParticipantRole` |
| Credentials | Workshop Studio → Get AWS CLI credentials. Put them in a local `.env`. Never commit that file. |

From a laptop in India, measured on the challenge poster resized to 640 px:

| Call | Time |
|---|---|
| DetectFaces | about 1.0–1.3 s |
| SearchFacesByImage | about 0.45–0.49 s |
| Both at once | about 0.5–0.7 s |

A service running in Virginia will be faster. The parallel number is the slower call, not the sum. Rekognition's Python client is blocking, so use a thread pool. A plain async gather will still run the calls one after another.

These sandbox limits are already checked. Do not spend the day re-requesting quotas.

| Resource | Limit | What to do |
|---|---|---|
| EC2 G and P vCPUs, including g4, g5, g6, p3, p4, p5 | 0 | Do not launch GPU virtual machines |
| Standard EC2 vCPUs | 256 | A small always-on CPU box is fine |
| SageMaker `ml.g4dn.xlarge` or `ml.g5.xlarge` endpoint | 2 | Spare only, after a CPU test misses a spoof |
| SageMaker p4 and p5 | 0 | Do not use |
| Cognito identity pool | Allowed | Created and deleted in a test |
| `CreateFaceLivenessSession` | Allowed | Returned a session |

## Branches

Same repo, one branch each. Do not commit straight to `main`.

| Person | Branch | Folder |
|---|---|---|
| 1 | `kiosk` | `kiosk/` |
| 2 | `decision` | `decision/` |
| 3 | `identity` | `identity/` |
| 4 | `scoreboard` | `scoreboard/` |

```bash
git clone https://github.com/madhavofficial/hid-hackathon.git
cd hid-hackathon
git checkout kiosk
```

Only change files in your folder, plus `contract/` when the payload itself changes. Open a pull request into `main` when your "done when" line is true. Everyone else pulls `main` after it merges.

## Person 1, kiosk

Done when a button sends one payload and the page shows Allow, Deny, or Ask again.

Build a page that uses the laptop camera.

- Grab 2 or 3 JPEGs at about 480×640, about 150 ms apart. Downscale in the browser before sending. Three frames are about 120 KB.
- Use MediaPipe Face Landmarker in the page for face position, pose, and blink. The person should see that feedback immediately. Do not send every video frame to AWS.
- `POST /check` with `frames` and `otp: null`.
- Render the returned `decision`. Allow, Deny, and Ask again are three different screens.
- On Ask again, offer a recapture, a blink, or a code. A blink sends a second `/check` whose frames are eyes-closed then eyes-open. A code sends `otp` plus the latest frame.

You can point at a mock that returns `ask_again` until Person 2's service is up. Stay in `kiosk/`.

## Person 2, decision service

Done when a real payload returns in under 2 seconds with scores and `elapsed_ms`.

Build one warm CPU process. A container Lambda is fine only if it stays warm. A cold start can spend the whole 2 seconds before the model runs. A small EC2 instance or App Runner in `us-east-1` is the safer demo host. Standard EC2 quota is 256 vCPUs.

On each request:

1. Pick the sharpest frame locally, for example with a Laplacian variance. Do this before Rekognition.
2. In a thread pool, at the same time:
   - MiniFASNet, or a similar small ONNX anti-spoof model, on that frame. Higher score means more live.
   - Rekognition `DetectFaces` once, with quality attributes. Read sharpness, brightness, pose, and whether the eyes are open.
   - Rekognition `SearchFacesByImage` once, against the collection id Person 3 gives you. Read similarity, 0–100.
3. Compare the 2 or 3 frames yourself for motion. A printed photo and a phone screen are flat and barely change. MiniFASNet scores one crop. It does not see that motion.
4. Apply the rules:
   - Low sharpness, no face, or a tiny face → `ask_again`, reason `low_quality`. Do not call that a spoof.
   - Spoof score low, or almost no motion on a face that matches someone → `deny`, reason `spoof`.
   - Live score high and similarity high → `allow`, reason `live_and_match`.
   - Live score high and no match → `deny`, reason `identity_mismatch`.
   - Blink retry: one frame with eyes closed and a later frame with eyes open, confirmed by `EyesOpen`, can clear an `ask_again`.
   - OTP retry: Person 3's check passes or fails.
5. Write one DynamoDB item: decision, reason, scores, `elapsed_ms`, and a spoof label if the caller sent one. Person 4 reads this table. Agree the table name in the first hour and put it in your README.

Call DetectFaces once and SearchFacesByImage once per request. Do not call them once per frame.

Leave the SageMaker GPU endpoint off unless Person 4 shows a mask or a video replay getting `allow`.

## Person 3, identity and step-up

Done when an enrolled person can be allowed, a stranger is denied, and Ask again can require a blink or a code.

Do this first, before Person 2 can return a real Allow:

- Create one Rekognition collection in `us-east-1`.
- Put each enrolled photo in S3.
- `IndexFaces` into that collection. External image id is the person id.
- Give Person 2 the collection id. One enrolled face is enough to unblock them. Add the rest after.

Then the step-up:

- SMS one-time code through Amazon SNS. Store the code long enough to check the next `/check`. Person 2 calls you, or you expose a tiny verify function. A wrong or missing code is `deny` with reason `otp_failed` only after they were asked. A missing code on the first visit is not a failure.
- Blink is Person 1's camera plus Person 2's `EyesOpen` check. You do not build a second blink model.

Later, only after blink and SMS work: Rekognition Face Liveness. `CreateFaceLivenessSession` is allowed, and creating a Cognito identity pool is allowed. The Amplify Face Liveness component needs that pool so the browser can stream the colored-light check. Wire it only if a mask or a hard video still gets through. Take the reference image from the liveness result and run `SearchFacesByImage` on that image, not on an older frame.

Do not launch a GPU instance.

## Person 4, scoreboard

Done when the pitch view shows detection rate, false accepts, false rejects, and average decision time for at least two spoof types.

Read Person 2's DynamoDB items. Each run needs a label:

- `live`
- `printed_photo`
- `screen_replay`
- `video_replay`
- `mask`

Add the label in the client or with a button on your view. Record failures too.

For each label show:

- Detection rate. Correct decisions divided by attempts.
- False accepts. A spoof or the wrong person got `allow`.
- False rejects. A live enrolled person got `deny`.
- Average `elapsed_ms`. This must stay under 2 seconds.

`ask_again` on a blurry live person is a correct low-quality path, not a false reject. `allow` on a printed photo is a false accept even if the face matches.

The demo must include at least two of printed photo, screen, video, and mask. Run those against the real `/check` service and keep the numbers. If a mask or a video is allowed, tell Person 2. That is the only signal to turn on Face Liveness or one `ml.g4dn.xlarge` / `ml.g5.xlarge` endpoint.

## First hour

1. Person 3 creates the collection, enrolls one face, and sends the collection id.
2. Person 2 stands up `POST /check` and writes one DynamoDB row, even if the spoof model is still a stub.
3. Person 1 sends the real camera payload to that URL.
4. Person 4 records every response from the start.

The GPU endpoint stays off.
