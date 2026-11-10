# Operator / teacher lesson: How SDL v0.6 works

## One-minute mental model

**The instrument measures. Python supervises. The browser explains.**

This component belongs to the SDL / RobotEDU education product strategy: a Vernier-like instrument-and-software experience spanning experiments, acquisition, graphing, analysis and robotics. Its independently runnable gateway is an implementation boundary within that platform. It does not imply all broader product goals are implemented or validated here.

For the physical ATOM Matrix 1.0 monitor on PC port 8799, see [the detailed 50 Hz design and programmer's reference](08_ATOM_RESPONSIVENESS_DESIGN.md). It documents the dedicated FreeRTOS sampler, bounded queues, separate browser ingestion/rendering, source locations and evidence. The general lesson below describes the original demo on port 8788.

1. **Instrument (or synthetic device):** produces measurements, assigns a monotonically increasing sequence number, remembers its boot identity, reports optional RSSI, and sends timestamped samples. For a real ESP32 this runs as Wi-Fi **station** on your existing router; it is not an access point.
2. **Python SDL sidecar gateway:** connects to the instrument on TCP port 8766. It verifies each data envelope's CRC32, detects gaps and duplicates, calculates throughput/jitter/RTT/estimated lag, appends JSONL logs, and relays accepted samples to browsers.
3. **Browser CORE 10 dashboard:** loads locally over HTTP port 8788. It opens `/ws/telemetry` to receive readings and health metrics, plots graphs, performs model fitting and residual analysis, saves trials in browser local storage, and exports CSV/JSON. The dashboard can be closed and re-opened without stopping device acquisition.
4. **Existing SUPER SDL MCP Gateway (separate, not bundled):** remains an optional future integration point for Codex. This v0.6 package neither changes nor replaces it.

## Why TCP/IP is used

- Device -> Python: newline-delimited JSON over a persistent **TCP socket**, reliable ordered transport.
- Python -> dashboard: **WebSocket**, an HTTP-upgraded bidirectional stream well suited to real-time browser visualization.
- Browser -> Python: in demo mode, only an allowlisted `select_experiment` command is permitted. Physical control/actuation is explicitly disabled in this prototype.
- Timing-critical measurement belongs on the device. TCP, WebSocket, and a browser are not suitable for photogate microsecond timing or feedback loops. Buffer raw samples on the instrument when required.

## Teaching walk-through (10-15 minutes)

**Act A - one real network path without hardware**

Launch `START_DEMO.bat` and open Connections. Point out that the simulator is a separate TCP server, not a JavaScript curve masquerading as a socket. The Python gateway is a TCP client on one side and WebSocket server on the other. Connect the Python plugin, then start a Galileo run in Live. This produces synthetic mass-vs-time measurements carried over two socket legs.

**Act B - why a measured point has an identity**

Each accepted sample retains `node_id`, `boot_id`, `seq`, `x`, `y`, `unit`, and its receive timestamp. If a packet fails its checksum, Python rejects it. A missing sequence number raises a gap count; repeated numbers raise duplicate counts. The interface reports these separately.

**Act C - what the metrics prove**

- Samples/s: valid samples received in the last 5 seconds.
- Throughput: approximate **accepted application-frame byte rate**, not Wi-Fi PHY bitrate.
- Link-health score: application-level penalty from the last 30 seconds of errors; **not RF signal strength**.
- RTT: round-trip time of Python's ping/pong to the node (includes node scheduling).
- Lag: approximate one-way node-to-Python delay, estimated using timestamp offset from pings; uncertainty about RTT/2.
- RSSI: if available, a number **reported by the device's Wi-Fi radio**, not something Python calculates from TCP.

**Act D - fail on purpose**

Stop the clean demo and relaunch with `--drop-every 5 --bad-crc-every 7 --duplicate-every 4`. Watch missing, CRC, duplicates, and 30-second score. Explain why any single metric is insufficient: TCP can deliver bytes perfectly yet application samples can still be absent (e.g., the instrument did not produce them).

**Act E - data becomes evidence**

In Live choose Galileo, start, stop and save. Then select Analysis, review modeled-vs-measured data and residuals. Export CSV. Contrast the raw stream and model: a smooth fitted curve must never be mistaken for measurements. In Archive, label synthetic work as simulation, not real observation.

## Exact control path

```
       (Optional separate project) Codex -> MCP -> SUPER SDL v0.7 gateway
                              [NOT WIRED INTO v0.6]

 ESP32 / Pico W (Wi-Fi STA)              PC running Python
 [samples + seq + CRC32] ---- TCP 8766 -> [SDL v0.6 sidecar gateway]
           ^                              | validate; health; logs
           |                              | WebSocket /ws/telemetry
           |                              v
           +-- DEMO ONLY select -------- [Browser CORE10 v0.6 :8788]

 In demo mode, [separate Python synthetic TCP node] replaces physical Wi-Fi device.
```

## Practical division of responsibilities

| Where | Must happen there | Must NOT depend on |
|---|---|---|
| Device | Accurate timestamps, fast acquisition, hardware state, buffering | Web browser render loop |
| Python | Protocol validation, sequence/loss statistics, connection recovery, raw session logs | An open browser tab |
| Browser | Visualization, interactive models, CSV/export, classroom workflow | Direct command access to every device |

## What this release does not do

It does not replace Vernier commercial instrumentation with metrologically certified devices; claim independent browser automation validation in this environment; supply authentication/TLS for remote users; run the old SDL ASCII/TCP commands; include the existing MCP gateway code; or confirm physical ATOM/ESP32 operation. These are deliberately explicit acceptance boundaries.
