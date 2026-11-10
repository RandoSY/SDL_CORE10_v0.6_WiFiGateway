# Gateway reliability changes - 2026-11-08

This maintenance update addresses the five issues found in the local gateway review. It keeps the Python standard-library runtime, existing service ports, device envelope format, and demo-only command allowlist.

## Changes and regression evidence

| Review finding | Resulting behavior | Automated evidence |
|---|---|---|
| Oversized lines and a correctly checksummed pong with a list/dictionary ID could terminate acquisition | Oversized input closes only that device connection and reconnects. Invalid fields/JSON are counted and rejected before dictionary lookups, timing arithmetic or forwarding | TCP recovery with and without a terminating newline; exact line-size boundaries; malformed pong followed by a valid sample on the same connection; invalid field and deep JSON tests |
| A second Windows log rotation silently stopped all subsequent appends | `Path.replace()` replaces the single previous archive; OS write/rotation errors appear in status; later writes retry normally | Multiple rotations over an existing archive on Windows, visible filesystem failure, and subsequent successful write |
| A silent open TCP socket never triggered recovery | Configurable read and ping deadlines terminate the failed connection, await its worker cleanup, and reconnect | Silent socket, partial line, active samples with unmatched pongs, slow sampling with healthy pongs, blocked write |
| Slow browsers silently lost queued samples | Per-browser cumulative drop counters accompany every outgoing JSON message and appear in HTTP status/Connections. Reports observed while recording flag the run and survive archive/load and exports | Queue overflow, separate fast/slow clients, sample versus non-sample eviction, actual frame serialization, JavaScript save/reload and CSV/JSON assertions |
| A new device could inherit old RSSI | RSSI and link observations clear across reconnects/identity changes; a hello without RSSI explicitly clears it | New node sharing a boot string, hello without RSSI, and same-boot TCP reconnect preserving sequence continuity |

## Operating the response deadline

```bat
py -3 launch.py --demo --node-timeout 10 --open-browser
py -3 launch.py --node-host 192.168.0.125 --node-timeout 30 --open-browser
```

`--node-timeout` must be a positive finite number of seconds. Direct callers can pass `node_timeout=...` to `LabGateway`. Zero, negative values, NaN and infinity are rejected.

The gateway sends a ping immediately on connection, then at intervals of `min(2 seconds, timeout / 2)`. Each pending ping must receive its matching valid pong. Expired pings are checked on this cadence, so detection can occur up to one ping interval after expiry, plus scheduling/IO delay. An unrelated pong, valid samples, or malformed input cannot acknowledge a pending ping.

Each device `readline()` must also complete before the deadline; sending partial bytes does not restart that individual read's timer. A write/drain uses the same timeout and closes its captured writer on failure. TCP establishment keeps its separate 3-second limit. Read/ping workers are canceled and awaited, socket closure is allowed up to 1 second, and reconnection waits 1.5 seconds. The timeout counter includes TCP establishment, read and pending-ping timeouts; other socket/write failures are exposed through `last_device_error`.

This deadline measures responsiveness, not sample rate. A slow sensor may remain connected while supplying pongs; the sample-age metric still shows whether useful data is arriving. Health is zero until a sample is accepted on the current connection/identity, and still uses the existing fixed 3-second stale-data cap thereafter. These heuristics do not certify measurement quality.

## Validation and identity continuity

