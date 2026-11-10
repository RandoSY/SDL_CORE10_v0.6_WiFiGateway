"""SDL Wi-Fi Gateway + dashboard bridge, Python stdlib-only.

Node side: newline-delimited JSON over TCP (SDL-NDJSON/1, explicitly NOT SDL ASCII).
Dashboard side: RFC6455 WebSocket at /ws/telemetry with read-only samples and diagnostics.
Demo-mode select_experiment is allowed; no arbitrary hardware control is accepted.
Port defaults deliberately avoid historical 8000 MCP, 8765 Pico and 8787 Traffic Cop.
"""
import asyncio
from collections import deque
import hashlib
import base64
import json
import math
import mimetypes
from pathlib import Path
import struct
import time
import uuid
import zlib

from .node_sim import canonical_bytes

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'web'
LOGS = ROOT / 'logs'
MAX_HTTP = 16*1024
MAX_WS_PAYLOAD = 32768
MAX_NODE_LINE = 65536  # Includes the terminating newline.
MAX_LOG_BYTES = 20*1024*1024
NODE_TIMEOUT = 10.0
RECONNECT_DELAY = 1.5


def unix_ms(): return round(time.time()*1000, 3)
def mono_ms(): return time.monotonic()*1000


def finite_number(value):
    """JSON booleans and integers too large for float arithmetic are not measurements."""
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False

def quantile(vals, fraction):
    if not vals: return None
    seq = sorted(vals)
    return round(seq[min(len(seq)-1, max(0, int((len(seq)-1)*fraction)))], 2)


class WSClient:
    def __init__(self, reader, writer, peer):
        self.reader, self.writer, self.peer = reader, writer, peer
        self.closed = False
        self.queue = asyncio.Queue(maxsize=128)
        self.client_id = str(uuid.uuid4())
        self.dropped_messages = 0
        self.dropped_samples = 0

    def delivery_status(self):
        return dict(client_id=self.client_id, dropped_messages=self.dropped_messages,
                    dropped_samples=self.dropped_samples, queued_messages=self.queue.qsize())

    async def write_loop(self):
        try:
            while True:
                msg = await self.queue.get()
                # Attach current counters at write time: even a previously queued frame
                # reports losses that occurred while this browser was falling behind.
                msg = dict(msg, delivery=self.delivery_status())
                raw = json.dumps(msg, separators=(',', ':'), allow_nan=False).encode()
                header = bytes([0x81])
                if len(raw) <= 125: header += bytes([len(raw)])
                elif len(raw) <= 65535: header += b'\x7e'+struct.pack('!H',len(raw))
                else: header += b'\x7f'+struct.pack('!Q',len(raw))
                self.writer.write(header+raw)
                await self.writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass

    def send(self, msg):
        if self.closed: return
        if self.queue.full():
            try:
                dropped = self.queue.get_nowait()
                self.dropped_messages += 1
                if dropped.get('type') == 'sdl.sample':
                    self.dropped_samples += 1
            except asyncio.QueueEmpty: pass
        self.queue.put_nowait(msg)

    async def receive(self):
        try:
            while True:
                head = await self.reader.readexactly(2)
                opcode, masked, length = head[0]&15, head[1]&0x80, head[1]&127
                if length == 126: length = struct.unpack('!H',await self.reader.readexactly(2))[0]
                if length == 127: length = struct.unpack('!Q',await self.reader.readexactly(8))[0]
                if not masked or length > MAX_WS_PAYLOAD: break
                mask = await self.reader.readexactly(4)
                frame = await self.reader.readexactly(length)
                data = bytes(b ^ mask[i%4] for i,b in enumerate(frame))
                if opcode == 8: break
                if opcode == 9:  # Ping; request-response messages are otherwise app-layer JSON
                    self.writer.write(b'\x8a'+(bytes([len(data)]) if len(data)<126 else b'\x00')+data[:125])
                    await self.writer.drain()
                    continue
                if opcode != 1: continue
                try: yield json.loads(data.decode('utf-8'))
                except (UnicodeError, ValueError): continue
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            return

    async def close(self):
        self.closed = True
        self.writer.close()
        try: await self.writer.wait_closed()
        except (ConnectionError, OSError): pass


