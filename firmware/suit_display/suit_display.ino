// MarsWalk suit display: an ESP32 + Waveshare 7.5" e-paper (800 x 480, black/white) that shows the walk like a
// car navigation screen. It downloads the finished picture from the MarsWalk planner (/api/eink.bin: 48 000 bytes,
// 1 bit per pixel, most significant bit first, 1 = black) and draws it. All the maths stays on the planner.
//
// Hardware: Waveshare Universal e-Paper Driver Board (ESP32) + 7.5" V2 raw panel (GxEPD2_750_T7).
//   Other 7.5" variants: change the display class below (GxEPD2_750 for the old 640 x 384 panel will NOT fit).
// Libraries (Arduino Library Manager): GxEPD2 by Jean-Marc Zingg, Adafruit GFX. Board: "ESP32 Dev Module".
// The planner must listen on the network: `marswalk serve --host 0.0.0.0`, and this board must reach that computer.

#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <GxEPD2_BW.h>

// ---- settings --------------------------------------------------------------------------------------------
const char* WIFI_SSID = "your-network";
const char* WIFI_PASS = "your-password";
const char* PLANNER   = "http://192.168.1.20:8000";   // the computer running `marswalk serve --host 0.0.0.0`
const uint32_t REFRESH_S = 60;                          // e-paper: one full refresh a minute is plenty
// Mission time: counted from power-on (press RESET when leaving the rover). For a replay, set a speed-up.
const float TIME_SCALE = 1.0;                           // e.g. 30.0 plays a 3.5 h walk in 7 minutes

// Waveshare ESP32 driver board wiring: CS 15, DC 27, RST 26, BUSY 25; SPI on SCK 13, MOSI 14.
GxEPD2_BW<GxEPD2_750_T7, GxEPD2_750_T7::HEIGHT> display(GxEPD2_750_T7(/*CS=*/15, /*DC=*/27, /*RST=*/26, /*BUSY=*/25));
SPIClass hspi(HSPI);

static const int W = 800, H = 480;
static uint8_t frame[W * H / 8];

static void message(const char* line1, const char* line2) {
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    display.setTextColor(GxEPD_BLACK);
    display.setTextSize(3);
    display.setCursor(30, 200);
    display.print(line1);
    display.setTextSize(2);
    display.setCursor(30, 250);
    display.print(line2);
  } while (display.nextPage());
}

static bool download(float elapsed_h) {
  HTTPClient http;
  String url = String(PLANNER) + "/api/eink.bin?elapsed_h=" + String(elapsed_h, 3);
  http.setTimeout(20000);                                // the first request after a restart can take ~15 s
  if (!http.begin(url)) return false;
  int code = http.GET();
  if (code != 200) {
    http.end();
    return false;
  }
  WiFiClient* s = http.getStreamPtr();
  size_t got = 0;
  uint32_t t0 = millis();
  while (got < sizeof(frame) && millis() - t0 < 20000) {
    int n = s->readBytes(frame + got, sizeof(frame) - got);
    if (n <= 0) delay(10);
    got += n > 0 ? n : 0;
  }
  http.end();
  return got == sizeof(frame);
}

void setup() {
  Serial.begin(115200);
  hspi.begin(13, 12, 14, 15);                            // remap SPI to the driver board's pins
  display.epd2.selectSPI(hspi, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  display.init(115200);
  display.setRotation(0);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(500);
  if (WiFi.status() != WL_CONNECTED) message("No Wi-Fi", WIFI_SSID);
}

void loop() {
  float elapsed_h = TIME_SCALE * millis() / 3600000.0f;
  if (WiFi.status() == WL_CONNECTED && download(elapsed_h)) {
    display.setFullWindow();
    display.firstPage();
    do {
      display.fillScreen(GxEPD_WHITE);
      display.drawBitmap(0, 0, frame, W, H, GxEPD_BLACK);  // set bits are black
    } while (display.nextPage());
  } else {
    Serial.println("planner not reachable; keeping the last screen");
  }
  display.hibernate();
  delay(REFRESH_S * 1000UL);
}
