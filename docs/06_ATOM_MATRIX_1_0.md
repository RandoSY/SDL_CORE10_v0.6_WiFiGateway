# Original ATOM Matrix 1.0 bench node and activity display

## Hardware and scope

`arduino/SDL_ATOM_Gateway_Node/` targets the **original ATOM Matrix hardware release 1.0**, ESP32-PICO-D4, MPU6886 (`WHO_AM_I = 0x19`). It is not an AtomS3 or a BMI270 driver. Pins: matrix GPIO27, button GPIO39 with the board's pull-up, internal IMU SDA25/SCL21. The external Grove pins are not initialized or probed.

The device on COM30 originally reported SDL hardware diagnostic 1.0.0 messages with MPU6886 PASS and Wi-Fi offline. A ROM connection identified ESP32-PICO-D4 revision v1.0 and 4 MB flash. The chip's silicon revision and ATOM board release are separate identifiers; the firmware target follows the user's confirmed ATOM Matrix 1.0 board.

This separate sketch supplies the gateway's SDL-NDJSON/1 TCP protocol on port 8766. The original diagnostic source remains in its separate Desktop project. The generic `SDL_WiFi_Node_Reference.ino` remains an ADC example; do not confuse its GPIO32 input with the onboard IMU used here.

Current firmware **0.6.4** acquires at **50 Hz** in a dedicated FreeRTOS task and queues physical magnitude readings for TCP publishing. A 15.02-second physical test received 751 samples at 50 Hz, with no gaps/skips/drops/errors. It sends `simulated=false`, `x` as acquisition uptime in **milliseconds**, and `y` as acceleration magnitude in **milli-g (mg)**. Stationary magnitude near 1000 mg is a functional check, not a calibration certificate.

