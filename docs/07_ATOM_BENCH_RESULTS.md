# ATOM Matrix 1.0 bench record - 2026-11-08

This record separates observed hardware results from unperformed checks. Target is the user's confirmed **original ATOM Matrix 1.0**, connected through FTDI on COM30.

| Check | Result / evidence |
|---|---|
| Passive serial baseline, 115200 baud | Existing SDL diagnostic reported MPU6886 PASS (`0x19`), magnitude approximately 1.02 g, Wi-Fi offline, and stable free heap of 285,748 bytes over the initial 8-second observation |
| ROM chip identification | ESP32-PICO-D4 silicon revision v1.0, 40 MHz crystal |
| Flash identity | 4 MB flash detected at 115200 baud |
| Faster serial transport | Changing to 460800 or 230400 failed before backup data was read; baseline 115200 remained usable |
| Native matrix renderer | Compiled with GCC C++17 and `-Wall -Wextra -Werror`; all assertions passed |
| ATOM firmware build | Arduino CLI, `m5stack:esp32:m5stack_atom`, core 3.3.8, NeoPixel 1.15.5; configured build exit 0; sketch 991,681 bytes (31%), globals 48,888 bytes (14%) |
| Build warnings | Installed M5Stack core/variant redefines GPIO macros. Package post-build PowerShell invocations also reported profile execution-policy messages; build and binary generation succeeded. No system execution policy was changed |
| Full flash backup | Canceled to expedite at the user's direction; no valid full backup is claimed |
| Upload / boot | Uploaded on COM30 at 115200 baud; bootloader, partition table, OTA selector and application hashes verified by esptool; new firmware booted successfully |
| Physical IMU after upload | `IMU=PASS`, axes approximately (-37,-976,283) mg, magnitude 1017 mg; communication error count 0 at the captured status |
| Wi-Fi configuration | Initial saved-settings-only boot was unconfigured. User then supplied `Desktop/ip_facts.txt`; local configuration build uploaded and all written-image hashes verified. No full erase performed |
| Assigned IP / ICMP | **192.168.0.214**; two ICMP replies, 0% loss; observed RTTs 77 ms and 7 ms (brief reachability check, not a latency benchmark) |
| Gateway stream / reconnect | **PASS after session permissions took effect:** 21 accepted samples, 0 CRC/parse/duplicate/reordering errors, 1 successful forced TCP reconnect, logging OK. Three sequence gaps arose during the deliberate disconnect |
| Matrix decision after network setup | Serial state `matrix=WIFI_READY` (blue outline) without a peer; user confirmed a green outline during the successful live gateway test |
| Device filesystem listing | Actual partitions queried over COM30. SPIFFS mount without formatting failed; therefore there is **no verified file listing**, rather than proof the partition is empty. No format or file modification requested |
| Optical matrix confirmation / physical button | User confirmed amber dots and active green outline. Button activity detected over USB; one-count-per-intentional-press accuracy is not yet confirmed |

The selected build's NVS region is `0x9000..0xDFFF`. The upload's sector erase/write ranges exclude that region: bootloader `0x1000..0x7FFF`, partition table `0x8000..0x8FFF`, OTA selector `0xE000..0xFFFF`, and application from `0x10000`. No full-flash erase is part of the procedure. Saved configuration availability is checked by the running firmware; preserving a region alone does not prove useful credentials were stored there.

See [firmware scope and LED legend](06_ATOM_MATRIX_1_0.md). Physical acceleration is not yet calibrated. This record does not claim a long-duration reliability, RF-performance, or metrology test.

The initial check used `--serial-seconds 6 --seconds 12` and declined TCP while offline. After network setup, `py -3 -B scripts/check_atom_node.py --port COM30 --serial-seconds 2 --seconds 12` initially encountered the session TCP access denial, then **passed once full access and networking were enabled**. Successful evidence is in `artifacts/atom-bench-20261108-132507/` (`serial.txt`, `session.jsonl`, `result.json`). Current inventory and ping output are `artifacts/atom-current-inventory.txt` and `artifacts/atom-ping.txt`. No IP address was guessed or assigned manually.

Current device inventory reported by the firmware:

| Partition | Offset | Size | Role |
|---|---|---|---|
| `nvs` | `0x009000` | 20 KiB | Persistent settings, including station configuration |
| `otadata` | `0x00E000` | 8 KiB | Boot/OTA selection metadata |
| `app0` | `0x010000` | 3 MiB | Compiled firmware |
| `spiffs` | `0x310000` | 896 KiB | Filesystem partition; could not mount without formatting |
| `coredump` | `0x3F0000` | 64 KiB | Reserved diagnostic storage |

The bootloader and partition table are separate flash regions at `0x1000` and `0x8000`. Firmware source/header files live on the PC; they are compiled into `app0`, not uploaded as device filesystem files.

## Direct hardware follow-up

