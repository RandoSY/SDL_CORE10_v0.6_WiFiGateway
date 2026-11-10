# SDL CORE 10 v0.6 - Independent Wi-Fi/TCP Gateway + Graphical Analysis

**Start here: `docs/00_START_HERE.md`.** On Windows, double-click **`START_DEMO.bat`** after extracting the entire ZIP. Python 3.10+ standard library; no extra packages, Docker or cloud required for the demo.

- Dashboard: `http://127.0.0.1:8788/`
- WebSocket: `ws://127.0.0.1:8788/ws/telemetry`
- Python health: `http://127.0.0.1:8788/api/status`
- TCP node: port `8766`; simulation launches on `127.0.0.1`
- Unit/integration tests: `py -3 -m unittest discover -s tests -v`
- Real instrument (experimental): `START_WIFI_NODE.bat <DEVICE_IP> [PORT]`
- Optional browser behavior tests (Node.js required only for these tests): `node --test tests/test_browser_delivery.cjs`

**Scope:** 10 CORE 10 simulations and 8 Vernier-inspired browser extensions from v0.5; Python TCP gateway with 5-second goodput, sample integrity, RTT and approximate lag. Default data are explicitly **synthetic**. The gateway is a **standalone sidecar**, not a modification to the historical SUPER SDL v0.7 MCP/SDL-ASCII service; it uses different ports and a different node protocol.

**Security:** local-only browser server; no TLS or authentication. Do not port-forward or connect to untrusted networks.

Learn the architecture via `docs/01_ARCHITECTURE_AND_LESSON.md` and printable `docs/ARCHITECTURE.svg`. Status and limitations in `docs/04_TEST_REPORT.md`.

**Reliability fixes (2026-11-08):** malformed node input is rejected or reconnects safely; silent nodes have a configurable response deadline (`--node-timeout 10`); repeated Windows log rotation works and reports failures; browser queue losses are visible and retained in saved runs/exports; device-specific diagnostics reset on reconnect. See [behavior, compatibility, and recovery details](docs/05_GATEWAY_RELIABILITY.md).

**Original ATOM Matrix 1.0:** a separate MPU6886 bench node with state-based LED feedback is in `arduino/SDL_ATOM_Gateway_Node/`. See [hardware, matrix legend and bench limitations](docs/06_ATOM_MATRIX_1_0.md). It uses saved station settings when available and never indicates a successful transfer from an animation alone.

To run the physical COM30 USB/TCP/reconnect check from your normal Windows account, double-click **`RUN_ATOM_BENCH.bat`**. It reads the actual node IP and saves results under `artifacts/atom-bench-*`. An offline agent sandbox may deny LAN TCP even when ping succeeds; see the [bench record](docs/07_ATOM_BENCH_RESULTS.md#root-cause-of-the-pc-tcp-denial).

**Accelerometer monitor:** `START_ACCELEROMETER.bat` opens `http://127.0.0.1:8799/accelerometer.html`. Firmware 0.6.4 uses a dedicated FreeRTOS sampler and 128-reading queue; the physical 15.02-second test delivered 751 samples at 50.00 Hz without gaps, skips, drops or CRC/parse errors. See the [formal validation report](output/pdf/ATOM_Matrix_1_0_50Hz_Validation_Report.pdf), [runbook](RUNBOOK.md), and `node scripts/measure_accelerometer.cjs --history` for evidence and recall.

**Programmer's guide:** [PDF guide and source reference](output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf) and [editable design explanation](docs/08_ATOM_RESPONSIVENESS_DESIGN.md). Explains the sampler/queue, Python bridge, browser capture versus redraw, exact source locations, overflow policies and measured limits. The user confirmed substantially improved browser responsiveness at a solid displayed 50 Hz. Later cumulative queue drops qualify the short passing test; long-duration losslessness remains unverified.

**Fresh GitHub checkout:** set your physical ATOM endpoint once with `py -3 start_accelerometer.py --node-host <ATOM_IP> --save-node --open-browser` (replace `<ATOM_IP>`). This creates the ignored local `accelerometer_settings.json`; subsequent starts can use `START_ACCELEROMETER.bat`. `accelerometer_settings.example.json` shows the format with a documentation-only example IP. USB is optional. For a device without saved Wi-Fi credentials, the firmware folder supplies `wifi_config.example.h`; follow its comments to create an ignored local header.

The repository includes source, tests, documentation, reports, images, the original release ZIP, and the experiment summary ledger. Credentials, local endpoint settings, firmware/build exports, raw capture logs, temporary renderings and the local agent-session pointer remain local. Historical evidence paths and PDF file links refer to the original workstation; use the printed relative paths and fresh-checkout setup on another computer. No firmware binaries containing local credentials are published. `.gitattributes` preserves exact bytes for recorded source fingerprints.
