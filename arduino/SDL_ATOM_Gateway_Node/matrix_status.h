#pragma once
#include <stdint.h>
#include <initializer_list>

// Pure rendering: no sleeps, networking, or fabricated progress counters.
namespace sdl {
enum class Phase { Boot, SensorFault, Unconfigured, Joining, Ready, Peer, Responsive };
struct Status {
  uint32_t now = 0;
  bool booting = false, sensorOk = false, configured = false;
  bool wifi = false, peer = false, button = false;
  bool sawPing = false, sentSample = false, sawError = false;
  uint32_t pingAt = 0, sampleAt = 0, errorAt = 0;
};
struct Matrix { uint32_t pixel[25] = {}; };
constexpr uint32_t AMBER = 0xD08000, BLUE = 0x0060C0, CYAN = 0x008888;
constexpr uint32_t GREEN = 0x00A040, RED = 0xC00000, WHITE = 0x808080, VIOLET = 0x8000A0;
inline bool recent(uint32_t now, uint32_t at, bool seen, uint32_t duration) {
  return seen && uint32_t(now - at) < duration;
}
inline Phase phase(const Status& s) {
  if (s.booting) return Phase::Boot;
  if (!s.sensorOk) return Phase::SensorFault;
  if (!s.configured) return Phase::Unconfigured;
  if (!s.wifi) return Phase::Joining;
  if (!s.peer) return Phase::Ready;
  return recent(s.now, s.pingAt, s.sawPing, 6000) ? Phase::Responsive : Phase::Peer;
}
inline const char* name(Phase p) {
  switch (p) {
    case Phase::Boot: return "BOOT";
    case Phase::SensorFault: return "SENSOR_FAULT";
    case Phase::Unconfigured: return "NO_SAVED_WIFI";
    case Phase::Joining: return "WIFI_JOINING";
    case Phase::Ready: return "WIFI_READY";
    case Phase::Peer: return "TCP_PEER";
    case Phase::Responsive: return "PING_ACTIVE";
  }
  return "UNKNOWN";
}
inline Matrix render(const Status& s) {
  Matrix m;
  const Phase p = phase(s);
  if (p == Phase::Boot) {
    for (uint8_t i : {uint8_t(7), uint8_t(11), uint8_t(12), uint8_t(13), uint8_t(17)}) m.pixel[i] = WHITE;
    return m;
  }
  if (p == Phase::SensorFault) {
    for (uint8_t row = 0; row < 5; ++row) {
      m.pixel[row * 5 + row] = RED;
      m.pixel[row * 5 + 4 - row] = RED;
    }
    return m; // Fault glyph has priority over pulses and button feedback.
  }
  if (p == Phase::Unconfigured) {
    m.pixel[0] = m.pixel[4] = m.pixel[20] = m.pixel[24] = AMBER;
  } else if (p == Phase::Joining) {
    static const uint8_t edge[] = {0,1,2,3,4,9,14,19,24,23,22,21,20,15,10,5};
    m.pixel[edge[(s.now / 180) % 16]] = AMBER;
  } else {
    const uint32_t c = p == Phase::Ready ? BLUE : p == Phase::Peer ? CYAN : GREEN;
    for (uint8_t row = 0; row < 5; ++row)
      for (uint8_t col = 0; col < 5; ++col)
        if (row == 0 || row == 4 || col == 0 || col == 4) m.pixel[row * 5 + col] = c;
    if (s.peer && recent(s.now, s.sampleAt, s.sentSample, 120)) m.pixel[12] = GREEN;
    if (s.peer && recent(s.now, s.pingAt, s.sawPing, 120)) m.pixel[7] = WHITE;
  }
  if (s.button) m.pixel[22] = VIOLET;
  if (recent(s.now, s.errorAt, s.sawError, 800)) m.pixel[0] = RED;
  return m;
}
} // namespace sdl