Before the session permission update, a fresh check observed Wi-Fi online and MPU6886 PASS but TCP was denied with `WinError 5`. This initial failure was an execution-access limitation; the successful retest below supersedes it.

A 30-second USB observation included the user's button/tilt action:

- Acceleration changed from approximately `(-35,-975,291)` mg stationary to `(-689,-424,-170)` mg during movement, then `(-107,-1000,198)` mg afterward. This confirms a physical motion response; these readings are not calibration data.
- The press counter advanced from 0 to 2. Button activity was detected; the number of intentional physical presses is being confirmed before asserting one count per press.
- IMU remained PASS; the firmware's communication error count stayed 0 and free heap stayed at 222,988 bytes across the printed statuses.
- A fresh two-packet ping check received both replies, at 7 ms and 22 ms, with 0% loss.
- Matrix state remained `WIFI_READY`, with no TCP peer and no samples transmitted, consistent with the access-denied TCP attempt.

Serial observations are saved in the timestamped `artifacts/atom-usb-*` folder. The simulated gateway suite separately passes all 28 Python tests.

## Root cause of the PC TCP denial

The shell identified its Windows account as `desktop-oh1us46\codexsandboxoffline`, a member of `CodexSandboxUsers`. A direct socket probe connected successfully to loopback `127.0.0.1:8766`, while connecting to the ATOM's `192.168.0.214:8766` raised `PermissionError`, Winsock 10013 (access forbidden). The asynchronous gateway reported the corresponding denied operation as WinError 5. This is local access denial, not an observed TCP refusal from the ATOM (normally Winsock 10061).

Windows Firewall's current profiles reported `BlockInbound,AllowOutbound`; no firewall setting was changed. The session's offline identity and effective network restriction explain why ICMP ping can work while the gateway process cannot open a LAN TCP socket. A narrowly scoped out-of-sandbox test was rejected by the session approval policy (`sandbox_approval=false`), and a retry after the user's full-permissions statement remained denied. User authorization alone did not change the running shell's effective policy.

`RUN_ATOM_BENCH.bat` is ready for the user to double-click from Explorer under their normal Windows account. It executes the same USB/TCP/reconnect check and writes timestamped results, with no elevation, flashing or firewall changes. The agent must not launch a different user/process route to evade its own restriction. If it also fails in a normal terminal, the resulting error will distinguish an actual refusal/timeout or application-specific Windows rule from the sandbox denial.

