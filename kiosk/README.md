# Kiosk

Laptop camera. Capture 2 or 3 frames at about 480×640, roughly 150 ms apart. MediaPipe handles pose and blink on the page. Send one `POST /check` body from `contract/check.example.json` and render `allow`, `deny`, or `ask_again`.
