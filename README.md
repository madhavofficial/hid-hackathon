# HID Hackathon

Face liveness kiosk. One sandbox account, four folders, one request.

| Folder | Who | Done when |
|---|---|---|
| `kiosk/` | Person 1 | A button sends one payload and shows Allow, Deny, or Ask again |
| `decision/` | Person 2 | That payload returns in under 2 seconds with scores and milliseconds |
| `identity/` | Person 3 | An enrolled person can be allowed, a stranger is denied, and Ask again can require a blink or a code |
| `scoreboard/` | Person 4 | The pitch view shows detection rate, false accepts, false rejects, and average time for at least two spoof types |

The request and response live in `contract/check.example.json`.

Person 3 enrolls one real face first and gives Person 2 the Rekognition collection id. Person 4 records every call, including failures. The SageMaker GPU endpoint stays unused unless a mask or a video gets past the CPU check.
