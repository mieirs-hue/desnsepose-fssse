#include <Arduino.h>
#include <WiFi.h>

#ifndef NODE_ID
#define NODE_ID "A"
#endif

#ifndef NODE_LABEL
#define NODE_LABEL "node_a"
#endif

#ifndef WIFI_SSID
#define WIFI_SSID "OfficeWiFi"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "ChangeMe"
#endif

namespace {

uint32_t lastSampleAt = 0;
bool bootAnnounced = false;

void forceIndicatorsOff() {
#ifdef LED_BUILTIN
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LOW);
#endif
#ifdef RGB_BUILTIN
  pinMode(RGB_BUILTIN, OUTPUT);
  neopixelWrite(RGB_BUILTIN, 0, 0, 0);
#endif
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(1200);
  forceIndicatorsOff();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

void loop() {
  if (!bootAnnounced) {
    Serial.printf(
      "{\"node\":\"%s\",\"label\":\"%s\",\"status\":\"boot\",\"mode\":\"passive_rssi\",\"ssid\":\"%s\"}\n",
      NODE_ID,
      NODE_LABEL,
      WIFI_SSID
    );
    bootAnnounced = true;
  }

  const uint32_t now = millis();
  if (now - lastSampleAt < 100) {
    delay(10);
    return;
  }

  // Keep status LEDs dark while still sampling/reporting data.
  forceIndicatorsOff();

  lastSampleAt = now;
  wl_status_t wifiStatus = WiFi.status();
  int currentRssi = -100;
  if (wifiStatus == WL_CONNECTED) {
    currentRssi = WiFi.RSSI();
  }

  Serial.printf(
    "{\"node\":\"%s\",\"label\":\"%s\",\"mode\":\"passive_rssi\",\"rssi\":%d,\"wifi\":%d,\"timestamp\":%lu}\n",
    NODE_ID,
    NODE_LABEL,
    currentRssi,
    static_cast<int>(wifiStatus),
    static_cast<unsigned long>(now)
  );
}