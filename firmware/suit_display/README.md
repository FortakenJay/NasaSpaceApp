# Suit display firmware (ESP32 + Waveshare 7.5" e-paper)

The planner draws the whole screen; this board only downloads it and puts it on the glass, once a minute.

1. Wire nothing: the **Waveshare Universal e-Paper Driver Board (ESP32)** takes the 7.5" panel's ribbon directly.
2. Arduino IDE: board **ESP32 Dev Module**; install **GxEPD2** and **Adafruit GFX** from the Library Manager.
3. In `suit_display.ino`, set `WIFI_SSID`, `WIFI_PASS` and `PLANNER` (the IP of the computer running the planner).
4. On that computer: `marswalk serve --host 0.0.0.0`, then plan a walk in the app. The board always shows the latest plan.
5. Flash. Press **RESET** when the walk starts: mission time counts from power-on. `TIME_SCALE = 30` replays a
   3.5 h walk in 7 minutes for a demo.

The panel class is `GxEPD2_750_T7` (7.5" V2, 800 x 480). If your panel is a different 7.5" variant, pick the
matching class from GxEPD2's examples; the image is always 800 x 480.

Format of `/api/eink.bin`: 48 000 bytes, rows top to bottom, 8 pixels per byte, most significant bit first,
bit set = black (what `drawBitmap(..., GxEPD_BLACK)` expects).
