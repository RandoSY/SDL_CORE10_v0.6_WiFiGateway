/* Behavior tests for the actual browser scripts using Node's built-in test/VM APIs.
 * The DOM/WebSocket substitutes test state and exports, not browser rendering.
 * Run: node --test tests/test_browser_delivery.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function dashboard(saved = new Map()) {
  const elements = new Map();
  class Element {
    constructor(tag = 'div') {
      this.tagName = tag;
      this.children = [];
      this.dataset = {};
      this.value = '';
      this.hidden = false;
      this.textContent = '';
      const classes = new Set();
      this.classList = {
        add: name => classes.add(name), remove: name => classes.delete(name),
        contains: name => classes.has(name),
        toggle(name, on = !classes.has(name)) { on ? classes.add(name) : classes.delete(name); }
      };
    }
    set id(id) { this._id = id; elements.set(id, this); }
    get id() { return this._id; }
    appendChild(child) { this.children.push(child); return child; }
    append(...children) { children.forEach(child => this.appendChild(child)); }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    setAttribute() {}
    addEventListener() {}
    closest() { return null; }
    getBoundingClientRect() { return {width: 0, height: 0}; }
    click() { this.onclick?.(); }
  }
  const document = {
    getElementById(id) {
      if (!elements.has(id)) { const element = new Element(); element.id = id; }
      return elements.get(id);
    },
    createElement: tag => new Element(tag),
    querySelectorAll: () => [],
    querySelector: selector => document.getElementById(selector)
  };
  for (const [id, value] of Object.entries({'cal-scale': '1', 'cal-offset': '0', 'sample-field': 'y'})) {
    document.getElementById(id).value = value;
  }
  const listeners = new Map();
  const window = {
    addEventListener(type, callback) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(callback);
    },
    dispatchEvent(event) { for (const callback of listeners.get(event.type) || []) callback(event); }
  };
  const sockets = [];
  class WebSocket {
    static OPEN = 1;
    constructor() { this.readyState = 1; sockets.push(this); queueMicrotask(() => this.onopen?.()); }
    send() {}
    close() { this.readyState = 3; this.onclose?.(); }
    message(message) { this.onmessage({data: JSON.stringify(message)}); }
  }
  let exported;
  const context = vm.createContext({
    window, document, WebSocket, console, Blob,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    localStorage: {getItem: key => saved.get(key) || null, setItem: (key, value) => saved.set(key, value)},
    performance: {now: () => 1000}, requestAnimationFrame() {},
    setTimeout() { return 0; }, clearTimeout() {}, setInterval() {}, clearInterval() {},
    URL: {createObjectURL(blob) { exported = blob; return 'blob:test'; }, revokeObjectURL() {}},
    confirm: () => true
  });
  for (const script of ['analysis.js', 'comms.js', 'core10.js', 'app.js', 'wifi_diagnostics.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'web', script), 'utf8'), context, {filename: script});
  }
  return {
    get: id => document.getElementById(id), window, sockets, saved,
    exported: () => exported,
    async connect() {
      const select = document.getElementById('live-adapter');
      select.onchange({target: {value: 'gateway'}});
      await document.getElementById('plugin-connect').onclick();
      return sockets.at(-1);
    }
  };
}

test('delivery loss flags capture, survives archive/reload and appears in CSV/JSON', async () => {
  const app = dashboard();
  const socket = await app.connect();
  const delivery = dropped => ({client_id: 'browser-A', dropped_messages: dropped, dropped_samples: dropped});
  // Loss while paused establishes a baseline, not a warning for a future run.
  socket.message({type: 'sdl.metrics', delivery: delivery(4), payload: {connected: true}});
  app.get('live-start').onclick();
  socket.message({type: 'sdl.metrics', delivery: delivery(7), payload: {connected: true}});
  for (const seq of [1, 2]) socket.message({
    type: 'sdl.sample', delivery: delivery(7),
    payload: {x: seq, y: seq * 2, simulated: true}
  });
  assert.equal(app.get('capture-warning').hidden, false);
  assert.match(app.get('capture-warning').textContent, /3 browser sample delivery drops/);
  assert.equal(app.window.SDLPrototype.getState().points, 2);
  app.get('live-stop').onclick();
  app.get('live-save').onclick();
  const runs = JSON.parse(app.saved.get('sdl-core10-v05-archive'));
  assert.equal(runs[0].browser_dropped_samples, 3);
  assert.match(app.get('archive-list').children[0].children[0].textContent, /DELIVERY LOSS/);
  app.get('analysis-csv').onclick();
  const csv = await app.exported().text();
  const rows = csv.split('\n').map(row => row.split(','));
  const column = rows[0].indexOf('"browser_dropped_samples"');
  assert.ok(column >= 0);
  assert.equal(rows[1][column], '3');
  app.get('archive-backup').onclick();
  const backup = await app.exported().text();
  assert.equal(JSON.parse(backup).runs[0].browser_dropped_samples, 3);
  const imported = dashboard();
  await imported.get('import-json-file').onchange({target: {files: [{text: async () => backup}], value: 'backup.json'}});
  const importedRuns = JSON.parse(imported.saved.get('sdl-core10-v05-archive'));
  assert.equal(importedRuns[0].browser_dropped_samples, 3);
  // Reload uses the real sanitizer and Archive Load action.
  const reloaded = dashboard(app.saved);
  reloaded.get('archive-list').children[0].children[4].children[0].onclick();
  assert.match(reloaded.get('capture-warning').textContent, /3 browser sample delivery drops/);
  reloaded.get('live-clear').onclick();
  assert.equal(reloaded.get('capture-warning').hidden, true);
});

test('new runs reset warnings and paused delivery loss is not charged twice', async () => {
  const app = dashboard();
  const socket = await app.connect();
  const message = count => ({type: 'sdl.metrics', delivery: {dropped_samples: count}, payload: {connected: true}});
  app.get('live-start').onclick();
  socket.message(message(2));
  assert.match(app.get('capture-warning').textContent, /2 browser sample delivery drops/);
  app.get('live-stop').onclick();
  socket.message(message(5));
  app.get('live-start').onclick();
  assert.equal(app.get('capture-warning').hidden, true);
  socket.message(message(5));
  assert.equal(app.get('capture-warning').hidden, true);
  socket.message(message(6));
  assert.match(app.get('capture-warning').textContent, /1 browser sample delivery drops/);
});

test('diagnostics distinguish upstream health, browser loss and logging failure', async () => {
  const app = dashboard();
  const socket = await app.connect();
  socket.message({type: 'sdl.metrics', delivery: {dropped_messages: 3, dropped_samples: 2}, payload: {
    connected: true, node: 'node-A', app_link_health_score: 100,
    logging_ok: false, log_errors: 1, last_log_error: 'disk full'
  }});
  assert.match(app.get('diag-status').textContent, /CHECK WARNINGS/);
  assert.equal(app.get('diag-health').textContent, '100/100');
  assert.match(app.get('diag-detail').textContent, /this browser dropped 2 samples/);
  assert.match(app.get('diag-detail').textContent, /LOGGING FAILED: disk full/);
});
