// Native tests execute the actual firmware renderer, without LED/network drivers.
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include "../arduino/SDL_ATOM_Gateway_Node/matrix_status.h"
int main() {
  sdl::Status s;
  s.booting = true;
  assert(sdl::phase(s) == sdl::Phase::Boot);
  s.booting = false;
  auto m = sdl::render(s);
  assert(sdl::phase(s) == sdl::Phase::SensorFault);
  assert(m.pixel[0] == sdl::RED && m.pixel[12] == sdl::RED && m.pixel[4] == sdl::RED);
  s.sensorOk = true;
  assert(sdl::phase(s) == sdl::Phase::Unconfigured);
  m = sdl::render(s);
  assert(m.pixel[0] == sdl::AMBER && m.pixel[24] == sdl::AMBER && m.pixel[12] == 0);
  s.configured = true;
  assert(sdl::phase(s) == sdl::Phase::Joining);
  const auto first = sdl::render(s);
  s.now = 180;
  const auto second = sdl::render(s);
  assert(first.pixel[0] == sdl::AMBER && second.pixel[1] == sdl::AMBER);
  s.wifi = true;
  assert(sdl::phase(s) == sdl::Phase::Ready);
  s.peer = true;
  assert(sdl::phase(s) == sdl::Phase::Peer); // No fabricated green before a real ping.
  s.sawPing = true; s.pingAt = s.now;
  assert(sdl::phase(s) == sdl::Phase::Responsive);
  s.sentSample = true; s.sampleAt = s.now;
  m = sdl::render(s);
  assert(m.pixel[12] == sdl::GREEN && m.pixel[7] == sdl::WHITE);
  s.now += 120;
  m = sdl::render(s);
  assert(m.pixel[12] == 0 && m.pixel[7] == 0); // Pulses expire without sleeping.
  s.now += 6000;
  assert(sdl::phase(s) == sdl::Phase::Peer); // Stale pings remove green border.
  s.peer = false;
  s.sampleAt = s.pingAt = s.now;
  m = sdl::render(s);
  assert(m.pixel[12] == 0 && m.pixel[7] == 0); // No old activity while disconnected.
  s.button = true;
  assert(sdl::render(s).pixel[22] == sdl::VIOLET);
  s.sawError = true; s.errorAt = s.now;
  assert(sdl::render(s).pixel[0] == sdl::RED);
  s.now += 800;
  assert(sdl::render(s).pixel[0] == sdl::BLUE);
  s.sensorOk = false;
  m = sdl::render(s);
  assert(m.pixel[12] == sdl::RED && m.pixel[22] == 0); // Fault overrides button.
  assert(sdl::recent(20, UINT32_MAX - 20, true, 120));
  assert(!sdl::recent(200, UINT32_MAX - 20, true, 120));
}