For the implementation rationale, exact source navigation and later observations, use the [programmer's guide](../output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf) and [editable design reference](08_ATOM_RESPONSIVENESS_DESIGN.md). These include the later cumulative queue drops; the short passing measurement is not proof of lossless long-term operation.

The dedicated monitor is `http://127.0.0.1:8799/accelerometer.html`; start it with `START_ACCELEROMETER.bat`. It plots physical magnitude with correct ms/mg labels, CSV/JSON export and a 5-second stationary check. Browser rendering is capped at 10 Hz while every incoming sample is captured up to 4096 retained rows (about 82 seconds at 50 Hz); evictions and delivery drops are explicit. The last 60 seconds of the active segment are plotted. Existing CORE 10 presets retain their own scientific labels and should not be used for the IMU stream.

## Matrix legend

Brightness is capped at 20/255 and patterns are sparse. The display updates at most every 50 ms. It has no animation sleeps and does not fabricate network progress or sample activity.

| Display | Meaning | Trigger / priority |
|---|---|---|
| Small white plus | Startup initialization | First half-second; once per boot |
| Steady red X | MPU6886 missing or latest acceleration read failed | Overrides connection and event indicators after startup |
| Four amber corners | No saved Wi-Fi station configuration | Expected unconfigured condition, not a sensor failure |
| Single amber dot traveling around the edge | Saved network configured, not connected | Joining/retrying indication; does not imply successful RF traffic |
| Steady blue outline | Wi-Fi up, TCP service ready, no connected peer | Derived from actual Wi-Fi/socket state |
| Cyan outline | TCP peer connected, no recent completed ping/pong | Connection alone does not prove it is the Python gateway |
| Green outline | TCP connected and a ping was received with a successful local pong write within 6 seconds | Returns to cyan if that evidence goes stale |
| Brief green center pulse | A complete sample envelope was accepted by the local socket write | 120 ms; not proof of Python CRC acceptance, browser delivery or durable logging |
| Brief white pixel above center | Valid ping received and pong written locally | 120 ms; independent of sample pulse |
| Violet pixel at bottom center | Debounced physical button held | Press count increases on the down transition; does not change acquisition mode |
| Red top-left corner | Recent local communication error | 800 ms after incomplete write, overlong command or invalid ping ID; sensor-fault X still wins |

Disconnect clears event indicators so a new connection cannot inherit old ping/sample activity. The sensor-fault X takes priority over button feedback; LEDs do not claim a hardware electrical/optical self-test. A person must still confirm visible color, orientation and pixel operation.

The pure renderer in `matrix_status.h` also provides named states printed over USB (`matrix=...`). This makes state decisions auditable even without a camera. USB status uses 115200 baud; `s`, `i`, or `w` prints a status line and `h`/`?` prints help. These commands do not switch to decorative LED modes.

## Wi-Fi and connection behavior

The user selected **reuse saved Wi-Fi settings if available**. The sketch checks the saved station configuration and calls `WiFi.begin()` without supplying or printing credentials. It creates no access point, adds no default password, and does not erase network settings. If none are saved, it stays in the four-amber-corner state with working USB/IMU diagnostics. No credentials are embedded in this source.

After the device reported no saved settings, the user supplied `Desktop/ip_facts.txt`. A git-ignored `wifi_config.local.h` supplies `NODE_WIFI_SSID` and `NODE_WIFI_PASSWORD` for the local build; the configured network is saved through `WiFi.begin(ssid, password)`. Such a configured binary contains those strings, so local headers/builds are excluded from version control. With the local header absent, the sketch retains its saved-settings-only behavior.

USB command `f` prints the actual flash partition inventory and attempts `SPIFFS.begin(false)` to list paths and sizes (up to 100 files). It never requests formatting or reads file contents. An unmountable SPIFFS partition means no verified file list is available; it must not be described as empty. Firmware code and its compiled strings reside in the application partition, not as source files in SPIFFS.

Wi-Fi retries approximately every 20 seconds with auto-reconnect enabled. The TCP service starts when Wi-Fi is up, ends when Wi-Fi drops, and starts again after recovery. One connected peer is supported. Incoming command processing is bounded per loop and overlong lines are discarded through the next newline. Only compact gateway-style ping messages with ASCII alphanumeric/hyphen IDs receive replies; this is not a general hardware command interface.

The priority-2 sampler runs on core 1 at 20 ms intervals, independently of the existing network/display loop. A 128-reading FreeRTOS queue absorbs short publishing stalls; full-queue drops and skipped sampler deadlines are counted in USB `[TIMING]` output. Sequence numbers continue while the gateway is absent, so gaps remain observable. No fabricated catch-up samples are emitted. LED writes occur only when the image changes; at 50 Hz continuous sample activity can make the green center appear steady. Sensor reads, publishing and UI latency remain separate quantities. The `millis()` clock wraps after approximately 49.7 days and still requires further handling for continuous sessions spanning that boundary.

## Build, native tests and recovery

Required installed components for this workspace: Arduino CLI, M5Stack ESP32 core 3.3.8, and Adafruit NeoPixel 1.15.5. Build from the project root:

```powershell
arduino-cli compile --fqbn m5stack:esp32:m5stack_atom --jobs 4 --build-path artifacts/atom-build --output-dir artifacts/atom-bin --warnings all arduino/SDL_ATOM_Gateway_Node
```

Native tests execute the actual renderer header, with no copied state model. This workspace has GCC in `C:/msys64/ucrt64/bin`; make its runtime DLLs available on PATH before running:

```powershell
$env:Path = 'C:\msys64\ucrt64\bin;' + $env:Path
& 'C:\msys64\ucrt64\bin\g++.exe' -std=c++17 -Wall -Wextra -Werror tests/test_atom_matrix.cpp -o artifacts/atom-tests/test_atom_matrix.exe
& artifacts/atom-tests/test_atom_matrix.exe
```

Coverage includes startup/fault priority, unconfigured versus joining Wi-Fi, peer versus responsive connection, event pulse expiration, stale ping fallback, no stale sample/ping pulses after disconnect, button feedback, communication-error expiration and unsigned timer rollover. These tests validate rendering decisions, not physical LED emission.

Builds and optional flash backups belong under ignored `artifacts/`. A **full flash backup may contain saved credentials**; keep it local rather than publishing or attaching it to a report. A backup is not required for the bench checks. The initial backup attempt in this session was canceled at the user's direction to expedite testing; no complete backup is claimed. If a full backup is taken separately, verify its 4,194,304-byte length before treating it as restorable. The original diagnostic source is still available in the separate Desktop project for rebuilding.

On this COM30 connection, ROM/stub queries succeeded at 115200 baud; attempts to switch to 230400/460800 failed before reading flash. Use the stable baud rate rather than treating a failed fast transfer as a sensor or gateway failure. Do not open a serial monitor while esptool is using the port.

Bench results (backup, build, upload, boot, network and observed display) are recorded separately in `07_ATOM_BENCH_RESULTS.md` once performed. A successful compile or serialized LED state is not a physical visual confirmation.

After loading this sketch, `py -3 -B scripts/check_atom_node.py --port COM30` records USB status in a fresh `artifacts/atom-bench-*` folder. If the node is online, it exercises the actual Python gateway for 20 seconds, closes only that test TCP connection once, and checks sample resumption, CRCs, sequence handling, RTT and log status. The deliberate reconnection can create expected sequence gaps. If no saved network is available/connected, the tool records that Wi-Fi/TCP testing was not run and exits with code 2. This bench helper needs pyserial; the demo and ordinary Python gateway tests remain standard-library-only.

## Hardware reference

[M5Stack's original ATOM Matrix documentation](https://docs.m5stack.com/en/core/Atom-Matrix) describes the ESP32-PICO-D4, MPU6886, 5x5 matrix and button, and recommends low LED brightness to avoid excess heating. This sketch follows that hardware target and keeps brightness at 20/255.
