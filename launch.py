"""Run gateway and optional independent synthetic TCP node with one command.
Python 3.10+ standard library only. CTRL+C to stop everything.
"""
import argparse, asyncio, webbrowser
import math
from gateway.node_sim import SimNode
from gateway.server import LabGateway

async def main(args):
    sim_server=None
    if args.demo:
        sim=SimNode('127.0.0.1',args.node_port,args.drop_every,args.bad_crc_every,args.duplicate_every,args.delay_ms)
        sim_server=await sim.serve()
    server=LabGateway(args.node_host,args.node_port,args.bind,args.port,args.demo,node_timeout=args.node_timeout)
    if args.open_browser:
        asyncio.get_running_loop().call_later(1,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}/'))
    try:await server.run()
    finally:
        if sim_server:
            sim_server.close();await sim_server.wait_closed()

if __name__=='__main__':
    ap=argparse.ArgumentParser(description='SDL CORE 10 Wi-Fi Python Gateway + telemetry quality')
    ap.add_argument('--demo',action='store_true',help='start synthetic TCP node for independent live demonstration')
    ap.add_argument('--node-host',default='127.0.0.1',help='TCP device IP address (use Wi-Fi STA DHCP address for a real node)')
    ap.add_argument('--node-port',default=8766,type=int,help='SDL-NDJSON/1 node port (NOT historic SDL-ASCII 8765)')
    ap.add_argument('--node-timeout',default=10.0,type=float,help='positive seconds allowed for node reads and ping replies (default 10)')
    ap.add_argument('--bind',default='127.0.0.1',help='HTTP host interface; default loopback for safety')
    ap.add_argument('--port',default=8788,type=int,help='gateway HTTP+WebSocket port')
    ap.add_argument('--open-browser',action='store_true')
    ap.add_argument('--drop-every',default=0,type=int,help='demo fault injection: omit every Nth sample')
    ap.add_argument('--bad-crc-every',default=0,type=int,help='demo fault injection: corrupt CRC of every Nth sample')
    ap.add_argument('--duplicate-every',default=0,type=int,help='demo fault injection: duplicate every Nth sample')
    ap.add_argument('--delay-ms',default=0,type=int,help='demo fault injection: additional node transmission delay')
    args=ap.parse_args()
    if not math.isfinite(args.node_timeout) or args.node_timeout<=0:
        ap.error('--node-timeout must be a positive finite number of seconds')
    if args.demo and args.node_host!='127.0.0.1':ap.error('--demo requires --node-host 127.0.0.1')
    if args.demo and args.node_port==args.port:ap.error('node and web ports must differ')
    if args.bind not in ('127.0.0.1','localhost'):
        ap.error('this prototype serves a command channel without login; LAN exposure disabled; use loopback only')
    try:asyncio.run(main(args))
    except KeyboardInterrupt:print('\nSDL gateway stopped.')
