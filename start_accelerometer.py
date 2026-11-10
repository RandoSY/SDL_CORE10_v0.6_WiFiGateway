"""Independent physical accelerometer monitor, leaving the simulator untouched."""
import argparse
import asyncio
from pathlib import Path
import webbrowser
import json
import urllib.request
import re
import ipaddress
from gateway.server import LabGateway

SETTINGS = Path(__file__).resolve().parent / 'accelerometer_settings.json'

def existing_monitor(port, node_host=None):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=1) as response:
            status = json.load(response)
        return (status.get('node') == 'atom-matrix-imu' and status.get('connected') is True
                and (node_host is None or status.get('node_host') == node_host))
    except (OSError, ValueError):
        return False

def discover_node(serial_port='COM30'):
    """Optional setup aid; normal Wi-Fi operation does not call this."""
    from scripts.check_atom_node import observe_serial
    text = observe_serial(serial_port, .6)
    addresses = re.findall(r'WiFi=ONLINE IP=(\d+\.\d+\.\d+\.\d+)', text)
    if not addresses or addresses[-1] == '0.0.0.0':
        raise RuntimeError(f'No online ATOM address on {serial_port}; use --node-host <current IP>')
    return addresses[-1]

def valid_host(value):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError('Node host must be an IP address or hostname')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', value):
            raise ValueError('Use a node hostname or IP without a URL scheme or port')
    return value

def resolve_node(node_host=None, discover_usb=False, serial_port='COM30', settings_path=SETTINGS):
    if node_host is not None:
        return valid_host(node_host)
    if discover_usb:
        return valid_host(discover_node(serial_port))
    try:
        settings = json.loads(Path(settings_path).read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise RuntimeError('Set --node-host <IP-or-hostname> --save-node once; USB discovery is optional') from exc
    if not isinstance(settings, dict):
        raise ValueError('Accelerometer settings must be a JSON object')
    return valid_host(settings.get('node_host'))

def save_node(node_host, settings_path=SETTINGS):
    path = Path(settings_path)
    settings = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(settings, dict):
        raise ValueError('Accelerometer settings must be a JSON object')
    settings['node_host'] = valid_host(node_host)
    path.write_text(json.dumps(settings, indent=2)+'\n', encoding='utf-8')

async def run(args):
    gateway = LabGateway(node_host=args.node_host, http_port=args.port)
    folder = Path(__file__).resolve().parent / 'logs' / 'accelerometer'
    folder.mkdir(parents=True, exist_ok=True)
    gateway.log_path = folder / 'session.jsonl'
    if args.open_browser:
        asyncio.get_running_loop().call_later(1, webbrowser.open,
            f'http://127.0.0.1:{args.port}/accelerometer.html')
    await gateway.run()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--node-host', help='ATOM IP or hostname; overrides saved settings without USB')
    source.add_argument('--discover-usb', action='store_true', help='optional USB setup discovery')
    parser.add_argument('--serial-port', default='COM30', help='used only with --discover-usb')
    parser.add_argument('--save-node', action='store_true', help='remember the selected node for subsequent Wi-Fi-only starts')
    parser.add_argument('--port', type=int, default=8799)
    parser.add_argument('--open-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    try:
        args.node_host = resolve_node(args.node_host, args.discover_usb, args.serial_port)
        if args.save_node:
            save_node(args.node_host)
        if args.open_browser and existing_monitor(args.port, args.node_host):
            webbrowser.open(f'http://127.0.0.1:{args.port}/accelerometer.html')
            print(f'Opened existing accelerometer monitor on port {args.port}.')
        else:
            print(f'ATOM Wi-Fi endpoint: {args.node_host}:8766')
            asyncio.run(run(args))
    except KeyboardInterrupt:
        print('Accelerometer monitor stopped.')
    except (OSError, RuntimeError, ValueError, ImportError) as exc:
        parser.exit(1, f'Monitor startup failed: {exc}\n')
