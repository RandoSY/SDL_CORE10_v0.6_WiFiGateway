/* Original ATOM Matrix / MPU6886 SDL-NDJSON/1 bench node.
 * GPIO27: low-brightness matrix; GPIO39: button; internal IMU: SDA25/SCL21.
 * Reuses saved station configuration; never prints credentials, creates an AP,
 * scans Grove, or changes the external GPIO32 ADC/I2C wiring.
 * This is separate from the earlier hardware diagnostic and generic ADC sketch.
 */
#include <Arduino.h>
#include <Adafruit_NeoPixel.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_wifi.h>
#include <math.h>
#include <SPIFFS.h>
#include <esp_partition.h>
#include <atomic>
#include "matrix_status.h"
#if __has_include("wifi_config.local.h")
#include "wifi_config.local.h"
#else
static const char* NODE_WIFI_SSID = "";
static const char* NODE_WIFI_PASSWORD = "";
#endif

static constexpr uint8_t LED_BRIGHTNESS = 20;
static constexpr uint32_t ACQUIRE_MS = 20, TELEMETRY_MS = 20, RETRY_MS = 20000;
static constexpr uint16_t TCP_PORT = 8766;
Adafruit_NeoPixel pixels(25, 27, NEO_GRB + NEO_KHZ800);
WiFiServer node(TCP_PORT);
WiFiClient peer;
sdl::Status status;
String bootId, command;
bool serverStarted = false, discarding = false, imuPresent = false;
bool buttonCandidate = false;
uint32_t buttonChangedAt = 0, presses = 0, seq = 0, txSamples = 0, errors = 0;
uint32_t acquiredAt = 0, ledAt = 0, printedAt = 0, retryAt = 0;
int32_t axMg = 0, ayMg = 0, azMg = 0, magnitudeMg = 0;
struct Reading {
  uint32_t at, sequence;
  int32_t ax, ay, az, magnitude;
  bool valid;
};
QueueHandle_t readings = nullptr;
std::atomic<uint32_t> samplerSkipped{0}, queueDropped{0}, acquireMaxUs{0};
uint32_t networkMaxUs = 0, sampleMaxUs = 0, displayMaxUs = 0;
int32_t cachedRSSI = -130;
uint32_t rssiAt = 0;

