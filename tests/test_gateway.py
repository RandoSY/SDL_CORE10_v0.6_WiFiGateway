"""Independent gateway verification, Python standard library only.
Run: python -m unittest discover -s tests -v
"""
import asyncio, base64, json, os, struct, time, unittest, zlib
import tempfile
from pathlib import Path
from gateway.node_sim import SimNode, envelope, canonical_bytes
from gateway.server import LabGateway, Metrics

class UnitTests(unittest.TestCase):
    def setUp(self):
        self.g=LabGateway()
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.g.log_path=Path(directory.name)/'session.jsonl'
    def test_crc_good_and_rejected_bad(self):
        body={'type':'sample','seq':2,'x':1,'y':12,'mono_ms':5}
        raw=envelope(body).encode()
        self.assertEqual(self.g.parse_line(raw),body)
        obj=json.loads(raw);obj['crc32']='00000000'
        self.assertIsNone(self.g.parse_line(json.dumps(obj).encode()))
        self.assertEqual(self.g.metrics.crc_errors,1)
    def test_sequence_gap_duplicate_and_reordered(self):
        for seq in [1,2,4,4,3,5]:
            self.g.handle_device({'type':'sample','seq':seq,'x':seq,'y':22,'mono_ms':seq,'period_ms':500},200)
        m=self.g.metrics
        self.assertEqual((m.samples,m.missing,m.duplicates,m.out_of_order),(4,1,1,1))
    def test_rssi_is_explicit_report_not_derived(self):
        self.assertIsNone(self.g.metrics.snapshot()['rssi_dbm'])
        self.g.handle_device({'type':'hello','node':'esp32-demo','boot_id':'b1','rssi_dbm':-62},100)
        self.assertEqual(self.g.metrics.snapshot()['rssi_dbm'],-62)
    def test_recent_health_window_recovers(self):
        m=self.g.metrics;m.connected=True;m.node='test';m.last_rx_mono=time.monotonic()*1000
        m.recent_errors.append((time.monotonic()*1000,'crc',2))
        self.assertEqual(m.snapshot()['app_link_health_score'],94)
        m.recent_errors.clear()
        self.assertEqual(m.snapshot()['app_link_health_score'],100)
    def test_bad_unicode_json(self):
        self.assertIsNone(self.g.parse_line(b'{not json'))
        self.assertEqual(self.g.metrics.parse_errors,1)

class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Free ephemeral ports on loopback to avoid conflicts with production services.
        self.node=SimNode(host='127.0.0.1',port=0,drop_every=5,bad_crc_every=7,duplicate_every=4)
        self.node_server=await self.node.serve()
        nodeport=self.node_server.sockets[0].getsockname()[1]
        self.g=LabGateway(node_host='127.0.0.1',node_port=nodeport,http_host='127.0.0.1',http_port=0,demo=True)
        self.g.log=lambda _:None
        self.web_server=await asyncio.start_server(self.g.http_client,'127.0.0.1',0)
        self.port=self.web_server.sockets[0].getsockname()[1]
        self.device_task=asyncio.create_task(self.g.connect_device())
        self.heartbeat_task=asyncio.create_task(self.g.heartbeat())
        await asyncio.sleep(.8)
    async def asyncTearDown(self):
        self.g.stopped=True
        for t in (self.device_task,self.heartbeat_task):t.cancel()
        await asyncio.gather(self.device_task,self.heartbeat_task,return_exceptions=True)
        self.node_server.close();self.web_server.close()
        await self.node_server.wait_closed();await self.web_server.wait_closed()
    async def get(self,path):
        r,w=await asyncio.open_connection('127.0.0.1',self.port)
        w.write(f'GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode());await w.drain()
        response=await asyncio.wait_for(r.read(),3)
        w.close();await w.wait_closed()
        return response
    async def test_independent_http_and_node_stream(self):
        response=await self.get('/api/status')
        self.assertIn(b'HTTP/1.1 200',response)
        data=json.loads(response.split(b'\r\n\r\n',1)[1])
        self.assertTrue(data['connected'])
        self.assertGreaterEqual(data['samples_total'],1)
        self.assertIsNotNone(data['rtt_ms'])
        self.assertIn('throughput_kbit_s',data)
        self.assertIn('estimated_upstream_lag_ms',data)
        response=await self.get('/index.html')
        self.assertIn(b'CORE 10',response)
        self.assertIn(b'HTTP/1.1 200',response)
    async def test_websocket_metrics_and_simulated_live_samples(self):
        r,w=await asyncio.open_connection('127.0.0.1',self.port)
        key=base64.b64encode(os.urandom(16)).decode()
        request=f'GET /ws/telemetry HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'
        w.write(request.encode());await w.drain()
        data=await asyncio.wait_for(r.readuntil(b'\r\n\r\n'),2)
        self.assertIn(b'101 Switching Protocols',data)
        got=set()
        for _ in range(12):
            first=await asyncio.wait_for(r.readexactly(2),3)
            plen=first[1]&127
            if plen==126: plen=struct.unpack('!H',await r.readexactly(2))[0]
            elif plen==127: plen=struct.unpack('!Q',await r.readexactly(8))[0]
            msg=json.loads((await r.readexactly(plen)).decode())
            got.add(msg['type'])
            if msg['type']=='sdl.sample':
                self.assertTrue(msg['payload']['simulated'])
                self.assertIn('seq',msg['payload'])
            if 'sdl.sample' in got and 'sdl.metrics' in got and 'sdl.hello' in got:break
        self.assertTrue({'sdl.hello','sdl.metrics','sdl.sample'}<=got)
        w.close();await w.wait_closed()
    async def test_fault_injection_causes_actual_integrity_counts(self):
        await asyncio.sleep(3.4)
        status=self.g.metrics.snapshot()
        self.assertGreaterEqual(status['missing_samples'],1)
        self.assertGreaterEqual(status['duplicate_samples'],1)
        self.assertGreaterEqual(status['crc_errors'],1)
        self.assertLess(status['app_link_health_score'],100)
        self.assertEqual(status['rssi_dbm'],None)

if __name__=='__main__': unittest.main()
