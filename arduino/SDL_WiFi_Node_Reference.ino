/* SDL CORE 10 Wi-Fi node — EXAMPLE, NOT HARDWARE-VERIFIED.
   Arduino ESP32 core; no third-party packages. Wi-Fi STA only, TCP server 8766.
   Gateway protocol: SDL-NDJSON/1; not compatible with historic SDL ASCII/TCP.
   Demonstrates physical ADC reading on GPIO32 (3.3 V MAX; do not wire 5 V).
   IMPORTANT: GPIO32 is also SCL on the original ATOM Matrix Grove port:
   do NOT attach an I2C scale at the same time as this ADC example.
*/
#include <Arduino.h>
#include <WiFi.h>

static const char* WIFI_SSID = "CHANGE_ME";
static const char* WIFI_PASS = "CHANGE_ME";
static const uint16_t PORT = 8766;
static const int ADC_PIN = 32;
static WiFiServer server(PORT);
static String bootId;
static uint32_t seq = 0;
static uint32_t lastSend = 0;
static String receiveLine;
static WiFiClient active;

uint32_t checksum(const String& text) {
  uint32_t crc = 0xFFFFFFFFUL;
  for (size_t i = 0; i < text.length(); ++i) {
    crc ^= (uint8_t)text[i];
    for (int k=0;k<8;++k) crc = (crc>>1) ^ ((crc & 1) ? 0xEDB88320UL : 0UL);
  }
  return crc ^ 0xFFFFFFFFUL;
}
void writeFrame(const String& body) {
  if (!active || !active.connected()) return;
  char hex[9]; snprintf(hex,sizeof(hex),"%08lx",(unsigned long)checksum(body));
  active.print("{\"body\":"); active.print(body);
  active.print(",\"crc32\":\""); active.print(hex); active.println("\"}");
}
void emitHello() {
  String b = "{\"boot_id\":\""+bootId+"\",\"node\":\"esp32-wifi-01\",\"protocol\":\"SDL-NDJSON/1\",\"rssi_dbm\":"+String(WiFi.RSSI())+",\"simulated\":false,\"type\":\"hello\"}";
  writeFrame(b);
}
void emitSample() {
  ++seq;
  // Lexicographically sorted JSON keys and integer values exactly match Python canonical_bytes().
  String b = "{\"boot_id\":\""+bootId+"\",\"channel\":\"adc32\",\"experiment\":\"measure\",\"mono_ms\":"+String(millis())+
    ",\"node\":\"esp32-wifi-01\",\"period_ms\":500,\"protocol\":\"SDL-NDJSON/1\",\"rssi_dbm\":"+String(WiFi.RSSI())+
    ",\"seq\":"+String(seq)+",\"simulated\":false,\"type\":\"sample\",\"unit\":\"ADC counts\",\"x\":"+String(seq)+",\"y\":"+String(analogRead(ADC_PIN))+"}";
  writeFrame(b);
}
String extractId(const String &line) {  // Minimal response for ASCII UUID-shaped ping id
  int p=line.indexOf("\"id\":\""); if (p<0) return "";
  p+=6; int end=line.indexOf('"',p); if(end<0 || end-p>80)return "";
  return line.substring(p,end);
}
void handleCommand(const String &line) {
  if(line.indexOf("\"type\":\"ping\"") >= 0) {
    String id=extractId(line);
    if(id.length())writeFrame("{\"id\":\""+id+"\",\"mono_ms\":"+String(millis())+",\"type\":\"pong\"}");
  }
  // Real hardware never accepts select_experiment, actuation or remote commands in this demo.
}
void setup() {
  Serial.begin(115200); delay(200);
  bootId = String((uint32_t)esp_random(),HEX);
  pinMode(ADC_PIN, INPUT);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID,WIFI_PASS);
  Serial.print("Connecting to existing Wi-Fi router");
  uint32_t started=millis();
  while(WiFi.status()!=WL_CONNECTED && millis()-started<20000){delay(300);Serial.print('.');}
  if(WiFi.status()==WL_CONNECTED){server.begin();Serial.println();Serial.println(WiFi.localIP());}
}
void loop() {
  if(WiFi.status()!=WL_CONNECTED){
    if(active)active.stop();
    static uint32_t lastRetry=0;
    if(millis()-lastRetry>5000){WiFi.reconnect();lastRetry=millis();}
    delay(100);return;
  }
  if(!active || !active.connected()) {
    WiFiClient incoming=server.available();
    if(incoming){active=incoming;active.setNoDelay(true);receiveLine="";emitHello();}
  }
  if(active && active.connected()) {
    while(active.available()) {
      char c=(char)active.read();
      if(c=='\n') {handleCommand(receiveLine);receiveLine="";}
      else if(c!='\r'&&receiveLine.length()<256)receiveLine+=c;
    }
    if(millis()-lastSend>=500){lastSend=millis();emitSample();}
  }
  delay(3);
}