class Metrics:
    def __init__(self):
        self.connected = False
        self.node = '—'; self.boot_id = None
        self.samples = 0; self.bytes_total = 0; self.missing = 0; self.duplicates = 0
        self.out_of_order = 0; self.crc_errors = 0; self.parse_errors = 0; self.reconnects = 0
        self.last_seq = None; self.last_rx_mono = None; self.last_rx_unix = None
        self.recv_rates = deque(maxlen=15000)
        self.ping_rtts = deque(maxlen=120)
        self.lags = deque(maxlen=120)
        self.offset = None
        self.lag_uncertainty_ms = None
        self.last_ping_id = None; self.pending = {}
        self.connected_since = None
        self.reconnect_attempts = 0
        self.recent_errors = deque(maxlen=5000)
        self.reported_rssi_dbm = None
        self.last_sample_gap_ms = None
        self.arrival_jitter_ms = deque(maxlen=150)
        self.nominal_interval_ms = None
        self.node_timeouts = 0
        self.last_device_error = None
        self.logging_ok = True
        self.log_errors = 0
        self.last_log_error = None

    def reset_device_observations(self, *, clear_pending=True):
        """Keep session counters, but never attribute old observations to a new link."""
        self.reported_rssi_dbm = None
        self.last_rx_mono = self.last_rx_unix = None
        self.nominal_interval_ms = None
        self.recv_rates.clear()
        self.ping_rtts.clear()
        self.lags.clear()
        self.arrival_jitter_ms.clear()
        if clear_pending:
            self.pending.clear()
        self.offset = self.lag_uncertainty_ms = None

    def snapshot(self, clients=0):
        now = mono_ms()
        elapsed_window = 5.0
        while self.recv_rates and self.recv_rates[0][0] < now-elapsed_window*1000:
            self.recv_rates.popleft()
        packets = len(self.recv_rates)
        bps = sum(item[1] for item in self.recv_rates)/elapsed_window
        stale = None if self.last_rx_mono is None else round((now-self.last_rx_mono)/1000, 2)
        # Recent window health, not an irreversible cumulative penalty.
        while self.recent_errors and self.recent_errors[0][0] < now-30000:
            self.recent_errors.popleft()
        recent = dict(crc=0, gaps=0, duplicates=0, reordered=0, parse=0)
        for _, kind, count in self.recent_errors:
            if kind in recent: recent[kind] += count
        score = max(0, min(100, 100 - 3*recent['crc'] - 2*recent['gaps']
                                   - 2*recent['duplicates'] - 3*recent['reordered']
                                   - recent['parse']))
        if not self.connected: score = 0
        elif stale is None: score = 0
        elif stale > 3: score = min(score, 40)
        sample_total = self.samples+self.missing
        return dict(connected=self.connected, node=self.node, boot_id=self.boot_id,
                    clients=clients, samples_total=self.samples, bytes_total=self.bytes_total,
                    missing_samples=self.missing, duplicate_samples=self.duplicates,
                    out_of_order=self.out_of_order, crc_errors=self.crc_errors,
                    parse_errors=self.parse_errors, reconnects=self.reconnects,
                    reconnect_attempts=self.reconnect_attempts,
                    node_timeouts=self.node_timeouts, last_device_error=self.last_device_error,
                    logging_ok=self.logging_ok, log_errors=self.log_errors,
                    last_log_error=self.last_log_error,
                    app_link_health_score=score, app_health_window_s=30,
                    window_errors_30s=recent,
                    arrival_jitter_ms=quantile(self.arrival_jitter_ms,.5),
                    nominal_interval_ms=self.nominal_interval_ms,
                    integrity_pct=round(100*self.samples/max(1,self.samples+self.missing+self.crc_errors),2),
                    data_rate_samples_s=round(packets/elapsed_window,2), throughput_bytes_s=round(bps,1),
                    throughput_kbit_s=round(8*bps/1000,2),
                    last_sample_age_s=stale, rtt_ms=quantile(self.ping_rtts,.5),
                    rtt_p95_ms=quantile(self.ping_rtts,.95),
                    estimated_upstream_lag_ms=quantile(self.lags,.5),
                    estimated_upstream_p95_ms=quantile(self.lags,.95),
                    clock_uncertainty_ms=self.lag_uncertainty_ms,
                    lost_fraction_pct=round(100*self.missing/max(1,sample_total),2),
                    rssi_dbm=self.reported_rssi_dbm, signal_note=('RSSI is node-reported, not independently measured by Python' if self.reported_rssi_dbm is not None else 'RSSI unavailable from TCP; score is application-level health, not RF quality'),
                    latency_note='Upstream lag is clock-offset-estimated; uncertainty approximately RTT/2. Not a one-way hardware timestamp.',
                    source='synthetic node' if self.node=='sim-atom-01' else 'network node')


