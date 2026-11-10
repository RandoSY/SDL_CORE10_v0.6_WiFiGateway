"""Explicit, read-only bench check for the ATOM Matrix 1.0 gateway sketch.

Requires pyserial for COM observation. Does not flash, provision Wi-Fi, reset
the board, scan other ports, or operate attached peripherals. When online it
opens TCP 8766 and deliberately closes that test connection once to verify
gateway recovery. Existing production logs are not used.
"""
import argparse
import asyncio
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gateway.server import LabGateway


def observe_serial(port_name, seconds):
    import serial
    port = serial.Serial(port=None, baudrate=115200, timeout=.25, write_timeout=1)
    port.dtr = port.rts = False
    port.port = port_name
    received = bytearray()
    with port:
        port.write(b's')  # Read-only status command in both identified SDL sketches.
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            received.extend(port.read(min(port.in_waiting or 1, 4096)))
    return received.decode('utf-8', errors='replace')


async def check_tcp(host, seconds, output):
    gateway = LabGateway(node_host=host, node_timeout=10)
    gateway.log_path = output / 'session.jsonl'
    # Avoid mixing records from separate explicitly invoked bench runs.
    if gateway.log_path.exists():
        raise FileExistsError('Use a fresh output directory for each bench run')
    task = asyncio.create_task(gateway.connect_device())
    try:
        await asyncio.sleep(seconds / 2)
        if task.done():
            task.result()
            raise RuntimeError('Acquisition task stopped')
        before = gateway.metrics.samples
        if gateway.device_writer is None or before == 0:
            snapshot = gateway.status()
            snapshot['bench_passed'] = False
            snapshot['bench_error'] = 'No live node samples before reconnect test'
            return snapshot
        gateway.device_writer.close()  # Interrupt only this test TCP session.
        await asyncio.sleep(seconds / 2)
        if task.done():
            task.result()
            raise RuntimeError('Acquisition task stopped after reconnect')
        snapshot = gateway.status()
        snapshot['bench_samples_before_disconnect'] = before
        snapshot['bench_passed'] = (
            snapshot['connected'] and snapshot['samples_total'] >= before + 3
            and snapshot['reconnects'] >= 1 and snapshot['rtt_ms'] is not None
            and snapshot['crc_errors'] == 0 and snapshot['parse_errors'] == 0
            and snapshot['duplicate_samples'] == 0 and snapshot['out_of_order'] == 0
            and snapshot['logging_ok']
        )
        return snapshot
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM30')
    parser.add_argument('--serial-seconds', type=float, default=12)
    parser.add_argument('--seconds', type=float, default=20)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.serial_seconds <= 120 or not 12 <= args.seconds <= 120:
        parser.error('serial-seconds must be 1..120 and seconds must be 12..120')
    output = args.output or ROOT / 'artifacts' / ('atom-bench-' + time.strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True, exist_ok=False)
    text = observe_serial(args.port, args.serial_seconds)
    (output / 'serial.txt').write_text(text, encoding='utf-8')
    statuses = [line for line in text.splitlines() if '[SDL-NODE]' in line]
    if not statuses:
        raise RuntimeError('No gateway-node status observed; check the installed firmware and baud')
    latest = statuses[-1]
    print(latest)
    if 'IMU=PASS' not in latest:
        raise RuntimeError('ATOM IMU is not reporting PASS')
    addresses = re.findall(r'WiFi=ONLINE IP=(\d+\.\d+\.\d+\.\d+)', latest)
    if not addresses or addresses[-1] == '0.0.0.0':
        result = {'bench_passed': False, 'tcp_test': 'not run',
                  'reason': 'No online station connection; inspect saved Wi-Fi configuration',
                  'last_serial_status': latest}
        (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print('IMU/USB observed; Wi-Fi/TCP test not run because the node is offline.')
        return 2
    result = asyncio.run(check_tcp(addresses[-1], args.seconds, output))
    (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    return 0 if result['bench_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
