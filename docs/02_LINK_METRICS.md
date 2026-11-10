# Wi-Fi/LAN communications diagnostics - precise definitions

The Python implementation is in `gateway/server.py`, especially `Metrics.snapshot`, `LabGateway.handle_device`, `LabGateway.connect_device`, and `LabGateway.heartbeat`. A WebSocket metrics snapshot is broadcast each second. Query `http://127.0.0.1:8788/api/status` for the same information without a browser.

| Metric / JSON field | Computation | Interpretation / limitation |
|---|---|---|
| `connected` | Active TCP socket to node | Reachability only; not data correctness |
| `app_link_health_score` | Start 100; subtract recent CRC (3 each), gap (2 each), duplicate (2 each), reordered (3 each), parse (1 each) errors in **30 seconds**; 0 when disconnected or no sample accepted on the current connection/identity; capped at 40 when accepted data stale >3s | **Custom heuristic**, not a Wi-Fi standard or RF quality percentage; excludes browser drops and logging errors |
| `samples_total` | Count of accepted unique in-order samples | Excludes duplicate/out-of-order/rejected samples |
| `missing_samples` | Forward jumps in sequence count, summed | Samples missing **at application layer**; not direct evidence of Wi-Fi packet loss |
| `duplicate_samples` | Repeated last sequence number | Application-level duplicate samples |
| `out_of_order` | Sequence lower than latest accepted value | Out-of-order delivery/replay, not accepted |
| `crc_errors` | Wrong CRC32 for canonical JSON body | Detects accidental envelope corruption; **not** a cryptographic integrity/authentication guarantee |
| `parse_errors` | Malformed/invalid JSON or invalid field types | Includes invalid device messages |
| `integrity_pct` | `100*accepted / (accepted + missing + crc_errors)` | Approximate success indicator; denominator may count an error twice when CRC rejection also produces a sequence gap |
| `throughput_bytes_s` | Sum of bytes in **accepted** sample envelopes over 5 seconds / 5 | Not aggregate TCP/Ethernet/Wi-Fi throughput; excludes rejected frames, ACK, ping, retransmit, framing and browser traffic |
| `throughput_kbit_s` | `8*throughput_bytes_s / 1000` | Application goodput, decimal kb/s |
| `data_rate_samples_s` | Number of accepted samples in past 5 sec / 5 | Includes startup averaging window, so starts below steady-state |
| `rtt_ms`, `rtt_p95_ms` | Measured node ping-to-pong time; median and approximate 95th percentile of most recent 120 | End-to-end **round-trip** response including processing; not raw Wi-Fi latency |
| `estimated_upstream_lag_ms` | Node monotonic timestamp mapped to Python monotonic with ping midpoint clock offset, sampled arrival minus mapped send | Estimated one-way application delay, not true RF flight time |
| `clock_uncertainty_ms` | Approx. most recent RTT/2 | Rough uncertainty under symmetric delay assumption; may be worse on asymmetric/jittery network |
| `arrival_jitter_ms` | Deviation of arrival spacing from declared sample period, median of last 150 | Includes host scheduling, sample gaps and simulator timing effects |
| `last_sample_age_s` | Time since last accepted sample | Helpful for identifying a stale yet connected instrument |
| `rssi_dbm` | Directly **reported by node** when supplied | Cleared at disconnect/reconnect, identity changes, and a hello without RSSI; TCP alone cannot measure Wi-Fi RSSI |
| `reconnects` | TCP reconnections after an earlier successful session | Not the count of Wi-Fi association failures |
| `node_timeout_s` | Configured read/write and ping-response deadline; default 10 seconds | TCP connection establishment has a separate 3-second timeout |
| `node_timeouts` | Cumulative TCP connect/read or ping-response timeouts | Ordinary EOF, socket errors and oversized lines cause recovery without incrementing this timeout counter; write failure is reported through `last_device_error` |
| `last_device_error` | Most recent connection/read/ping error | Cleared on successful TCP connection; inspect timeout/error counters for history |
| `logging_ok` | Whether the latest log attempt succeeded; initially true | True does not certify earlier rows or storage durability; next successful write restores true |
| `log_errors`, `last_log_error` | Cumulative failed logging attempts and latest OS error text | Retained after logging recovers; rows missed during failure are not replayed |
| `browser_clients` | Array of active WebSocket clients with `client_id`, `dropped_messages`, `dropped_samples`, `queued_messages` | Per-client, per-connection queue observations; disconnected clients are removed |

Every outgoing WebSocket JSON message also carries a top-level `delivery` object with the same per-client fields. These are current counters attached when the frame is written, rather than when it is queued. `dropped_messages` counts all evicted message types; `dropped_samples` counts only evicted `sdl.sample` messages. They do not change upstream `missing_samples` or `integrity_pct`.

Link observations (RSSI, RTT, lag, jitter, sample age, nominal interval, and rolling goodput) are cleared across disconnect/reconnect and identity changes. Session totals remain cumulative. Sequence continuity is preserved for the same `(node, boot_id)` across reconnects and reset when that identity changes. Pending pings from the current TCP connection survive the initial hello so the first valid pong can establish RTT.

### Conceptual integrity layers

1. **Device recording:** Did the sensor make the reading? Are timestamps/units calibrated?
2. **Application numbering:** Did every expected acquisition sequence appear? This detects some missing observations.
3. **Envelope CRC32:** Did message body bytes match its checksum? Does not authenticate the sender.
4. **TCP:** Ordered, reliable byte stream between endpoints; transport retransmissions are not represented by application sample gaps.
5. **Gateway acceptance and archive:** Were valid readings accepted, indexed and logged?
6. **WebSocket display:** Did the current browser receive and plot them? A slow browser may drop enqueued UI messages independently of device acquisition. Drop counters identify known queue loss; they are not browser acknowledgments or a guarantee that every delivered sample was plotted.

For an actual instrument, the most important numbers to watch together are accepted sample rate vs requested sample rate, sequence gaps, sample age, reconnects, RTT/lag, and the instrument's own RSSI when available. One green score alone is insufficient.

See [gateway reliability](05_GATEWAY_RELIABILITY.md) for run warning semantics, export fields, retention limits, and recovery steps.
