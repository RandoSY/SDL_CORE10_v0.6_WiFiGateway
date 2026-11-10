# Working commands

Run from this project directory. Target: **original ATOM Matrix 1.0 / MPU6886 / COM30**.

## Monitor

- Fresh checkout: `py -3 start_accelerometer.py --node-host <ATOM_IP> --save-node --open-browser` (replace the placeholder). This creates the ignored local endpoint file; `accelerometer_settings.example.json` shows its format. Normal runtime needs no USB. `wifi_config.example.h` documents optional local firmware credentials; do not publish the resulting header or configured binaries.
- Open `http://127.0.0.1:8799/accelerometer.html`.
- Double-click `START_ACCELEROMETER.bat`, or `py -3 start_accelerometer.py --port 8799 --open-browser`. Normal startup uses `accelerometer_settings.json` and never opens USB. The saved current address is `192.168.0.213`; .214 was stale.
- Change and remember a Wi-Fi endpoint from PowerShell with `.\START_ACCELEROMETER.bat --node-host <IP-or-hostname> --save-node` (replace the placeholder). Hostnames work only if the device/network actually provides name resolution; current firmware does not advertise an mDNS name. A DHCP reservation is an option for keeping a saved IP stable; no router settings were changed.
- Optional USB setup: `.\START_ACCELEROMETER.bat --discover-usb --serial-port COM30 --save-node`. Only this option needs pyserial/USB. Existing disconnected gateways must be stopped/restarted separately; resolving an address does not change the endpoint inside an old process.
- Node TCP port is 8766; browser HTTP/WebSocket port is 8799. A running instance is reused by the browser launcher. Device DHCP address may change.
- Logs: `logs/accelerometer/session.jsonl`, current plus one previous file, 20 MiB rotation.

## Validate and recall

```powershell
node --test tests/test_accelerometer.cjs tests/test_browser_delivery.cjs
py -3 -B -m unittest discover -s tests -p test_start_accelerometer.py -v
py -3 -B -m unittest discover -s tests -v
node scripts/measure_accelerometer.cjs 0.6.4-freertos
node scripts/measure_accelerometer.cjs --history
py -3 -B scripts/build_atom_report.py
```

The measurement needs Node 22+, Python/pyserial, COM30 free, and the live gateway on 8799. It captures 15 seconds, reads USB timing counters, and appends unique experiment evidence and firmware/source fingerprints to `experiments/atom-performance.jsonl`.

The report generator needs ReportLab and writes `output/pdf/ATOM_Matrix_1_0_50Hz_Validation_Report.pdf`. Its current three-page output was rendered with Poppler and visually checked. It refuses to regenerate the recorded report if current firmware source/binary hashes differ from the tested ledger entry.

Programmer's guide: `py -3 -B scripts/build_atom_programmers_guide.py` uses ReportLab and writes `output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf`. It reads `docs/08_ATOM_RESPONSIVENESS_DESIGN.md`, resolves source line references dynamically and fingerprints the referenced files. If the ignored local endpoint file is absent, its fingerprint is omitted with an explanatory note. Render the resulting PDF with Poppler and inspect it before sharing an updated edition. This guide does not replace the historical validation report; regenerating that historical report requires the original credential-bearing local binary matching its ledger hash, which is intentionally not published.

## Build and flash

Arduino CLI; M5Stack ESP32 core 3.3.8; Adafruit NeoPixel 1.15.5. Local network header `arduino/SDL_ATOM_Gateway_Node/wifi_config.local.h` is ignored; do not publish it or credential-bearing builds. Keep that file and saved settings intact.

```powershell
arduino-cli compile --fqbn m5stack:esp32:m5stack_atom --jobs 8 --build-path artifacts/atom-build --output-dir artifacts/atom-bin --warnings default arduino/SDL_ATOM_Gateway_Node
& 'C:\Users\rasyoung\.platformio\penv\Scripts\esptool.exe' --chip esp32 --port COM30 --baud 115200 --after hard_reset write_flash -z --flash_mode dio --flash_freq 80m --flash_size 4MB 0x1000 artifacts/atom-bin/SDL_ATOM_Gateway_Node.ino.bootloader.bin 0x8000 artifacts/atom-bin/SDL_ATOM_Gateway_Node.ino.partitions.bin 0xe000 'C:\Users\rasyoung\AppData\Local\Arduino15\packages\m5stack\hardware\esp32\3.3.8\tools\partitions\boot_app0.bin' 0x10000 artifacts/atom-bin/SDL_ATOM_Gateway_Node.ino.bin
```

Flashing must be authorized. These ranges preserve NVS; no full erase/format is required. 230400/460800 failed on this connection; 115200 works. Installed vendor pin-macro warnings are pre-existing; successful build/flash alone is not a hardware pass.

## Known limits

- Refresh the monitor after JS/HTML changes; export an existing capture before refreshing. Plotting is limited to 10 Hz while all incoming readings are retained up to 4096 rows, with evictions counted.
- FreeRTOS queue covers 128 readings (nominal 2.56 s). TCP publishing can still stall and add latency; queue overflow and sampler skips must stay visible.
- Sensor timestamp units are ms, magnitude units mg. Rest check is functional, not calibration. Initial RSSI is not meaningful before the first cache refresh.
- `CodexSandboxOffline` previously denied LAN TCP while ping worked; effective full access resolved it. Do not change firewall rules to work around an offline session.
- SPIFFS could not mount without formatting; no verified file list is available. Do not format it to obtain a listing.
- ATOM supports one TCP peer. Stop the live monitor before a direct `check_atom_node.py` reconnect bench; reconnect monitoring afterward. Never open COM30 concurrently from two tools. The WebSocket measurement uses the existing gateway instead of taking another node connection.
