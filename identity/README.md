# Identity and step-up

Enroll real people: photo in S3, face in one Rekognition collection, `IndexFaces`. Hand the collection id to the decision service.

Ask again is a blink confirmed with DetectFaces, or an SNS code. Cognito and Face Liveness are the later path for a mask or a hard video, after blink and the code already work.
