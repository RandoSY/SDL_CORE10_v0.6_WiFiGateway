# SDL v0.6 TCP / WebSocket wire contract and Wi-Fi hardware

## Ports and coexistence

| Service | Default port | This package |
|---|---:|---|
| TCP node endpoint (simulator or ESP32) | `8766` | **SDL-NDJSON/1**; not legacy protocol |
| HTTP CORE10 + WebSocket | `8788` | Python gateway binds `127.0.0.1` |
| Historical Pico SDL ASCII/TCP | `8765` | Not changed; not directly supported by this sidecar |
| Historical SUPER SDL MCP | `8000` | Not changed; not bundled |
| Historical Traffic Cop | `8787` | Not changed; not bundled |

## Device-to-Gateway payload

Each line sent on TCP is one UTF-8 JSON **envelope** terminated by newline. It includes `body` and `crc32`. The CRC32 covers canonical JSON of the **body only**, using sorted keys, no whitespace, and Python's UTF-8 encoding. The supplied Python simulator computes this automatically. ESP32 must serialize keys and numeric types consistently to match Python canonical serialization.

```json
{"body":{"type":"sample","seq":7,"x":3.5,"y":14.2,"mono_ms":3500,"period_ms":500,"unit":"g","channel":"mass","simulated":true},"crc32":"<computed CRC32>"}
```

`<computed CRC32>` is a placeholder, not a literal valid checksum. Use `gateway.node_sim.envelope(body)` to generate a valid line.

Node message types: `hello` declares node, boot ID, optional RSSI; `sample` contains acquisition; `pong` returns the ID and node monotonic timestamp for gateway-issued `ping`; `ack` may report accepted demo commands.

### Input limits and response deadlines

- Each complete UTF-8 envelope, including its terminating newline, must fit within **65,536 bytes**. Overlong lines close the device connection and trigger reconnection; a trailing partial line is rejected. Deeply nested/unparseable JSON, bad CRCs and invalid fields are counted and rejected.
- `type` must be `hello`, `sample`, `pong`, or `ack`. When non-null, `node`, `boot_id`, `channel`, `unit`, `experiment`, and `id` must be strings of at most 128 characters.
- Samples require integer `seq` from 0 through `2^53 - 1`, finite numeric `x` and `y`, and `abs(y) < 10^15`. Booleans are not numbers. The sequence limit preserves exact browser JSON integer representation.
- When non-null, `mono_ms` must be finite and nonnegative, `period_ms` must be finite and between 1 and 3,600,000, and `rssi_dbm` must be finite and between -130 and 0. If present, `simulated` must be a JSON boolean.
- A pong requires a string `id` matching a pending ping and finite nonnegative `mono_ms` to contribute timing data. Structurally valid but unknown pong IDs are ignored and do not satisfy another ping's deadline.
- **Answer every ping**, even if sampling is paused or slow. The default response/read deadline is 10 seconds, adjustable with `--node-timeout <seconds>`. Samples alone do not satisfy a pending ping. Reconnection waits 1.5 seconds after cleanup. See `05_GATEWAY_RELIABILITY.md` for scheduling details.

These checks tighten acceptance of malformed/previously loosely typed custom messages. The bundled simulator and reference sketch use compatible field types; the sketch still requires hardware validation.

The browser receives JSON messages via `ws://127.0.0.1:8788/ws/telemetry`:

- `sdl.hello` indicates bridge metadata and simulation/external mode.
- `sdl.sample` contains the accepted data point and provenance.
- `sdl.metrics` contains current Python link statistics once per second.
- `sdl.ack` and `sdl.command_result` acknowledge demo experiment selection.
- `sdl.error` reports invalid commands.

Every message also includes additive top-level `delivery` metadata for that browser's queue loss counters. Existing consumers can ignore it; consumers that require capture-integrity reporting should retain it. The payload shapes and service ports are unchanged. Browser capture warnings are persisted as run-level `browser_dropped_samples` in archive/JSON and, when nonzero, as a repeated run-level CSV column. See `05_GATEWAY_RELIABILITY.md` for the distinction between observed drops and exact missing samples in a trial.

## Wi-Fi Station node bring-up (reference example)

For the **original ATOM Matrix 1.0 / MPU6886**, use the separate `arduino/SDL_ATOM_Gateway_Node/` bench sketch and [matrix/hardware guide](06_ATOM_MATRIX_1_0.md). Its partial physical verification is recorded in [bench results](07_ATOM_BENCH_RESULTS.md). The generic ADC instructions below describe a different example.

**First establish the demo without hardware.** Then use the optional Arduino sketch `arduino/SDL_WiFi_Node_Reference.ino` as a development starting point; it has **not been compiled/flashed/bench-verified here**.

1. Select an ESP32 development board with compatible ESP32 Arduino core.
2. Open the sketch and set `WIFI_SSID` and `WIFI_PASS` to your LAN credentials. Do not publish the edited sketch with secrets.
3. Power the device over USB for programming only. In the Arduino IDE build/flash it; watch Serial Monitor at 115200 for the router-assigned DHCP IP address.
4. The device starts a TCP server at port **8766**, measures its configured ADC GPIO32 every 500ms, and includes node-reported RSSI. It does *not* yet speak to the M5Stack U180/U177 I2C weight module, whose address is usually `0x26`.
5. On the same LAN, on the PC where Python runs: `py -3 launch.py --node-host <DEVICE_IP> --node-port 8766 --open-browser`.
6. In browser Connections select `Python SDL Wi-Fi Gateway - live`, Connect; in Live press Start run. A sample stream and link diagnostics should be visible.

**Electrical warning:** The reference GPIO32 ADC input is 3.3V max. On the original ATOM Matrix, GPIO32 is also Grove SCL; do not connect the I2C scale and this ADC sketch at the same time. A U180 or U177 weight-I2C module requires its own properly engineered I2C firmware, level checks and commissioning sequence (scan 0x26, tare, calibrate known weights, check second reference). Those are **next steps**, not verified features of this Arduino example.

## Security boundaries

- This standalone demo does not add device authentication, TLS, or an authenticated web UI. It binds its browser HTTP/WebSocket service to loopback to reduce accidental network exposure. A device TCP listener may still be reachable on your LAN; use trusted lab networks.
- Do **not** forward ports 8766 or 8788 to the public internet. Do not operate hazardous actuators from the demo bridge.
- Do not confuse CRC32 with tamper protection: anyone who can replace a frame can calculate a new CRC32.
- If a real deployment requires remote access, specify a protected gateway, TLS, authentication, authorization, and audit policy first.

## Modularity

`web/comms.js` registers communication adapters using a common contract. The Python Gateway adapter consumes `sdl.sample` and `sdl.metrics` without forcing changes to the scientific graph engine. Future changes can add e.g. a legacy-ASCII adapter **at Python's node side**, preserving the browser contract. There is currently no shipped legacy-ASCII adapter in this package.
