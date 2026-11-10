"""SDL Lab Wi-Fi node emulator, TCP NDJSON/1; educational synthetic readings ONLY."""
import asyncio, json, math, random, time, uuid, zlib


def canonical_bytes(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False).encode()


def envelope(body):
    return json.dumps({'body': body, 'crc32': f'{zlib.crc32(canonical_bytes(body)) & 0xffffffff:08x}'}, separators=(',', ':')) + '\n'


class SimNode:
    def __init__(self, host='127.0.0.1', port=8766, drop_every=0, bad_crc_every=0, duplicate_every=0, delay_ms=0):
        self.host, self.port = host, port
        self.drop_every, self.bad_crc_every, self.duplicate_every = drop_every, bad_crc_every, duplicate_every
        self.delay_ms = delay_ms
        self.boot_id = str(uuid.uuid4())[:8]
        self.experiment = 'galileo'
        self.interval = .5
        self.epoch = time.monotonic()
        self.counter = 0
        self.exp_counter = 0
        self.rng = random.Random(1007)

    def sample(self):
        self.counter += 1
        self.exp_counter += 1
        i = self.exp_counter
        seq = self.counter
        t = i * self.interval
        r = self.rng
        exp = self.experiment
        # Different synthetic processes; never passed off as physical observations.
        if exp == 'measure':
            x, y, unit = i, 100 + r.gauss(.15, .12), 'mm'
        elif exp == 'dice':
            x, y, unit = i, r.randint(1, 6) + r.randint(1, 6), 'sum'
        elif exp == 'deck':
            x, y, unit = i, 1 if r.random() < .61 else 0, 'red=1'
        elif exp == 'mixing':
            x, y, unit = t, .5 + .5 * math.exp(-t / 8) + r.gauss(0, .025), 'fraction'
        elif exp == 'cooling':
            x, y, unit = t, 22 + 51 * math.exp(-t / 18) + r.gauss(0, .13), '°C'
        elif exp == 'calorie':
            x, y, unit = t, 21 + 14 * (1 - math.exp(-t / 18)) + r.gauss(0, .08), '°C'
        elif exp == 'tea':
            x, y, unit = t, .08 + .75 * (1 - math.exp(-t / 12)) + r.gauss(0, .008), 'AU'
        elif exp == 'yeast':
            x, y, unit = t, .04 * (1 - math.exp(-t / 30)) + r.gauss(0, .0007), 'g'
        elif exp == 'life':
            x, y, unit = i, 2800 + 10*i + r.gauss(0, 180), 'steps'
        else:  # Galileo's water clock: amount accumulating, drainage rate slightly declining
            x, y, unit = t, max(0, 2.25*t - .0045*t*t + r.gauss(0, .05)), 'g'
        return {'type': 'sample', 'protocol': 'SDL-NDJSON/1', 'node': 'sim-atom-01',
                'boot_id': self.boot_id, 'seq': seq, 'mono_ms': round((time.monotonic()-self.epoch)*1000, 3),
                'x': round(x, 5), 'y': round(y, 6), 'channel': 'primary', 'unit': unit,
                'experiment': exp, 'simulated': True, 'period_ms': round(self.interval*1000)}

    async def client(self, reader, writer):
        async def send(body):
            writer.write(envelope(body).encode('utf-8'))
            await writer.drain()
        peer = writer.get_extra_info('peername')
        print(f'[NODE] Gateway connected: {peer}', flush=True)
        async def tx():
            await send({'type':'hello', 'node':'sim-atom-01', 'boot_id':self.boot_id, 'protocol':'SDL-NDJSON/1', 'simulated':True})
            while True:
                await asyncio.sleep(self.interval)
                body = self.sample()
                if self.drop_every and body['seq'] % self.drop_every == 0:
                    continue  # intentional dropout for diagnostics exercise
                if self.delay_ms:
                    await asyncio.sleep(self.delay_ms / 1000)
                encoded = envelope(body)
                if self.bad_crc_every and body['seq'] % self.bad_crc_every == 0:
                    bad = json.loads(encoded)
                    bad['crc32'] = '00000000'
                    encoded = json.dumps(bad) + '\n'
                writer.write(encoded.encode())
                if self.duplicate_every and body['seq'] % self.duplicate_every == 0:
                    writer.write(encoded.encode())
                await writer.drain()
        task = asyncio.create_task(tx())
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line)
                    if obj.get('type') == 'ping':
                        await send({'type':'pong','id':obj.get('id'),'node':'sim-atom-01',
                                    'boot_id':self.boot_id,'mono_ms':round((time.monotonic()-self.epoch)*1000,3)})
                    elif obj.get('type') == 'select_experiment':
                        name = obj.get('experiment')
                        known = {'measure','dice','deck','mixing','cooling','calorie','tea','yeast','galileo','life'}
                        if name in known:
                            self.experiment = name
                            self.exp_counter = 0
                            await send({'type':'ack','id':obj.get('id'),'ok':True,'experiment':name})
                        else:
                            await send({'type':'ack','id':obj.get('id'),'ok':False,'error':'unsupported experiment'})
                except (ValueError, KeyError):
                    pass
        except (ConnectionError, OSError):
            pass
        finally:
            task.cancel()
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass
            print('[NODE] Gateway disconnected',flush=True)

    async def serve(self):
        server = await asyncio.start_server(self.client, self.host, self.port)
        print(f'[NODE] Synthetic TCP device at {self.host}:{self.port} (SDL-NDJSON/1)', flush=True)
        return server
