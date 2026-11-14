# Decision service

The full brief is in the root README, section "Person 2, decision service".

Warm CPU service. On the sharpest frame, run together:

- MiniFASNet spoof score
- Rekognition DetectFaces, once
- Rekognition SearchFacesByImage, once

Compare the frames locally for motion. Write one DynamoDB row per visit with the decision, scores, milliseconds, and spoof label. `decision` is `allow`, `deny`, or `ask_again`.