[Official OpenAI Windows sandbox troubleshooting](https://learn.chatgpt.com/docs/windows/windows-sandbox) recommends restarting Codex when network access was expected but remains blocked. In this session, the effective permissions subsequently changed to full access with networking enabled. `whoami` then reported the normal `rasyoung` account; the identical in-session bench command connected and passed **without an app restart, firmware change, or firewall modification**. This confirmed the ATOM listener was working and isolated the earlier failures to the offline execution context.

## Successful physical gateway retest

Command: `py -3 -B scripts/check_atom_node.py --port COM30 --serial-seconds 2 --seconds 12`.

| Measurement | Observed result |
|---|---|
| Node / endpoint | `atom-matrix-imu`, `192.168.0.214:8766` |
| Accepted physical samples | 21; 12 before the deliberate disconnect and 9 afterward |
| CRC / parse errors | 0 / 0 |
| Duplicates / out-of-order | 0 / 0 |
| Reconnects / timeouts | 1 successful reconnect / 0 timeouts |
| Missing sequence numbers | 3 during the deliberate disconnect; expected acquisition opportunities missed while disconnected |
| Configured sample period | 500 ms |
| Median application RTT | 12.61 ms after reconnect; brief bench observation, not a latency benchmark |
| Node-reported RSSI | -71 dBm at final snapshot |
| Logging | OK, 0 log errors |
| Matrix | User observed green outline during ping/pong traffic |
| Automated verdict | `bench_passed: true` |

The deliberate disconnect reduced the heuristic score to 94 and integrity to 87.5%; these values reflect the three intentionally missed sequence opportunities, not CRC failures. The helper closes its test connection on exit, so the node returns to the blue Wi-Fi-ready outline. No browser client was attached; this run validates physical node-to-Python streaming and recovery, not the graphical analysis workflow or optical confirmation of each individual activity pulse.

## 50 Hz update - firmware 0.6.4

The first 50 Hz attempt (0.6.3) used a shared loop and missed deadlines. Rolling snapshots were about 40-42 Hz; the last 500 logged samples of boot `f00eb3ac` averaged 48.54 Hz with 15 sequence gaps. This baseline is reconstructed from accepted raw data, not a matched-duration controlled benchmark.

Firmware 0.6.4 introduces a 20 ms priority-2 acquisition task on core 1, a 128-reading queue, counted skips/overflows, cached RSSI, and LED output only when its frame changes. The network/display loop publishes queued samples with original timestamps and sequence identities. Build passed (992,649 bytes program, 49,016 bytes globals); COM30 flash hashes verified.

`node scripts/measure_accelerometer.cjs 0.6.4-freertos` received **751 samples in 15.02 seconds**, exactly **50.00 Hz** from device and receive timing. Median/p95/maximum device interval were all **20 ms**. Sequence gaps, sampler skips, queue drops, CRC errors, parse errors and test-client delivery drops were all **zero**. RSSI was -72 dBm and median application RTT 9.89 ms. The stationary window reported mean 1017.6 mg, SD 2.7 mg.

Peak stage times observed since boot were acquisition 2.232 ms, network-command handling 3.716 ms, display 1.143 ms, and publishing 1962.551 ms. These peaks were unchanged across the measured window; they are not timing percentiles. The publish-stage stall includes frame construction and TCP writes. Independent acquisition and buffering protected sample cadence; network latency and button/UI responsiveness are not thereby guaranteed. The queue's nominal coverage is 2.56 seconds, and longer stalls can overflow it.

Evidence and source/binary SHA-256 fingerprints are appended to `experiments/atom-performance.jsonl`. Use `node scripts/measure_accelerometer.cjs --history` to recall results. Nine JavaScript behavior tests passed, including capture at 50 Hz, five-second stationary checking, source rejection, export metadata, and counted buffer eviction. The actual monitor JS processed the physical WebSocket stream with DOM substitutes; automated graphical rendering remained unavailable. This is a short functional pass, not an extended soak, calibrated vibration test, or validation of other board models.

## November 9 resumed observation and DHCP recovery

Firmware source still matched the measured 0.6.4 fingerprint; no new firmware was built or flashed. USB showed IMU PASS and Wi-Fi online at **192.168.0.213**, while the old monitor process still targeted .214. A temporary startup implementation discovered the address through COM30 by default; it was subsequently replaced by the Wi-Fi-only default described below. Its first three targeted regression tests passed (changed DHCP address, offline-node rejection, and rejecting stale/disconnected monitor reuse), and explicit live discovery returned .213. Discovery is an optional setup operation, not automatic endpoint replacement in an already-running process.

Cumulative USB counters showed **479 queue drops, zero sampler skips, and a 3.660139-second publishing-stage peak**. These are uncontrolled since-boot observations, not losses within the earlier 15-second test. The peak exceeds the queue's nominal 2.56-second coverage; the precise causes and timing of individual overflows were not recorded. The original short PASS and PDF remain valid for their stated window, but must not be treated as evidence of lossless overnight operation.

The separate physical check `py -3 -B scripts/check_atom_node.py --port COM30 --serial-seconds 2 --seconds 30` passed at .213: 1420 accepted samples, zero CRC/parse/duplicate/reordered errors, one deliberate disconnect followed by successful reconnection, and final rolling rate 50.0 Hz. The 76 missing sequence opportunities occurred across the deliberate disconnection; queue-drop delta during this check was zero. Evidence is `artifacts/atom-bench-20261109-125240/result.json`, with a concise ledger record. A separate auxiliary USB observation initially collided with the test's serial access; it was repeated sequentially after the completed test.

The execution tool initially rejected the scoped command to restart only the background monitor on port 8799, returning “blocked by policy” without a more specific reason. After the user reset the agent and requested a retry, the scoped restart succeeded as recorded below; the earlier pending-restart state is resolved.

The user clarified that USB is a setup convenience, not an operational requirement. The temporary default-USB-discovery design was therefore replaced: normal startup reads `accelerometer_settings.json`, or an explicit `--node-host`; only an explicit `--discover-usb` opens serial. The saved endpoint is .213. This host-only correction required no firmware change. A saved numeric IP can become stale again if DHCP changes; configure a stable network address or resolvable hostname as appropriate. Current firmware does not advertise mDNS, and no such capability is claimed.

## Wi-Fi-only recovery and browser acceptance - November 9

After verifying its executable and command line, the stale gateway PID 20656 was stopped and PID 26736 started on PC port 8799 using the saved .213 endpoint. Firmware stayed at 0.6.4 and no USB port was opened. In a ten-second status observation the accepted sample total advanced from 200 to 700: 500 additional readings, final rolling 50 Hz, zero new-process missing/CRC/parse counts, RTT 9.89 ms and RSSI -74 dBm. Firmware queue counters were not read in this observation. The structured ledger records this separately as `gateway_status_window`.

The user subsequently confirmed markedly improved browser snap and a solid displayed 50 Hz, describing it as “far far better responsiveness.” This is operator-observed graphical acceptance of the dedicated monitor, not an automated frame-time or end-to-end latency benchmark. No new long-duration losslessness claim follows from that feedback.

All 35 Python tests passed after the Wi-Fi-only startup correction, including seven endpoint/startup regressions. Nine JS behavior tests had passed for the monitor and browser delivery paths. The detailed implementation explanation and exact source reference are in [the programmer's guide](../output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf) and [editable design record](08_ATOM_RESPONSIVENESS_DESIGN.md).