`parse_line()` checks the UTF-8 JSON envelope and canonical-body CRC. `handle_device()` validates known message types, string fields, sequence range and numeric values before changing acquisition state. See [protocol limits](03_PROTOCOL_AND_HARDWARE.md#input-limits-and-response-deadlines) for exact bounds. Parse errors include invalid field types, unknown message types and overlong lines. CRC mismatches remain separate.

An oversized line cannot be safely resynchronized in place, so the gateway closes that connection. Other invalid complete messages are discarded and the connection can continue; a subsequent valid sample is accepted. A complete line at exactly 65,536 bytes is valid. A partial line at EOF is rejected.

Device identity is `(node, boot_id)` from hello. Sequence state persists across reconnects with the same identity so intervening gaps remain visible; either identity component changing resets the sequence baseline. Acquisition/error totals remain cumulative for the gateway lifetime. Producers must send a hello when identifying a new device/boot; the gateway does not infer a reboot solely from a sequence decrease.

RSSI, rolling goodput, sample age, nominal interval, RTT, lag, clock offset/uncertainty and jitter are cleared on disconnection/reconnection and identity changes. A hello without RSSI clears RSSI even for the same identity. A sample omitting RSSI preserves the most recent valid report on that connection. Initial hello processing retains pings already issued on the current TCP connection, avoiding loss of the first timing response.

## Log retention and failure recovery

Accepted samples and hello records append to `logs/session.jsonl`. Before the next append after that file exceeds 20 MiB, it replaces `logs/session.previous.jsonl`; a fresh current file is then opened. **Only the current file and one previous file are retained.** Older rotated data is intentionally replaced. A file may exceed the threshold by one record before the next rotation.

Logging failures do not stop telemetry. `logging_ok=false`, cumulative `log_errors`, and `last_log_error` appear in HTTP/WebSocket metrics and Connections. A subsequent successful write restores `logging_ok=true` while preserving the error count and last error text. Initially `logging_ok` is true; it is an attempt-status indicator, not proof of prior successful writes. Failed records are not buffered or replayed.

If logging fails, inspect the reported OS error and restore the directory's availability, permissions or free space. The next hello/sample retries automatically. Rotation failures are retried as well. Archive/export important trials before the two-file retention window overwrites them.

The logger remains synchronous and best effort. A slow filesystem can delay the event loop; this update does not introduce a logging thread, fsync durability, unlimited retention, or concurrent-process file coordination. Run one gateway writer per log directory.

## Browser delivery loss and saved runs

Each browser has a bounded 128-message queue. When full, the oldest queued message is evicted so device acquisition is not blocked. `dropped_messages` counts all evictions and `dropped_samples` counts evicted sample messages. Other browsers have independent counters.

Every outgoing JSON frame adds this top-level object, assembled when the frame is written:

```json
{
  "delivery": {
    "client_id": "connection-specific UUID",
    "dropped_messages": 3,
    "dropped_samples": 2,
    "queued_messages": 127
  }
}
```

The example is illustrative. `/api/status` and `sdl.metrics` additionally include a `browser_clients` array for active connections. `queued_messages` is an instantaneous queue observation; frame metadata is sampled after dequeuing its current message. Counters last for one WebSocket connection, reset on a new connection, and disappear from the status array after disconnect.

Connections shows **this browser dropped** counts, logging state and node timeout counts. An upstream score of 100 can coexist with browser queue loss or a logging failure; these are different stages of the data path. Known queue loss is not added to the node's missing-sample or CRC counts.

The browser processes counter deltas before ingesting the current frame. While recording, a positive sample-drop delta raises a persistent warning across tabs. Starting a new run, loading a different experiment, or choosing New run clears the current warning. Saving a flagged run preserves `browser_dropped_samples`; Archive labels it `[DELIVERY LOSS]`, loading it restores the warning, and JSON backup/import preserves the count. Older archives without the field load with zero known reported drops. CSV export adds a `browser_dropped_samples` column when nonzero and repeats the **run-level total**, rather than a per-row loss count.

These run totals count drops **reported while capture was active**, not a precisely timed count of missing trial observations. Drops observed while paused update the baseline but are not charged to a future run. If a loss occurred just before Start and its report arrives afterward, it is conservatively charged to the new capture. Reports arriving only after Stop are not retroactively charged to the finished run. Repeated reports of the same total are not counted twice.

Counters cover queue evictions only. They do not acknowledge browser rendering, detect all losses during abrupt disconnect, or reconstruct missing data. The existing 4,096-point browser capture limit also remains. Compare affected captures with gateway logs, checking logging errors and retention limits; do not assume those logs are a guaranteed complete archive. No automatic browser reconnect or sample replay is added here.

## Verification and artifact scope

Run the Python tests with `py -3 -B -m unittest discover -s tests -v` (or `RUN_TESTS.bat`). Optional browser behavior tests run with `node --test tests/test_browser_delivery.cjs`; they use Node's built-in modules and DOM/WebSocket substitutes, without installing packages. They execute the actual browser scripts and verify state, warning text, persistence and exports, but do not validate browser rendering. See [test report](04_TEST_REPORT.md).

This update changes the extracted source, tests, and Markdown documentation. The ZIP under `00/` and the existing operator guide PDF are original release artifacts and have not been regenerated; follow the updated Markdown for these maintenance behaviors. Physical Wi-Fi, firmware flashing, graphical browser smoke testing, and high-rate/long-duration acquisition still require separate validation.

Subsequent original ATOM Matrix 1.0 firmware upload, USB/IMU observations, and a successful short physical Wi-Fi/TCP stream/reconnect test are tracked separately in [the bench record](07_ATOM_BENCH_RESULTS.md). They do not establish long-duration acquisition or graphical browser validation.

The later dedicated accelerometer monitor adds browser auto-reconnect, physical-source checks, bounded capture and throttled rendering. Those are distinct from the original dashboard behaviors above. See [the detailed responsiveness design](08_ATOM_RESPONSIVENESS_DESIGN.md) and [PDF programmer's guide with exact source references](../output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf). The user has accepted its improved graphical responsiveness; automated browser frame-time measurement remains unperformed.
