# Kiosk

The full brief is in the root README, section "Person 1, kiosk".

The page posts to `/check`. In local development, Vite forwards that path to the decision service at `http://127.0.0.1:8000`. Start the decision service first, then run `npm run dev` in `kiosk/`. Set `VITE_USE_MOCK=true` only when the service is not running. Set `VITE_API_BASE_URL` when the service is not on that local address.

Laptop camera. Capture 2 or 3 frames at about 480×640, roughly 150 ms apart. MediaPipe handles pose and blink on the page. Send one `POST /check` body from `contract/check.example.json` and render `allow`, `deny`, or `ask_again`.