class LabGateway:
    def __init__(self, node_host='127.0.0.1', node_port=8766, http_host='127.0.0.1', http_port=8788, demo=False,
                 node_timeout=NODE_TIMEOUT):
        if not finite_number(node_timeout) or node_timeout <= 0:
            raise ValueError('node_timeout must be a positive finite number of seconds')
        self.node_host=node_host; self.node_port=node_port
        self.node_timeout = node_timeout
        self.http_host=http_host; self.http_port=http_port; self.demo=demo
        self.metrics=Metrics(); self.clients=set(); self.device_writer=None
        self.stopped=False; self.write_lock=asyncio.Lock()
        self.log_path=LOGS/'session.jsonl'
        self.latest_experiment = 'galileo'
        self.last_status=None

    def log(self, row):
        # bounded failure behavior: log failure cannot disrupt active acquisition
        try:
            self.log_path.parent.mkdir(exist_ok=True)
            if self.log_path.exists() and self.log_path.stat().st_size > MAX_LOG_BYTES:
                self.log_path.replace(self.log_path.with_name('session.previous.jsonl'))
            with self.log_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(row, separators=(',', ':'),ensure_ascii=False,allow_nan=False)+'\n')
            self.metrics.logging_ok = True
        except OSError as exc:
            self.metrics.logging_ok = False
            self.metrics.log_errors += 1
            self.metrics.last_log_error = str(exc)

    def status(self):
        snap = self.metrics.snapshot(len(self.clients))
        snap['browser_clients'] = [client.delivery_status() for client in self.clients]
        snap['node_timeout_s'] = self.node_timeout
        snap['node_host'] = self.node_host
        snap['node_port'] = self.node_port
        return snap

    def broadcast(self, message):
        for client in tuple(self.clients): client.send(message)

    async def send_node(self, obj):
        writer = self.device_writer
        if writer is None: return False
        try:
            async with self.write_lock:
                writer.write((json.dumps(obj,separators=(',', ':'))+'\n').encode())
                await asyncio.wait_for(writer.drain(), timeout=self.node_timeout)
            return True
        except (ConnectionError, OSError, asyncio.TimeoutError):
            writer.close()
            return False

    def parse_error(self):
        self.metrics.parse_errors += 1
        self.metrics.recent_errors.append((mono_ms(), 'parse', 1))

    def parse_line(self, raw):
        try:
            env = json.loads(raw.decode('utf-8'))
            if not isinstance(env,dict) or not isinstance(env.get('body'),dict):
                raise ValueError('Missing NDJSON body envelope')
            body = env['body']
            if not isinstance(env.get('crc32'),str):
                raise ValueError('Missing CRC32')
            checksum = f'{zlib.crc32(canonical_bytes(body)) & 0xffffffff:08x}'
            if checksum != env['crc32'].lower():
                self.metrics.crc_errors += 1
                self.metrics.recent_errors.append((mono_ms(),'crc',1))
                return None
            return body
        except (ValueError,UnicodeError,TypeError,OverflowError,RecursionError):
            self.parse_error()
            return None

    @staticmethod
    def valid_device_message(body):
        """Validate before dictionary lookups, clock arithmetic, or JSON forwarding."""
        if not isinstance(body, dict):
            return False
        typ = body.get('type')
        if typ not in ('hello', 'sample', 'pong', 'ack'):
            return False
        for key in ('node', 'boot_id', 'channel', 'unit', 'experiment', 'id'):
            value = body.get(key)
            if value is not None and (not isinstance(value, str) or len(value) > 128):
                return False
        if 'simulated' in body and type(body['simulated']) is not bool:
            return False
        for key in ('mono_ms', 'period_ms', 'rssi_dbm'):
            value = body.get(key)
            if value is not None and not finite_number(value):
                return False
        if body.get('mono_ms') is not None and body['mono_ms'] < 0:
            return False
        if body.get('period_ms') is not None and not 1 <= body['period_ms'] <= 3600000:
            return False
        if body.get('rssi_dbm') is not None and not -130 <= body['rssi_dbm'] <= 0:
            return False
        if typ == 'pong':
            return isinstance(body.get('id'), str) and finite_number(body.get('mono_ms'))
        if typ == 'sample':
            return (type(body.get('seq')) is int and 0 <= body['seq'] <= 2**53-1
                    and finite_number(body.get('x')) and finite_number(body.get('y'))
                    and abs(body['y']) < 1e15)
        return True

    def handle_device(self, body, nbytes):
        if not self.valid_device_message(body):
            self.parse_error()
            return
        m=self.metrics
        typ=body.get('type')
        if typ == 'hello':
            newnode=body.get('node') or 'unknown'
            newboot=body.get('boot_id')
            if (newnode, newboot) != (m.node, m.boot_id):
                # Pings already sent on this TCP connection still have valid replies.
                m.reset_device_observations(clear_pending=False)
                m.boot_id=newboot
                m.last_seq=None
            m.node=newnode
            # A hello describes the current radio; absent RSSI means unavailable.
            m.reported_rssi_dbm=None
            rssi=body.get('rssi_dbm')
            if isinstance(rssi,(int,float)) and -130<=rssi<=0:
                m.reported_rssi_dbm=round(rssi,1)
            self.log({'kind':'hello','ts':unix_ms(),'data':body})
            return
        if typ == 'pong':
            ident=body.get('id')
            if ident in m.pending:
                start=m.pending.pop(ident)
                end=mono_ms()
                rtt=end-start
                m.ping_rtts.append(rtt)
                node_mono=body.get('mono_ms')
                if isinstance(node_mono,(int,float)):
                    m.offset=(start+end)/2-node_mono
                    m.lag_uncertainty_ms=round(rtt/2,2)
            return
        if typ == 'ack':
            self.broadcast({'type':'sdl.ack','payload':body,'sent_unix_ms':unix_ms()})
            return
        if typ != 'sample': return
        seq=body.get('seq'); x=body.get('x'); y=body.get('y'); device_mono=body.get('mono_ms')
        if m.last_seq is not None:
            if seq == m.last_seq:
                m.duplicates+=1; m.recent_errors.append((mono_ms(),'duplicates',1)); return
            if seq < m.last_seq:
                m.out_of_order+=1; m.recent_errors.append((mono_ms(),'reordered',1)); return
            if seq > m.last_seq+1:
                missed=seq-m.last_seq-1
                m.missing += missed
                m.recent_errors.append((mono_ms(),'gaps',missed))
        m.last_seq=seq; m.samples+=1; m.bytes_total+=nbytes
        now=mono_ms()
        interval=body.get('period_ms')
        if isinstance(interval,(float,int)) and 1<=interval<=3600000:
            m.nominal_interval_ms=interval
            if m.last_rx_mono is not None:
                # Separate arrival jitter from expected gaps; includes host scheduling.
                elapsed=now-m.last_rx_mono
                m.arrival_jitter_ms.append(abs(elapsed - interval))
        m.last_rx_mono=now; m.last_rx_unix=unix_ms()
        rssi=body.get('rssi_dbm')
        if isinstance(rssi,(int,float)) and -130<=rssi<=0:
            m.reported_rssi_dbm=round(rssi,1)
        m.recv_rates.append((now,nbytes))
        age=None
        if m.offset is not None and isinstance(device_mono,(int,float)):
            age=now-(device_mono+m.offset)
            if age>=-m.lag_uncertainty_ms and age<100000:
                m.lags.append(max(0,age))
        payload={'x':x,'y':y,'channel':body.get('channel','primary'),
                 'unit':body.get('unit',''),'seq':seq,'device':m.node,'node_id':m.node,
                 'boot_id':m.boot_id,'device_mono_ms':device_mono,
                 'experiment':body.get('experiment'), 'simulated':bool(body.get('simulated',False)),
                 'received_unix_ms':m.last_rx_unix}
        message={'type':'sdl.sample','payload':payload,'meta':{'received_unix_ms':m.last_rx_unix,'upstream_lag_est_ms':None if age is None else round(max(0,age),2)},'sent_unix_ms':unix_ms()}
        self.broadcast(message)
        self.log({'kind':'sample','ts':m.last_rx_unix,'sample':payload})

    async def read_device(self, reader):
        while True:
            try:
                raw = await asyncio.wait_for(reader.readline(), timeout=self.node_timeout)
            except ValueError as exc:
                self.parse_error()
                raise ConnectionError('Node line exceeds 65536 bytes; reconnecting') from exc
            if not raw:
                return
            if len(raw) > MAX_NODE_LINE:
                self.parse_error()
                raise ConnectionError('Node line exceeds 65536 bytes; reconnecting')
            if not raw.endswith(b'\n'):
                self.parse_error()
                return
            body = self.parse_line(raw)
            if body is not None:
                self.handle_device(body, len(raw))

    async def ping_device(self):
        m = self.metrics
        interval = min(2.0, self.node_timeout / 2)
        while True:
            if m.pending and mono_ms() - min(m.pending.values()) >= self.node_timeout * 1000:
                raise asyncio.TimeoutError('Node did not answer a ping before its deadline')
            ident = str(uuid.uuid4())
            m.pending[ident] = mono_ms()
            if not await self.send_node({'type': 'ping', 'id': ident}):
                raise ConnectionError('Node write failed or timed out')
            await asyncio.sleep(interval)

    async def connect_device(self):
        m=self.metrics
        while not self.stopped:
            writer = None
            tasks = []
            try:
                reader,writer=await asyncio.wait_for(
                    asyncio.open_connection(self.node_host,self.node_port,limit=MAX_NODE_LINE),timeout=3)
                if m.connected_since is not None: m.reconnects+=1
                m.connected_since=mono_ms()
                m.connected=True
                m.last_device_error = None
                # Preserve identity/sequence across a same-boot reconnect; clear all
                # link observations until this connection supplies its own evidence.
                m.reset_device_observations()
                self.device_writer=writer
                print(f'[GATEWAY] TCP node connected {self.node_host}:{self.node_port}',flush=True)
                await self.send_node({'type':'select_experiment','experiment':self.latest_experiment,'id':str(uuid.uuid4())}) if self.demo else None
                tasks = [asyncio.create_task(self.read_device(reader)),
                         asyncio.create_task(self.ping_device())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            except asyncio.TimeoutError as exc:
                m.node_timeouts += 1
                m.last_device_error = str(exc) or 'Node connection/read timed out'
            except (ConnectionError,OSError) as exc:
                m.last_device_error = str(exc)
                if m.reconnect_attempts%6==0:print(f'[GATEWAY] Waiting for node {self.node_host}:{self.node_port} ({exc})',flush=True)
            finally:
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                if writer is not None:
                    writer.close()
                    try:
                        await asyncio.wait_for(writer.wait_closed(), timeout=1)
                    except (ConnectionError, OSError, asyncio.TimeoutError):
                        pass
                m.connected=False; m.pending.clear(); m.offset=None
                m.reset_device_observations()
                self.device_writer=None
                m.reconnect_attempts+=1
            await asyncio.sleep(RECONNECT_DELAY)

    async def heartbeat(self):
        while not self.stopped:
            snap=self.status()
            self.last_status=snap
            self.broadcast({'type':'sdl.metrics','payload':snap,'sent_unix_ms':unix_ms()})
            await asyncio.sleep(1)

    async def handle_ws(self,reader,writer,peer):
        client=WSClient(reader,writer,peer)
        self.clients.add(client)
        writer_task=asyncio.create_task(client.write_loop())
        client.send({'type':'sdl.hello','payload':{'service':'SDL CORE10 Python Bridge v0.6','protocol':'SDL-NDJSON/1','mode':'SYNTHETIC' if self.demo else 'EXTERNAL','ws_path':'/ws/telemetry'},'sent_unix_ms':unix_ms()})
        client.send({'type':'sdl.metrics','payload':self.status(),'sent_unix_ms':unix_ms()})
        try:
            async for req in client.receive():
                if not isinstance(req,dict):continue
                if req.get('type')=='sdl.command':
                    cmd=req.get('command')
                    if cmd=='select_experiment' and self.demo:
                        exp=str(req.get('experiment',''))
                        if exp not in {'measure','dice','deck','mixing','cooling','calorie','tea','yeast','galileo','life'}:
                            client.send({'type':'sdl.error','message':'Unknown CORE10 experiment'})
                            continue
                        self.latest_experiment=exp
                        ok=await self.send_node({'type':'select_experiment','experiment':exp,'id':str(uuid.uuid4())})
                        client.send({'type':'sdl.command_result','command':cmd,'ok':ok,'experiment':exp})
                    else:
                        client.send({'type':'sdl.error','message':'Demo experiment selection only; hardware commands disabled'})
        finally:
            self.clients.discard(client)
            writer_task.cancel()
            await asyncio.gather(writer_task, return_exceptions=True)
            await client.close()

    async def http_client(self,reader,writer):
        try:
            request=await asyncio.wait_for(reader.readline(),timeout=10)
            if not request or len(request)>2048:return
            pieces=request.decode('ascii','replace').strip().split(' ')
            if len(pieces)<3:return
            method,path,_=pieces
            headers={}
            while True:
                line=await asyncio.wait_for(reader.readline(),timeout=5)
                if not line or line in (b'\r\n',b'\n'):break
                if len(line)>MAX_HTTP: return
                name,_,value=line.decode('latin1').partition(':')
                headers[name.lower().strip()]=value.strip()
            peer=writer.get_extra_info('peername')
            if headers.get('upgrade','').lower()=='websocket' and path=='/ws/telemetry':
                key=headers.get('sec-websocket-key','')
                if len(key)<10:return
                accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                writer.write(('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n').encode())
                await writer.drain()
                await self.handle_ws(reader,writer,peer)
                return
            if method!='GET':
                status,body,ctype=405,b'Method Not Allowed','text/plain'
            elif path in ('/api/status','/health'):
                status,body,ctype=200,json.dumps(self.status(),allow_nan=False).encode(),'application/json'
            else:
                target=path.partition('?')[0].lstrip('/') or 'index.html'
                file=(WEB/target).resolve()
                if not file.is_relative_to(WEB.resolve()) or not file.is_file():
                    status,body,ctype=404,b'Not found','text/plain'
                else:
                    status,body,ctype=200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
            writer.write(f'HTTP/1.1 {status} {"OK" if status==200 else "Error"}\r\n'.encode())
            writer.write(f'Content-Type: {ctype}; charset=utf-8\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\n\r\n'.encode()+body)
            await writer.drain()
        except (ConnectionError, OSError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            writer.close()
            try: await writer.wait_closed()
            except (ConnectionError,OSError): pass

    async def run(self):
        listener=await asyncio.start_server(self.http_client,self.http_host,self.http_port)
        print(f'[GATEWAY] Dashboard: http://{self.http_host}:{self.http_port}/',flush=True)
        print(f'[GATEWAY] WebSocket: ws://{self.http_host}:{self.http_port}/ws/telemetry',flush=True)
        print(f'[GATEWAY] Node: {self.node_host}:{self.node_port}',flush=True)
        async with listener:
            await asyncio.gather(listener.serve_forever(),self.connect_device(),self.heartbeat())