bool readRegisters(uint8_t reg, uint8_t* data, uint8_t count) {
  Wire.beginTransmission(0x68);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(uint8_t(0x68), count, uint8_t(true)) != count) return false;
  for (uint8_t i = 0; i < count; ++i) data[i] = Wire.read();
  return true;
}
bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(0x68);
  Wire.write(reg); Wire.write(value);
  return Wire.endTransmission(true) == 0;
}
bool initIMU() {
  uint8_t id = 0;
  if (!readRegisters(0x75, &id, 1) || id != 0x19) return false;
  if (!writeRegister(0x6B, 1)) return false;
  delay(20); // Sensor wake-up only; display/network scheduling does not sleep.
  return writeRegister(0x1B, 0) && writeRegister(0x1C, 0) && writeRegister(0x1A, 3);
}
int16_t signed16(const uint8_t* p) {
  return int16_t((uint16_t(p[0]) << 8) | p[1]);
}
void acquisitionTask(void*) {
  const TickType_t period = pdMS_TO_TICKS(ACQUIRE_MS);
  TickType_t wake = xTaskGetTickCount();
  uint32_t sequence = 0;
  for (;;) {
    vTaskDelayUntil(&wake, period);
    const TickType_t late = xTaskGetTickCount() - wake;
    if (late >= period) {
      const uint32_t skipped = late / period;
      wake += skipped * period;
      sequence += skipped;
      samplerSkipped.fetch_add(skipped, std::memory_order_relaxed);
    }
    Reading r = {};
    r.at = millis(); r.sequence = ++sequence;
    uint8_t data[6];
    const uint32_t start = micros();
    r.valid = imuPresent && readRegisters(0x3B, data, 6);
    const uint32_t cost = micros() - start;
    if (cost > acquireMaxUs.load(std::memory_order_relaxed)) acquireMaxUs.store(cost, std::memory_order_relaxed);
    if (r.valid) {
      const float ax = signed16(data) / 16384.0f, ay = signed16(data + 2) / 16384.0f, az = signed16(data + 4) / 16384.0f;
      r.ax = lroundf(ax * 1000); r.ay = lroundf(ay * 1000); r.az = lroundf(az * 1000);
      r.magnitude = lroundf(sqrtf(ax*ax + ay*ay + az*az) * 1000);
    }
    if (xQueueSend(readings, &r, 0) != pdTRUE) queueDropped.fetch_add(1, std::memory_order_relaxed);
  }
}
void errorPulse() {
  ++errors;
  status.sawError = true;
  status.errorAt = millis();
}
uint32_t crc32(const String& body) {
  uint32_t crc = 0xFFFFFFFF;
  for (size_t i = 0; i < body.length(); ++i) {
    crc ^= uint8_t(body[i]);
    for (uint8_t bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ ((crc & 1) ? 0xEDB88320 : 0);
  }
  return crc ^ 0xFFFFFFFF;
}
bool sendBody(const String& body) {
  if (!peer || !peer.connected()) return false;
  char checksum[9];
  snprintf(checksum, sizeof(checksum), "%08lx", (unsigned long)crc32(body));
  const String frame = "{\"body\":" + body + ",\"crc32\":\"" + checksum + "\"}\n";
  if (peer.write(reinterpret_cast<const uint8_t*>(frame.c_str()), frame.length()) != frame.length()) {
    errorPulse();
    peer.stop();
    status.peer = status.sawPing = status.sentSample = false;
    return false;
  }
  return true;
}
void sendHello() {
  // Keys are sorted; all JSON numbers are integers for stable canonical CRCs.
  sendBody("{\"boot_id\":\"" + bootId + "\",\"node\":\"atom-matrix-imu\",\"protocol\":\"SDL-NDJSON/1\",\"rssi_dbm\":"
    + String(WiFi.RSSI()) + ",\"simulated\":false,\"type\":\"hello\"}");
}
void sample(uint32_t now) {
  if (!readings) return;
  if (status.wifi && uint32_t(now - rssiAt) >= 1000) { cachedRSSI = WiFi.RSSI(); rssiAt = now; }
  Reading r;
  for (uint8_t count = 0; count < 8 && xQueueReceive(readings, &r, 0) == pdTRUE; ++count) {
  acquiredAt = r.at; seq = r.sequence; status.sensorOk = r.valid;
  axMg = r.ax; ayMg = r.ay; azMg = r.az; magnitudeMg = r.magnitude;
  if (!r.valid || !peer || !peer.connected()) continue;
  // x is the actual acquisition timestamp in milliseconds, y is magnitude in mg.
  const String body = "{\"boot_id\":\"" + bootId + "\",\"channel\":\"acceleration_magnitude\",\"mono_ms\":"
    + String(acquiredAt) + ",\"period_ms\":" + String(TELEMETRY_MS) + ",\"protocol\":\"SDL-NDJSON/1\",\"rssi_dbm\":" + String(cachedRSSI)
    + ",\"seq\":" + String(seq) + ",\"simulated\":false,\"type\":\"sample\",\"unit\":\"mg\",\"x\":"
    + String(acquiredAt) + ",\"y\":" + String(magnitudeMg) + "}";
  if (sendBody(body)) {
    ++txSamples;
    status.sentSample = true;
    status.sampleAt = millis(); // Successful local write, not a gateway acceptance ACK.
  }
  }
}
void handleCommand(const String& line) {
  // The Python gateway emits compact JSON with ASCII UUID ping IDs. Accept only
  // that narrow read-only request; never reflect unchecked bytes into JSON.
  if (line.indexOf("\"type\":\"ping\"") < 0) return;
  int start = line.indexOf("\"id\":\"");
  if (start < 0) { errorPulse(); return; }
  start += 6;
  const int end = line.indexOf('"', start);
  if (end <= start || end - start > 80) { errorPulse(); return; }
  const String id = line.substring(start, end);
  for (size_t i = 0; i < id.length(); ++i) {
    const char c = id[i];
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '-')) {
      errorPulse(); return;
    }
  }
  if (sendBody("{\"id\":\"" + id + "\",\"mono_ms\":" + String(millis()) + ",\"type\":\"pong\"}")) {
    status.sawPing = true;
    status.pingAt = millis();
  }
}
void network(uint32_t now) {
  status.wifi = WiFi.status() == WL_CONNECTED;
  if (!status.wifi) {
    if (peer) peer.stop();
    if (serverStarted) { node.end(); serverStarted = false; }
    status.peer = status.sawPing = status.sentSample = false;
    command = ""; discarding = false;
    if (status.configured && uint32_t(now - retryAt) >= RETRY_MS) {
      retryAt = now;
      WiFi.reconnect();
    }
    return;
  }
  if (!serverStarted) {
    node.begin();
    serverStarted = true;
    Serial.printf("[WIFI] READY IP=%s TCP=%u\n", WiFi.localIP().toString().c_str(), TCP_PORT);
  }
  if (!peer || !peer.connected()) {
    status.sawPing = status.sentSample = false;
    WiFiClient incoming = node.accept();
    if (incoming) {
      peer.stop(); peer = incoming; peer.setNoDelay(true); peer.setTimeout(1);
      command = ""; discarding = false;
      sendHello();
    }
  }
  status.peer = peer && peer.connected();
  // Bound work per loop so incoming traffic cannot monopolize matrix/IMU updates.
  for (uint16_t count = 0; status.peer && count < 256 && peer.available(); ++count) {
    const char c = char(peer.read());
    if (c == '\n') {
      if (!discarding) handleCommand(command);
      command = ""; discarding = false;
    } else if (c != '\r' && !discarding) {
      if (command.length() >= 256) { command = ""; discarding = true; errorPulse(); }
      else command += c;
    }
  }
  status.peer = peer && peer.connected();
}
void button(uint32_t now) {
  const bool down = digitalRead(39) == LOW;
  if (down != buttonCandidate) { buttonCandidate = down; buttonChangedAt = now; }
  if (down != status.button && uint32_t(now - buttonChangedAt) >= 30) {
    status.button = down;
    if (down) ++presses;
  }
}
void display(uint32_t now) {
  if (uint32_t(now - ledAt) < 50) return;
  ledAt = now;
  status.now = now;
  if (now >= 500) status.booting = false; // Do not re-enter boot after millis wraps.
  const sdl::Matrix image = sdl::render(status);
  static sdl::Matrix previous;
  if (memcmp(image.pixel, previous.pixel, sizeof(image.pixel)) == 0) return;
  for (uint8_t i = 0; i < 25; ++i) pixels.setPixelColor(i, image.pixel[i]);
  pixels.show();
  previous = image;
}
void printStatus() {
  Serial.printf("[SDL-NODE] matrix=%s IMU=%s a_mg=(%ld,%ld,%ld) norm_mg=%ld presses=%lu WiFi=%s IP=%s peer=%u tx=%lu seq=%lu errors=%lu heap=%lu\n",
    sdl::name(sdl::phase(status)), status.sensorOk ? "PASS" : "FAIL",
    (long)axMg, (long)ayMg, (long)azMg, (long)magnitudeMg, (unsigned long)presses,
    status.wifi ? "ONLINE" : status.configured ? "JOINING" : "UNCONFIGURED",
    WiFi.localIP().toString().c_str(), status.peer, (unsigned long)txSamples,
    (unsigned long)seq, (unsigned long)errors, (unsigned long)ESP.getFreeHeap());
  Serial.printf("[TIMING] sampler_skipped=%lu queue_dropped=%lu queued=%u acquire_max_us=%lu network_max_us=%lu sample_max_us=%lu display_max_us=%lu\n",
    (unsigned long)samplerSkipped.load(), (unsigned long)queueDropped.load(), readings ? (unsigned)uxQueueMessagesWaiting(readings) : 0,
    (unsigned long)acquireMaxUs.load(), (unsigned long)networkMaxUs, (unsigned long)sampleMaxUs, (unsigned long)displayMaxUs);
}
void printStorage() {
  for (auto it = esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, nullptr);
       it != nullptr; it = esp_partition_next(it)) {
    const auto* p = esp_partition_get(it);
    Serial.printf("[FLASH] %s offset=0x%06lx size=0x%06lx\n", p->label,
      (unsigned long)p->address, (unsigned long)p->size);
  }
  if (!SPIFFS.begin(false)) {
    Serial.println("[FILES] SPIFFS not mountable; no format attempted, file list unavailable.");
    return;
  }
  File root = SPIFFS.open("/");
  unsigned count = 0;
  for (File file = root.openNextFile(); file && count < 100; file = root.openNextFile()) {
    Serial.printf("[FILE] %s bytes=%lu\n", file.path(), (unsigned long)file.size());
    ++count;
  }
  Serial.printf("[FILES] listed=%u used=%lu total=%lu%s\n", count,
    (unsigned long)SPIFFS.usedBytes(), (unsigned long)SPIFFS.totalBytes(), count == 100 ? " (listing capped)" : "");
  root.close(); SPIFFS.end();
}
void setup() {
  Serial.begin(115200);
  pinMode(39, INPUT); // Input-only pin; the board provides the pull-up.
  pixels.begin(); pixels.setBrightness(LED_BRIGHTNESS);
  status.booting = true; status.now = millis();
  const sdl::Matrix boot = sdl::render(status);
  for (uint8_t i = 0; i < 25; ++i) pixels.setPixelColor(i, boot.pixel[i]);
  pixels.show();
  Serial.println("\nSDL ATOM IMU Gateway Node 0.6.4; FreeRTOS sampler=50Hz; matrix brightness=20");
  bootId = String(uint32_t(esp_random()), HEX);
  command.reserve(256);
  Wire.begin(25, 21, 100000); Wire.setTimeOut(40);
  imuPresent = initIMU();
  readings = xQueueCreate(128, sizeof(Reading));
  if (!readings || xTaskCreatePinnedToCore(acquisitionTask, "sdl_acquire", 4096, nullptr, 2, nullptr, 1) != pdPASS) {
    if (readings) { vQueueDelete(readings); readings = nullptr; }
    Serial.println("[IMU] Sampler task allocation failed.");
  }
  WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.setAutoReconnect(true);
  wifi_config_t saved = {};
  status.configured = esp_wifi_get_config(WIFI_IF_STA, &saved) == ESP_OK && saved.sta.ssid[0] != 0;
  // Do not print or retain credential contents in application buffers.
  memset(&saved, 0, sizeof(saved));
  if (NODE_WIFI_SSID[0]) {
    WiFi.persistent(true);
    status.configured = true;
    WiFi.begin(NODE_WIFI_SSID, NODE_WIFI_PASSWORD);
  }
  else if (status.configured) WiFi.begin();
  else Serial.println("[WIFI] No saved station configuration; amber corner markers, USB diagnostics available.");
}
void loop() {
  const uint32_t now = millis();
  button(now);
  uint32_t start = micros();
  network(now);
  networkMaxUs = max(networkMaxUs, uint32_t(micros() - start));
  start = micros();
  sample(now);
  sampleMaxUs = max(sampleMaxUs, uint32_t(micros() - start));
  start = micros();
  display(millis());
  displayMaxUs = max(displayMaxUs, uint32_t(micros() - start));
  while (Serial.available()) {
    const char c = char(Serial.read());
    if (c == 's' || c == 'i' || c == 'w') printStatus();
    else if (c == 'f') printStorage();
    else if (c == 'h' || c == '?') Serial.println("s/i/w: status; f: flash/file inventory without format; matrix follows real state.");
  }
  if (uint32_t(now - printedAt) >= 5000) { printedAt = now; printStatus(); }
  delay(1);
}
