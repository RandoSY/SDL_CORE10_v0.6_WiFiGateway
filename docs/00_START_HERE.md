# SDL CORE 10 v0.6 - START HERE

**Deliverable:** independently runnable, Python-standard-library Wi-Fi/TCP telemetry gateway plus the existing five-tab CORE 10 graphical-analysis dashboard. **No Docker, Node, pip installs, or cloud account are required for the demo.**

## Windows: first successful experiment

1. Unzip the whole archive to a writable directory, e.g., `C:\SDL\SDL_CORE10_v0.6_WiFiGateway\`. Do not run individual HTML files directly out of ZIP.
2. Install Python 3.10 or newer if missing (`py -3 --version` verifies it).
3. Double-click `START_DEMO.bat`. This starts a **separate synthetic TCP instrument** and the **Python gateway** on your PC and opens `http://127.0.0.1:8788/`.
4. In the dashboard, select **Connections**. Choose **Python SDL Wi-Fi Gateway - live**. Confirm WebSocket URL `ws://127.0.0.1:8788/ws/telemetry` and press **Connect source**.
5. Verify status becomes **CONNECTED** and the **Wi-Fi / LAN Data Integrity Observatory** displays accepted samples/s, throughput, median round-trip time, and a link-health score.
6. Select **Live**, choose **Galileo Measurement Lab** (or another CORE 10 experiment), and press **Start run**. A stream of synthetic readings should appear. Stop, analyze, save, and export as needed.
7. Close the console (or press Ctrl+C) to stop the Python gateway and simulator. Closing only the dashboard window does not stop the gateway.

**Always recognize the provenance:** the default demo uses synthetic data transported through real loopback TCP sockets and real WebSocket messages. It is **not a physical Wi-Fi radio or instrument test**.

## Try deliberate communication failures

In PowerShell / cmd within the extracted directory:

```bat
py -3 launch.py --demo --drop-every 5 --bad-crc-every 7 --duplicate-every 4 --delay-ms 80 --open-browser
```

Watch **Connections** -> **SEQUENCE GAPS**, **CRC / DUPLICATES**, **APP LINK HEALTH**, **THROUGHPUT**, **ROUND-TRIP**, and **UPSTREAM LAG**. Restart without fault flags to return to clean demo conditions. Error counters are cumulative for that gateway session; health is a rolling 30-second heuristic.

## Run the automated tests

```bat
py -3 -m unittest discover -s tests -v
```

The Python suite now has 35 tests, including the original eight tests plus regressions for invalid fields, oversized/partial messages, silent nodes, unanswered pings, repeated log rotation, logging recovery, browser delivery loss, device identity changes, and seven monitor startup/endpoint checks. See `04_TEST_REPORT.md` for results and limitations.

Optional JavaScript behavior tests use Node.js's built-in runner: `node --test tests/test_browser_delivery.cjs`. Node.js is not needed to run the demo or Python tests.

## Recovery and capture warnings

The gateway reconnects after a node response timeout (10 seconds by default). A custom instrument must answer gateway pings with matching pong IDs, even when it samples slowly. Change the deadline when needed: `py -3 launch.py --node-host <DEVICE_IP> --node-timeout 30 --open-browser`.

In Connections, inspect logging status and **this browser dropped** counts as well as upstream integrity. A slow browser can lose sample deliveries while the gateway continues receiving data. A capture warning stays visible across tabs and is preserved when saving/loading the affected run or exporting JSON/CSV. Compare the browser capture with `logs/session.jsonl` before using affected data; logging itself is best effort and its errors must also be checked. Full definitions and retention limits are in `05_GATEWAY_RELIABILITY.md`.

## Where to learn more

- `01_ARCHITECTURE_AND_LESSON.md`: a guided explanation of each component and a walk-through.
- `02_LINK_METRICS.md`: exact meaning and limitations of link, integrity, throughput, and lag metrics.
- `03_PROTOCOL_AND_HARDWARE.md`: wire format, ESP32 example, real node steps and security caveats.
- `04_TEST_REPORT.md`: the local automated verification report and remaining acceptance gates.
- `05_GATEWAY_RELIABILITY.md`: fixes, protocol limits, timeout configuration, log retention, browser loss counters, and recovery steps.
- `08_ATOM_RESPONSIVENESS_DESIGN.md`: detailed explanation of the responsive 50 Hz physical ATOM monitor, with a linked PDF programmer's guide and source reference.
- `ARCHITECTURE.svg`: labeled, printable teaching diagram.

**Historical coexistence:** This is an independent v0.6 *sidecar*. It **does not overwrite or automatically integrate with** the earlier SUPER SDL v0.7 Python MCP gateway (MCP port 8000, legacy ASCII/TCP device port 8765, Traffic Cop 8787). The new sidecar uses device **8766** and dashboard HTTP/WebSocket **8788** by default. There is no direct MCP implementation in this download.
