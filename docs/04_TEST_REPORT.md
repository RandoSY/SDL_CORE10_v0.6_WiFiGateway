# Functional verification and reliability regressions - November 8-9, 2026

## Current ATOM monitor verification - November 9

`py -3 -B -m unittest discover -s tests -q` passed **35 Python tests** after the Wi-Fi-only startup correction, including seven startup/endpoint checks. The combined browser behavior command is `node --test tests/test_accelerometer.cjs tests/test_browser_delivery.cjs`; **nine tests passed** in the recorded monitor verification. Six cover the dedicated physical monitor and three cover the original browser delivery/persistence behavior. These checks execute JavaScript with DOM substitutes, not graphical rendering.

Physical firmware 0.6.4 passed the 751-sample / 15.02-second 50 Hz measurement; the subsequent Wi-Fi-only gateway restart received 500 additional samples over ten seconds with no new-process missing/CRC/parse counts. The user explicitly accepted improved browser responsiveness and a solid displayed 50 Hz. Later uncontrolled since-boot queue drops mean long-duration losslessness remains unverified. Read [the current bench record](07_ATOM_BENCH_RESULTS.md) and [programmer's guide](../output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf) for evidence scopes and implementation details. The original baseline report follows.

## Automated verification

The original release reported eight passing tests. After the reliability fixes, verification was run on this Windows workspace with Python 3.14.0 and Node.js v22.20.0:

```
py -3 -B -m unittest discover -s tests -v
node --test tests/test_browser_delivery.cjs
```

**Result: 28 Python tests passed and 3 JavaScript behavior tests passed, with 0 failures.** Python tests complete in approximately 9 seconds; the JavaScript checks complete in under one second. Node.js is only required for the optional JavaScript checks, not for the demo or Python suite.

The original eight tests remain:

1. `test_crc_good_and_rejected_bad`: accepts correct envelope CRC; rejects corrupted checksum.
2. `test_sequence_gap_duplicate_and_reordered`: counts missing sequence, repeated frame, out-of-order frame.
3. `test_rssi_is_explicit_report_not_derived`: treats RSSI as node-reported or missing.
4. `test_recent_health_window_recovers`: health score recovers when recent errors age out.
5. `test_bad_unicode_json`: malformed JSON handled as parse error.
6. `test_independent_http_and_node_stream`: real loopback TCP node -> gateway, HTTP status endpoint, nonempty throughput and RTT fields.
7. `test_websocket_metrics_and_simulated_live_samples`: real HTTP WebSocket upgrade and streaming `sdl.hello`, `sdl.metrics`, `sdl.sample` frames.
8. `test_fault_injection_causes_actual_integrity_counts`: injected missing samples, duplicate packets and corrupt CRC produce nonzero counters and degraded health score.

**Real networking mechanism:** Python's `asyncio.start_server` and `asyncio.open_connection`, not in-process function calls. The tests use OS-allocated free TCP ports on `127.0.0.1`.

Twenty additional Python regression tests in `tests/test_gateway_reliability.py` cover:

- Correctly checksummed but invalid device fields, non-finite/deep JSON, and continued acceptance of valid samples.
- Exact 65,536-byte line acceptance and rejection one byte over the limit; reconnection for oversized terminated/unterminated lines.
- Silent/partially transmitting open sockets, unanswered pings despite incoming samples, and slow sampling with healthy pongs.
- Bounded blocked writes and validation of timeout settings.
- Repeated Windows log rotation with an existing archive, visible filesystem failure, and successful retry.
- Reset of radio/clock observations on identity change and preservation of same-boot sequence continuity after reconnection.
- Zero health before the current connection supplies accepted samples.
- Independent fast/slow browser queues, sample/non-sample eviction counts, HTTP status representation, and delivery counters on actual serialized WebSocket frames.

Three JavaScript checks execute `analysis.js`, `comms.js`, `core10.js`, `app.js`, and `wifi_diagnostics.js` with DOM/WebSocket substitutes. They exercise capture warnings, counter deltas during recording versus pause, new-run reset, saved archive/reload, CSV and JSON exports, and distinct display of logging errors versus upstream integrity. These are behavior checks, not graphical browser automation.

Tests use temporary log directories or disable logging on integration fixtures. They do not overwrite existing session logs or connect to physical instruments. Short response/reconnect intervals are used only inside regression fixtures; production defaults remain 10 seconds and 1.5 seconds respectively. See `05_GATEWAY_RELIABILITY.md` for the behavior contract.

## Explicit limitations

- **Wi-Fi bench scope:** Automated gateway tests use loopback TCP with a synthetic instrument. The physical ATOM also joined Wi-Fi at `192.168.0.214`, answered pings, and passed a 12-second TCP stream/reconnect test after session network permissions took effect: 21 accepted samples, zero CRC/parse/duplicate/reordering errors, one successful forced reconnect. Three expected sequence gaps occurred during the deliberate disconnect. See `07_ATOM_BENCH_RESULTS.md`; this is a short functional check, not a long-duration/RF benchmark.
- **Firmware bench scope:** The generic ADC example remains unflashed. A separate original ATOM Matrix 1.0 IMU node was compiled, uploaded and observed over USB; IMU passed and responded to movement. Native tests of its matrix renderer passed. The user confirmed amber dots before configuration and a green outline during the successful gateway test. Individual activity pulses and precise button counting still need confirmation.
- **Graphical browser validation not completed:** The original report recorded Chromium's `ERR_BLOCKED_BY_ADMINISTRATOR`. This update verified JavaScript behavior with substitutes and independently exercised Python HTTP/WebSocket streaming; it did not repeat that browser launch or visually validate the updated warning layout. A graphical smoke test remains open.
- **Not an integration with historic MCP service:** v0.6 is a standalone sidecar to coexist with prior SUPER SDL v0.7 infrastructure.
- **Application-level diagnostics only:** no Wi-Fi PHY link rate, RF interference survey, or retransmission counters; no guaranteed device clock synchronization.
- **Production hardening incomplete:** no login, TLS or remote network access, and the reference device adapter is intentionally read-only.
- **Runtime compatibility:** this verification used Python 3.14.0. The source targets Python 3.10+, but older interpreters were not exercised in this update.
- **Acquisition limits:** no long-duration/high-rate or slow-filesystem benchmark. Logging remains synchronous/best effort, with current-plus-one-previous retention; browser drop counters do not certify rendering or complete captures.
- **Release artifacts:** the ZIP in `00/` and existing guide PDF were not regenerated. Updated source and Markdown contain the maintenance changes.

## Manual Windows acceptance checklist

- [ ] `START_DEMO.bat` opens the dashboard at `http://127.0.0.1:8788/`.
- [ ] In Connections select Python SDL Wi-Fi Gateway and Connect source.
- [ ] Status becomes Connected, and metrics update every second.
- [ ] In Live select Galileo, Start run, and watch synthetic mass-versus-time values grow.
- [ ] Stop, view Analysis, save to Archive, export CSV and JSON.
- [ ] Re-launch with fault flags and verify CRC, duplicate, and gap counters change.
- [ ] Stop the Python process and verify dashboard changes to offline.
- [ ] Restart the clean demo and verify connection recovers.
- [ ] Verify the Connections detail shows logging status, per-browser drops and timeout counts.
- [ ] With a known lossy browser capture, verify the warning across tabs, Archive Load, CSV and JSON in a graphical browser.
- [ ] Only after these pass, connect an ESP32 with the reference protocol and validate true physical source and reported RSSI.
