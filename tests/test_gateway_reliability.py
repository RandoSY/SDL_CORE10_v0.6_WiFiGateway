"""Regression coverage for the gateway reliability review (2026-11-08).

Uses temporary logs and real loopback TCP on OS-assigned ports. No hardware,
existing session logs, or fixed service ports are touched.
"""
import asyncio
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from gateway import server
from gateway.node_sim import envelope


class ValidationAndLoggingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.gateway = server.LabGateway()
        self.gateway.log_path = self.root / 'logs' / 'session.jsonl'

    def test_bad_fields_are_counted_without_mutating_acquisition(self):
        invalid = [
            {'type': 'pong', 'id': [], 'mono_ms': 1},
            {'type': 'pong', 'id': {}, 'mono_ms': 1},
            {'type': 'pong', 'id': 'known', 'mono_ms': 10**400},
            {'type': 'hello', 'node': ['bad'], 'boot_id': 'b'},
            {'type': 'hello', 'node': 'node', 'boot_id': {}},
        ]
        for changes in ({'x': True}, {'x': 10**400}, {'y': False},
                        {'mono_ms': []}, {'channel': {}}, {'period_ms': -1},
                        {'simulated': 'false'}, {'seq': 2**53}):
            invalid.append(dict(type='sample', seq=1, x=1, y=2) | changes)
        self.gateway.metrics.pending['known'] = server.mono_ms()
        for body in invalid:
            with self.subTest(body=body):
                # Every example is correctly checksummed; CRC alone is insufficient.
                parsed = self.gateway.parse_line(envelope(body).encode())
                self.assertIsNotNone(parsed)
                self.gateway.handle_device(parsed, 100)
        self.assertEqual(self.gateway.metrics.parse_errors, len(invalid))
        self.assertEqual(self.gateway.metrics.samples, 0)
        self.assertIn('known', self.gateway.metrics.pending)
        self.gateway.handle_device({'type': 'sample', 'seq': 1, 'x': 1, 'y': 2}, 100)
        self.assertEqual(self.gateway.metrics.samples, 1)

    def test_deep_json_and_nonfinite_values_are_parse_errors(self):
        for raw in (b'[' * 1500 + b'0' + b']' * 1500,
                    b'{"body":{"x":NaN},"crc32":"00000000"}'):
            self.assertIsNone(self.gateway.parse_line(raw))
        self.assertEqual(self.gateway.metrics.parse_errors, 2)

    def test_second_and_third_rotations_replace_existing_archive(self):
        with patch.object(server, 'MAX_LOG_BYTES', 1):
            for number in range(4):
                self.gateway.log({'record': number})
                self.assertTrue(self.gateway.metrics.logging_ok)
                self.assertEqual(json.loads(self.gateway.log_path.read_text()), {'record': number})
        previous = self.gateway.log_path.with_name('session.previous.jsonl')
        self.assertEqual(json.loads(previous.read_text()), {'record': 2})
        self.assertEqual(self.gateway.metrics.log_errors, 0)

    def test_log_failure_is_visible_and_next_write_can_recover(self):
        obstruction = self.root / 'not-a-directory'
        obstruction.write_text('occupied')
        self.gateway.log_path = obstruction / 'session.jsonl'
        self.gateway.log({'record': 'fails'})
        status = self.gateway.status()
        self.assertFalse(status['logging_ok'])
        self.assertEqual(status['log_errors'], 1)
        self.assertTrue(status['last_log_error'])
        self.gateway.log_path = self.root / 'recovered' / 'session.jsonl'
        self.gateway.log({'record': 'recovered'})
        self.assertTrue(self.gateway.status()['logging_ok'])
        self.assertEqual(self.gateway.status()['log_errors'], 1)
        self.assertEqual(json.loads(self.gateway.log_path.read_text()), {'record': 'recovered'})

    def test_identity_change_clears_old_radio_clock_and_sequence(self):
        gateway = self.gateway
        gateway.handle_device({'type': 'hello', 'node': 'A', 'boot_id': 'same', 'rssi_dbm': -62}, 100)
        gateway.handle_device({'type': 'sample', 'seq': 20, 'x': 1, 'y': 2}, 100)
        gateway.metrics.ping_rtts.append(12)
        gateway.handle_device({'type': 'hello', 'node': 'B', 'boot_id': 'same'}, 100)
        status = gateway.status()
        self.assertIsNone(status['rssi_dbm'])
        self.assertIsNone(status['rtt_ms'])
        self.assertIsNone(status['last_sample_age_s'])
        gateway.handle_device({'type': 'sample', 'seq': 1, 'x': 1, 'y': 2}, 100)
        self.assertEqual(gateway.metrics.samples, 2)
        self.assertEqual(gateway.metrics.out_of_order, 0)
        gateway.handle_device({'type': 'hello', 'node': 'B', 'boot_id': 'same', 'rssi_dbm': -50}, 100)
        gateway.handle_device({'type': 'hello', 'node': 'B', 'boot_id': 'same'}, 100)
        self.assertIsNone(gateway.status()['rssi_dbm'])

    def test_connected_without_samples_is_not_healthy(self):
        self.gateway.metrics.connected = True
        self.assertEqual(self.gateway.status()['app_link_health_score'], 0)

    def test_invalid_timeout_configuration_is_rejected(self):
        for timeout in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                server.LabGateway(node_timeout=timeout)


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_line_at_limit_is_accepted(self):
        gateway = server.LabGateway()
        gateway.log = lambda row: None
        raw = envelope({'type': 'sample', 'seq': 1, 'x': 1, 'y': 2}).encode()
        raw = raw[:-1] + b' ' * (server.MAX_NODE_LINE - len(raw)) + b'\n'
        self.assertEqual(len(raw), server.MAX_NODE_LINE)
        reader = asyncio.StreamReader(limit=server.MAX_NODE_LINE)
        reader.feed_data(raw)
        reader.feed_eof()
        await gateway.read_device(reader)
        self.assertEqual(gateway.metrics.samples, 1)

    async def test_one_byte_over_line_limit_is_rejected(self):
        gateway = server.LabGateway()
        reader = asyncio.StreamReader(limit=server.MAX_NODE_LINE)
        reader.feed_data(b'x' * server.MAX_NODE_LINE + b'\n')
        reader.feed_eof()
        with self.assertRaises(ConnectionError):
            await gateway.read_device(reader)
        self.assertEqual(gateway.metrics.parse_errors, 1)

    async def test_blocked_write_times_out_and_closes_only_that_writer(self):
        class Writer:
            closed = False

            def write(self, raw):
                pass

            async def drain(self):
                await asyncio.Future()

            def close(self):
                self.closed = True

        gateway = server.LabGateway(node_timeout=.02)
        gateway.device_writer = writer = Writer()
        self.assertFalse(await asyncio.wait_for(gateway.send_node({'type': 'ping'}), 1))
        self.assertTrue(writer.closed)

    async def test_slow_client_loss_is_reported_on_next_written_frame(self):
        class Writer:
            def __init__(self):
                self.frames = []
                self.written = asyncio.Event()

            def write(self, raw):
                self.frames.append(raw)
                self.written.set()

            async def drain(self):
                pass

        writer = Writer()
        slow = server.WSClient(None, writer, None)
        fast = server.WSClient(None, None, None)
        gateway = server.LabGateway()
        gateway.clients.update((slow, fast))
        for seq in range(130):
            gateway.broadcast({'type': 'sdl.sample', 'payload': {'seq': seq}})
            fast.queue.get_nowait()
        self.assertEqual(slow.delivery_status()['dropped_samples'], 2)
        self.assertEqual(fast.delivery_status()['dropped_samples'], 0)
        self.assertEqual(gateway.metrics.missing, 0)
        self.assertEqual(len(gateway.status()['browser_clients']), 2)
        task = asyncio.create_task(slow.write_loop())
        try:
            await asyncio.wait_for(writer.written.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        frame = writer.frames[0]
        length = frame[1] & 127
        offset = 2
        if length == 126:
            length = struct.unpack('!H', frame[2:4])[0]
            offset = 4
        message = json.loads(frame[offset:offset+length])
        self.assertEqual(message['payload']['seq'], 2)
        self.assertEqual(message['delivery']['dropped_samples'], 2)
        self.assertEqual(message['delivery']['client_id'], slow.client_id)

    async def test_non_sample_eviction_does_not_inflate_sample_loss(self):
        client = server.WSClient(None, None, None)
        for _ in range(129):
            client.send({'type': 'sdl.metrics'})
        self.assertEqual(client.dropped_messages, 1)
        self.assertEqual(client.dropped_samples, 0)


class ConnectionRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.handlers = set()
        self.writers = set()
        self.tasks = []
        self.listeners = []
        self.connections = 0
        self.patch = patch.object(server, 'RECONNECT_DELAY', .01)
        self.patch.start()

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for writer in self.writers:
            writer.close()
        for listener in self.listeners:
            listener.close()
            await listener.wait_closed()
        for task in self.handlers:
            task.cancel()
        await asyncio.gather(*self.handlers, return_exceptions=True)
        self.patch.stop()

    async def start_gateway(self, handler):
        async def tracked(reader, writer):
            task = asyncio.current_task()
            self.handlers.add(task)
            self.writers.add(writer)
            self.connections += 1
            number = self.connections
            try:
                await handler(number, reader, writer)
            except (ConnectionError, OSError):
                pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass
                self.writers.discard(writer)
                self.handlers.discard(task)

        listener = await asyncio.start_server(tracked, '127.0.0.1', 0)
        self.listeners.append(listener)
        self.gateway = server.LabGateway(node_port=listener.sockets[0].getsockname()[1], node_timeout=.2)
        self.gateway.log = lambda row: None
        self.device_task = asyncio.create_task(self.gateway.connect_device())
        self.tasks.append(self.device_task)

    async def until(self, condition):
        async def poll():
            while not condition():
                if self.device_task.done():
                    self.device_task.result()
                    self.fail('Acquisition task exited unexpectedly')
                await asyncio.sleep(.01)
        await asyncio.wait_for(poll(), 3)

    async def healthy_node(self, reader, writer, boot='boot', seq=1):
        writer.write(envelope({'type': 'hello', 'node': 'test-node', 'boot_id': boot}).encode())
        writer.write(envelope({'type': 'sample', 'seq': seq, 'x': 1, 'y': 2}).encode())
        await writer.drain()
        while raw := await reader.readline():
            request = json.loads(raw)
            if request['type'] == 'ping':
                writer.write(envelope({'type': 'pong', 'id': request['id'], 'mono_ms': 1}).encode())
                await writer.drain()

    async def oversize_recovery(self, ending):
        async def node(number, reader, writer):
            if number == 1:
                writer.write(b'x' * (server.MAX_NODE_LINE + 100) + ending)
                await writer.drain()
                await reader.read()
            else:
                await self.healthy_node(reader, writer)
        await self.start_gateway(node)
        await self.until(lambda: self.gateway.metrics.samples == 1)
        self.assertEqual(self.gateway.metrics.parse_errors, 1)
        self.assertGreaterEqual(self.gateway.metrics.reconnects, 1)
        self.assertFalse(self.device_task.done())

    async def test_oversize_line_with_newline_recovers(self):
        await self.oversize_recovery(b'\n')

    async def test_oversize_unterminated_line_recovers(self):
        await self.oversize_recovery(b'')

    async def test_malformed_checksummed_pong_does_not_disconnect(self):
        async def node(number, reader, writer):
            writer.write(envelope({'type': 'pong', 'id': [], 'mono_ms': 1}).encode())
            await self.healthy_node(reader, writer)
        await self.start_gateway(node)
        await self.until(lambda: self.gateway.metrics.samples == 1)
        self.assertEqual(self.gateway.metrics.parse_errors, 1)
        self.assertEqual(self.connections, 1)

    async def test_silent_open_socket_times_out_and_reconnects(self):
        async def node(number, reader, writer):
            if number == 1:
                await reader.read()
            else:
                await self.healthy_node(reader, writer)
        await self.start_gateway(node)
        await self.until(lambda: self.gateway.metrics.samples == 1)
        self.assertGreaterEqual(self.gateway.metrics.node_timeouts, 1)
        self.assertGreaterEqual(self.gateway.metrics.reconnects, 1)

    async def test_incomplete_line_cannot_hold_connection_open(self):
        async def node(number, reader, writer):
            if number == 1:
                writer.write(b'{"body":')
                await writer.drain()
                await reader.read()
            else:
                await self.healthy_node(reader, writer)
        await self.start_gateway(node)
        await self.until(lambda: self.gateway.metrics.samples == 1)
        self.assertGreaterEqual(self.gateway.metrics.node_timeouts, 1)

    async def test_samples_without_matching_pongs_still_time_out(self):
        async def node(number, reader, writer):
            if number != 1:
                await self.healthy_node(reader, writer, boot='recovered')
                return
            # Incoming data must not hide a broken ping response path.
            seq = 0
            while True:
                seq += 1
                writer.write(envelope({'type': 'sample', 'seq': seq, 'x': seq, 'y': 2}).encode())
                writer.write(envelope({'type': 'pong', 'id': 'not-a-pending-ping', 'mono_ms': 1}).encode())
                await writer.drain()
                await asyncio.sleep(.02)
        await self.start_gateway(node)
        await self.until(lambda: self.gateway.metrics.boot_id == 'recovered')
        self.assertGreaterEqual(self.gateway.metrics.node_timeouts, 1)

    async def test_healthy_pongs_allow_slow_sampling(self):
        async def node(number, reader, writer):
            await self.healthy_node(reader, writer)
        await self.start_gateway(node)
        await self.until(lambda: bool(self.gateway.metrics.ping_rtts))
        await asyncio.sleep(.5)  # More than twice the configured deadline.
        self.assertEqual(self.connections, 1)
        self.assertEqual(self.gateway.metrics.node_timeouts, 0)
        self.assertEqual(self.gateway.metrics.samples, 1)

    async def test_same_boot_reconnect_preserves_sequence_and_clears_rssi(self):
        async def node(number, reader, writer):
            if number == 1:
                writer.write(envelope({'type': 'hello', 'node': 'test-node', 'boot_id': 'boot', 'rssi_dbm': -62}).encode())
                writer.write(envelope({'type': 'sample', 'seq': 10, 'x': 1, 'y': 2}).encode())
                await writer.drain()
            else:
                await self.healthy_node(reader, writer, seq=12)
        await self.start_gateway(node)
        await self.until(lambda: self.gateway.metrics.samples == 2)
        self.assertEqual(self.gateway.metrics.missing, 1)
        self.assertIsNone(self.gateway.status()['rssi_dbm'])


if __name__ == '__main__':
    unittest.main()
