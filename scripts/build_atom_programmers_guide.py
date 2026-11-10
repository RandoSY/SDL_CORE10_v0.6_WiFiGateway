"""Build the programmer's PDF from the maintained design record and live source.

Requires ReportLab. Does not access hardware, logs, credentials, or the network.
Source references fail closed when their expected declarations cannot be found.
"""
from __future__ import annotations

import hashlib
import json
import re
import textwrap
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
DESIGN = ROOT / 'docs/08_ATOM_RESPONSIVENESS_DESIGN.md'
OUT = ROOT / 'output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf'
INO = 'arduino/SDL_ATOM_Gateway_Node/SDL_ATOM_Gateway_Node.ino'
MATRIX = 'arduino/SDL_ATOM_Gateway_Node/matrix_status.h'
SERVER = 'gateway/server.py'
JS = 'web/accelerometer.js'
START = 'start_accelerometer.py'
WIDTH = 516
NAVY = colors.HexColor('#16364E')
BLUE = colors.HexColor('#176D9C')
TEAL = colors.HexColor('#147C70')
MUTED = colors.HexColor('#516879')
PALE = colors.HexColor('#EFF5F8')
LINE = colors.HexColor('#CDDDE6')

# key, path, exact declaration/anchor, purpose. Resolve line numbers, never guess.
SPECS = [
    ('period', INO, 'static constexpr uint32_t ACQUIRE_MS', '20 ms acquisition/publication constants'),
    ('reading', INO, 'struct Reading {', 'Timestamped reading and atomic counters nearby'),
    ('acquire', INO, 'void acquisitionTask(void*)', 'Periodic sensor owner; deadline and queue-drop accounting'),
    ('send', INO, 'bool sendBody(', 'CRC envelope and complete local TCP write check'),
    ('publish', INO, 'void sample(', 'Cached RSSI; drain up to eight readings with original identity'),
    ('network', INO, 'void network(', 'Wi-Fi recovery, one peer, bounded command input'),
    ('nodelay', INO, 'peer.stop(); peer = incoming; peer.setNoDelay', 'TCP no-delay for accepted instrument peer'),
    ('button', INO, 'void button(', 'Main-loop 30 ms button debounce'),
    ('display', INO, 'void display(', '50 ms eligibility and changed-frame-only LED writes'),
    ('timing', INO, 'void printStatus(', 'Serial status and since-boot timing counters'),
    ('queue', INO, 'readings = xQueueCreate(', 'Allocate 128-reading FreeRTOS queue'),
    ('task', INO, 'if (!readings || xTaskCreatePinnedToCore', 'Create 4096-byte-stack, priority-2, core-1 sampler'),
    ('radio', INO, 'WiFi.mode(WIFI_STA); WiFi.setSleep(false)', 'Station mode, disabled sleep, auto reconnect'),
    ('loop', INO, 'void loop()', 'Publisher/network/UI ownership and stage maxima'),
    ('phase', MATRIX, 'inline Phase phase(', 'Boot/fault/network state priority'),
    ('matrix', MATRIX, 'inline Matrix render(', 'Pure state-to-pixel decisions and pulse expiry'),
    ('wsinit', SERVER, 'class WSClient:', 'Independent bounded queue per browser'),
    ('wswrite', SERVER, '    async def write_loop(', 'Attach current delivery counts at serialization time'),
    ('wsevict', SERVER, '    def send(self, msg):', 'Evict oldest queued browser message and count losses'),
    ('reset', SERVER, '    def reset_device_observations(', 'Clear stale radio/rate/clock evidence'),
    ('metrics', SERVER, '    def snapshot(', 'Five-second receive rate and link-health definitions'),
    ('log', SERVER, '    def log(self, row):', 'Synchronous best-effort log and replace-based rotation'),
    ('status', SERVER, '    def status(self):', 'Expose browser delivery and configured endpoint'),
    ('parse', SERVER, '    def parse_line(', 'UTF-8 JSON envelope and CRC verification'),
    ('validate', SERVER, '    def valid_device_message(', 'Message shape/type/range checks'),
    ('handle', SERVER, '    def handle_device(', 'Identity, sequence validation, forwarding and logging'),
    ('read', SERVER, '    async def read_device(', 'Bounded complete-line reads and response deadline'),
    ('ping', SERVER, '    async def ping_device(', 'Matching ping/pong supervision'),
    ('connect', SERVER, '    async def connect_device(', 'Connection lifecycle, cancellation and retry'),
    ('heartbeat', SERVER, '    async def heartbeat(', 'One-second diagnostics broadcasts'),
    ('plot', JS, ' function redraw()', 'Latest 60 seconds of active segment, raw point plotting'),
    ('viewstatus', JS, ' function status()', 'Metrics display and five-second functional rest check'),
    ('render', JS, ' function renderView(', '100 ms rendering throttle'),
    ('capture', JS, ' function sample(', 'Validate physical source and append before drawing'),
    ('browserconnect', JS, ' function connect()', 'WebSocket ingestion, delivery deltas and recovery'),
    ('export', JS, ' function metadata()', 'Capture provenance and known-loss metadata'),
    ('buttons', JS, " $('pause').onclick", 'Pause/new-run/export handlers immediately below'),
    ('reuse', START, 'def existing_monitor(', 'Require live matching node/endpoint before reuse'),
    ('usb', START, 'def discover_node(', 'Explicitly optional serial address discovery'),
    ('resolve', START, 'def resolve_node(', 'Explicit host / USB option / saved Wi-Fi settings'),
    ('save', START, 'def save_node(', 'Persist endpoint while preserving other settings'),
    ('start', START, 'async def run(', 'Dedicated log path and port-8799 gateway startup'),
]
SOURCES = {path: (ROOT / path).read_text(encoding='utf-8').splitlines()
           for path in dict.fromkeys(item[1] for item in SPECS)}
REFS = {}
for key, path, needle, purpose in SPECS:
    matches = [i + 1 for i, line in enumerate(SOURCES[path]) if line.lstrip().startswith(needle.lstrip())]
    if len(matches) != 1:
        raise ValueError(f'{path}: expected one anchor {needle!r}, found {len(matches)}')
    REFS[key] = (path, matches[0], purpose)


def ascii_text(text):
    for old, new in {
        '\u2011': '-', '\u2013': '-', '\u2014': ' - ', '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"', '\u2192': ' -> ', '\u2194': ' <-> ',
        '\u2264': '<=', '\u2265': '>=', '\u2248': '~', '\u00b7': ' / ',
    }.items():
        text = text.replace(old, new)
    return text


def uri(target):
    if target.startswith(('https://', 'http://')):
        return target
    path, _, fragment = target.partition('#')
    resolved = (DESIGN.parent / path).resolve()
    if not resolved.exists() and resolved != OUT:
        raise FileNotFoundError(f'Design link target missing: {target}')
    return resolved.as_uri() + ('#' + fragment if fragment else '')


def inline(text):
    """Small explicit Markdown subset used by the design record."""
    parts = re.split(r'(\[[^\]]+\]\([^)]+\)|`[^`]+`|\*\*[^*]+\*\*)', ascii_text(text))
    result = []
    for part in parts:
        if not part:
            continue
        link = re.fullmatch(r'\[([^\]]+)\]\(([^)]+)\)', part)
        if link:
            label, target = link.groups()
            result.append(f'<link href="{escape(uri(target))}" color="#176D9C">{escape(label)}</link>')
        elif part.startswith('`'):
            result.append(f'<font name="Courier" size="8.3">{escape(part[1:-1])}</font>')
        elif part.startswith('**'):
            result.append('<b>' + escape(part[2:-2]) + '</b>')
        else:
            result.append(escape(part))
    return ''.join(result)


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='GuideTitle', fontName='Helvetica-Bold', fontSize=31,
                          leading=35, textColor=NAVY, spaceAfter=14))
styles.add(ParagraphStyle(name='GuideSubtitle', fontSize=14, leading=20, textColor=MUTED, spaceAfter=14))
styles.add(ParagraphStyle(name='GuideH1', fontName='Helvetica-Bold', fontSize=16,
                          leading=20, textColor=NAVY, spaceBefore=17, spaceAfter=9, keepWithNext=True))
styles.add(ParagraphStyle(name='GuideH2', fontName='Helvetica-Bold', fontSize=11.5,
                          leading=15, textColor=BLUE, spaceBefore=10, spaceAfter=5, keepWithNext=True))
styles.add(ParagraphStyle(name='GuideBody', fontSize=9.6, leading=13.4, textColor=NAVY,
                          spaceAfter=8, splitLongWords=True, allowWidows=False, allowOrphans=False))
styles.add(ParagraphStyle(name='GuideSmall', fontSize=8.3, leading=11.4, textColor=MUTED,
                          spaceAfter=6, splitLongWords=True))
styles.add(ParagraphStyle(name='GuideCell', fontSize=8.1, leading=11.1, textColor=NAVY,
                          splitLongWords=True))
styles.add(ParagraphStyle(name='GuideRef', fontSize=8.2, leading=11.2, textColor=BLUE,
                          spaceAfter=8, splitLongWords=True, keepWithNext=True))
styles.add(ParagraphStyle(name='GuideCode', fontName='Courier', fontSize=7.6, leading=10.0,
                          textColor=NAVY, spaceBefore=5, spaceAfter=9))
styles.add(ParagraphStyle(name='GuideTOC', fontSize=10, leading=15, textColor=NAVY,
                          spaceBefore=6, spaceAfter=6, leftIndent=0, firstLineIndent=0))


def para(text, style='GuideBody', markdown=True):
    return Paragraph(inline(text) if markdown else text, styles[style])


story = []
headings = []


def heading(text, level=0):
    p = para(text, 'GuideH1' if level == 0 else 'GuideH2')
    if level == 0:
        p.guide_heading = (ascii_text(text), f'section-{len(headings)}')
        headings.append(p.guide_heading)
    story.append(p)


def table(headers, rows, widths=None, compact=False):
    count = len(headers)
    if widths is None:
        widths = [WIDTH * .42, WIDTH * .58] if count == 2 else [WIDTH * .23, WIDTH * .385, WIDTH * .385]
    data = [[para('**' + h + '**', 'GuideCell') for h in headers]]
    data.extend([[para(str(cell), 'GuideCell') for cell in row] for row in rows])
    t = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), PALE), ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, 0), .7, LINE),
        ('LINEBELOW', (0, 1), (-1, -1), .35, LINE),
        ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
        ('TOPPADDING', (0, 0), (-1, -1), 3 if compact else 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3 if compact else 6),
    ]))
    story.extend([t, Spacer(1, 8)])


def source_ref(keys):
    entries = []
    for key in keys:
        path, line, _ = REFS[key]
        entries.append(f'<link href="{escape((ROOT/path).as_uri())}" color="#176D9C">'
                       f'{escape(path)}</link> <b>L{line}</b> ({escape(key)})')
    story.append(para('<b>Read in source:</b> ' + '<br/>'.join(entries), 'GuideRef', markdown=False))


class Pipeline(Flowable):
    """Compact vector diagram with separate measurement and presentation rates."""
    def __init__(self):
        Flowable.__init__(self)
        self.width, self.height = WIDTH, 150

    def draw(self):
        c = self.canv
        boxes = [
            (0, 86, ['ATOM sampler', '20 ms / 50 Hz']),
            (180, 86, ['ATOM queue + TCP', '128 readings / port 8766']),
            (360, 86, ['Python bridge', 'validate / log / distribute']),
            (360, 8, ['Browser capture', 'every delivered reading']),
            (180, 8, ['Browser chart', 'redraw <=10 times/s']),
            (0, 8, ['CSV / JSON', 'raw timestamps + values']),
        ]
        for x, y, lines in boxes:
            c.setFillColor(PALE); c.setStrokeColor(LINE)
            c.roundRect(x, y, 156, 50, 6, stroke=1, fill=1)
            c.setFillColor(NAVY); c.setFont('Helvetica-Bold', 9)
            c.drawCentredString(x + 78, y + 30, lines[0])
            c.setFont('Helvetica', 8)
            c.drawCentredString(x + 78, y + 15, lines[1])
        c.setStrokeColor(TEAL); c.setFillColor(TEAL); c.setLineWidth(1.3)
        for x in (156, 336):
            c.line(x, 111, x + 24, 111)
            c.line(x + 24, 111, x + 19, 114); c.line(x + 24, 111, x + 19, 108)
        c.line(438, 86, 438, 58); c.line(438, 58, 435, 63); c.line(438, 58, 441, 63)
        c.line(360, 33, 336, 33)
        c.line(336, 33, 341, 36); c.line(336, 33, 341, 30)
        # Exports branch directly from capture, independently of chart redraws.
        c.line(438, 8, 438, 0); c.line(438, 0, 78, 0); c.line(78, 0, 78, 8)
        c.line(78, 8, 75, 3); c.line(78, 8, 81, 3)
        c.setFillColor(MUTED); c.setFont('Helvetica', 8)
        c.drawString(0, 70, 'Device owns measurement time. The browser owns presentation time.')


class GuideDoc(BaseDocTemplate):
    def afterFlowable(self, flowable):
        if hasattr(flowable, 'guide_heading'):
            text, bookmark = flowable.guide_heading
            self.canv.bookmarkPage(bookmark)
            self.canv.addOutlineEntry(text, bookmark, 0, closed=False)
            self.notify('TOCEntry', (0, text, self.page, bookmark))


def footer(canvas, doc):
    canvas.saveState()
    if doc.page > 1:
        canvas.setStrokeColor(LINE); canvas.line(48, 751, 564, 751)
        canvas.setFont('Helvetica', 8); canvas.setFillColor(MUTED)
        canvas.drawString(48, 761, 'ATOM MATRIX 1.0 / PROGRAMMER\'S GUIDE / FIRMWARE 0.6.4')
    canvas.setStrokeColor(LINE); canvas.line(48, 43, 564, 43)
    canvas.setFont('Helvetica', 8); canvas.setFillColor(MUTED)
    canvas.drawString(48, 29, 'SDL CORE 10 / 2026-11-09 / source references resolved at generation')
    canvas.drawRightString(564, 29, f'{doc.page}')
    canvas.restoreState()


# Cover and reader navigation.
story.append(Spacer(1, 32))
story.append(para('ATOM MATRIX 1.0', 'GuideTitle'))
story.append(para("Programmer's guide<br/>and source reference", 'GuideTitle', markdown=False))
story.append(para('How a fixed-rate sampler, bounded queues and deliberate browser rendering produced a responsive 50 Hz instrument.', 'GuideSubtitle'))
story.append(Spacer(1, 12))
story.append(Pipeline())
table(['Working result', 'Scope'], [
    ('50.00 Hz physical acquisition and receipt', '751 samples / 15.02 s; zero measured gaps, skips, drops or CRC/parse errors in that window'),
    ('Browser responsiveness accepted by user', 'Improved snap and a solid displayed 50 Hz; browser latency percentiles were not measured'),
    ('Independent operation over Wi-Fi', 'Normal host startup uses saved settings; USB is optional for setup and diagnostics'),
], [205, 311])
story.append(para('Revision 1 / November 9, 2026\nHardware: original ATOM Matrix 1.0 / ESP32-PICO-D4 / MPU6886', 'GuideSmall'))
story.append(para('Includes exact file/line navigation, numbered source excerpts, overflow semantics, test evidence, operating commands and source fingerprints. Historical validation PDF remains separate.', 'GuideSmall'))
story.append(PageBreak())
heading('Reading map')
story.append(para('Start with sections 1-3 for the architecture and device timing. Sections 5-6 explain the PC/browser path. Appendix A is the source lookup index; Appendix B shows the key lines in context. Appendix C gives working commands; Appendix D identifies this source snapshot.'))
story.append(para('All source paths are relative to this project root:', 'GuideSmall'))
story.append(para(str(ROOT), 'GuideSmall'))
story.append(para('L71 means line 71 in the named file, counting from one. Printed references are resolved from the actual source on each generation; file links open the local source, and the printed line identifies where to navigate in an editor. Moving the project can invalidate absolute PDF file links; the printed relative paths remain usable.', 'GuideSmall'))
toc = TableOfContents()
toc.levelStyles = [styles['GuideTOC']]
story.append(toc)
story.append(PageBreak())

CHAPTER_REFS = {
    '1.': ['network', 'start', 'browserconnect'],
    '2.': ['period', 'task', 'render'],
    '3.': ['acquire', 'queue', 'publish', 'loop'],
    '4.': ['phase', 'matrix', 'display'],
    '5.': ['connect', 'wsevict', 'handle', 'log'],
    '6.': ['capture', 'render', 'viewstatus', 'export'],
    '7.': ['timing', 'metrics'],
    '8.': ['resolve', 'usb', 'reuse', 'status'],
    '9.': ['reading', 'acquire', 'render'],
    '10.': [],
}


def markdown_body():
    lines = DESIGN.read_text(encoding='utf-8').splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('# '):
            i += 1
            continue
        if line.startswith('## '):
            title = line[3:]
            heading(title)
            keys = CHAPTER_REFS.get(title.split(' ', 1)[0], [])
            if keys:
                source_ref(keys)
            i += 1
        elif line.startswith('### '):
            heading(line[4:], 1)
            i += 1
        elif line.startswith('```'):
            language = line[3:]
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                block.append(lines[i]); i += 1
            i += 1
            if language == 'mermaid':
                story.append(Pipeline())
            else:
                story.append(Preformatted(ascii_text('\n'.join(block)), styles['GuideCode']))
        elif line.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [cell.strip() for cell in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', cell) for cell in cells):
                    rows.append(cells)
                i += 1
            table(rows[0], rows[1:])
        else:
            paragraph = [line]
            i += 1
            if not re.match(r'^\d+\. ', line):
                while i < len(lines) and lines[i].strip() and not lines[i].startswith(('#', '|', '```')):
                    paragraph.append(lines[i].strip()); i += 1
            story.append(para(' '.join(paragraph)))


markdown_body()
story.append(PageBreak())
heading('Appendix A. Exact source lookup')
story.append(para('Use these starting lines in the current snapshot. Functions may extend beyond the listed line; purpose text explains what to inspect. The generator rejects missing or ambiguous declaration anchors. Appendix D records the corresponding file fingerprints.'))
for path in SOURCES:
    heading(path, 1)
    rows = [(f'L{line} / `{key}`', purpose) for key, (refpath, line, purpose) in REFS.items() if refpath == path]
    table(['Start line / lookup key', 'What lives here'], rows, [145, 371], compact=True)

story.append(PageBreak())
heading('Appendix B. The important code in context')
story.append(para('These excerpts are copied from the source at generation time, not independently reimplemented examples. Long lines wrap with an indented continuation; only the first display line carries the original source line number.'))


def excerpt(title, key, count, offset=0):
    path, line, _ = REFS[key]
    start = line + offset
    output = []
    for number in range(start, min(start + count, len(SOURCES[path]) + 1)):
        wrapped = textwrap.wrap(ascii_text(SOURCES[path][number - 1]), width=93,
                                replace_whitespace=False, drop_whitespace=False) or ['']
        output.append(f'{number:>4} | {wrapped[0]}')
        output.extend('     |     ' + continuation for continuation in wrapped[1:])
    block = [para(title, 'GuideH2'),
             para(f'`{path}` / L{start}-L{start + count - 1}', 'GuideSmall'),
             Preformatted('\n'.join(output), styles['GuideCode'])]
    story.append(KeepTogether(block))


excerpt('B1. Fixed schedule and explicit missed-period accounting', 'acquire', 17)
excerpt('B2. Actual acquisition, nonblocking queue send and overflow count', 'acquire', 10, 16)
excerpt('B3. Queue/task allocation and radio setup', 'queue', 6)
story.append(para('The I2C work stays in the sampler; the zero-wait queue send prevents TCP backpressure from turning into a sampler wait. The sampler and publishing loop are separate tasks, not necessarily separate cores.'))
excerpt('B4. Capture first, draw only when due', 'render', 17)
story.append(para('In `sample()`, `points.push(lastSample)` precedes `renderView()`. The 100 ms gate controls presentation work after retention, preserving 50 Hz ingestion.'))
excerpt('B5. A slow browser loses its oldest queued item explicitly', 'wsevict', 11)
excerpt('B6. Skip redundant LED writes', 'display', 12)

story.append(PageBreak())
heading('Appendix C. Run, inspect, test and recall')
story.append(para('Run commands from the project root. None of the following commands flashes firmware. [RUNBOOK.md](../RUNBOOK.md) is the maintained build/flash reference; this guide documents the responsive design.'))
heading('C1. Normal operation: Wi-Fi only', 1)
story.append(Preformatted('.\\START_ACCELEROMETER.bat\n# Or, without automatically opening a browser:\npy -3 start_accelerometer.py --port 8799\n\n# Save the current endpoint (substitute a new host when needed):\n.\\START_ACCELEROMETER.bat --node-host 192.168.0.213 --save-node', styles['GuideCode']))
story.append(para('Monitor: http://127.0.0.1:8799/accelerometer.html\nStatus: http://127.0.0.1:8799/api/status\nCurrent node: 192.168.0.213:8766. Check `connected`, `node_host`, sample count, rate, error counters, log state and browser delivery counts. An already-running process retains its startup endpoint.'))
heading('C2. Automated regression suites', 1)
story.append(Preformatted('py -3 -B -m unittest discover -s tests -q\nnode --test tests/test_accelerometer.cjs tests/test_browser_delivery.cjs', styles['GuideCode']))
story.append(para('Recorded results: 35 Python tests and 9 JS tests passed. Python was 3.14 and Node was 22.20 in this workspace. Ordinary gateway runtime is standard-library Python; Node is needed for these JS tests and the measurement helper.'))
heading('C3. Evidence and optional physical diagnostics', 1)
story.append(Preformatted('node scripts/measure_accelerometer.cjs --history\nnode scripts/measure_accelerometer.cjs my-50hz-check\n\n# Explicit USB setup only; not needed for normal operation:\n.\\START_ACCELEROMETER.bat --discover-usb --serial-port COM30 --save-node\n\n# Direct node reconnect test; stop the live monitor first:\npy -3 -B scripts/check_atom_node.py --port COM30 --serial-seconds 2 --seconds 30', styles['GuideCode']))
story.append(para('The WebSocket measurement uses the running monitor gateway, captures 15 seconds through actual monitor JS and attempts serial timing snapshots. Its full pass requires readable before/after sampler counters, so no USB timing evidence cannot certify its complete acceptance criteria. Serial helpers need pyserial and COM30 free. The direct reconnect bench occupies the ATOM single-peer slot; never run it alongside the live node connection.'))
heading('C4. Regenerate this guide', 1)
story.append(Preformatted('py -3 -B scripts/build_atom_programmers_guide.py\npdftoppm -r 100 -png output/pdf/ATOM_Matrix_1_0_Programmers_Guide.pdf '
                          'tmp/pdfs/atom-guide', styles['GuideCode'], maxLineLength=95, splitChars=' '))
story.append(para('Requires ReportLab; rendering requires Poppler. Inspect the rendered pages before delivering a new edition. The guide is generated from `docs/08_ATOM_RESPONSIVENESS_DESIGN.md` plus current source anchors/excerpts; update the explanation when behavior changes, then regenerate and verify.'))

story.append(PageBreak())
heading('Appendix D. Snapshot identity and evidence scope')
story.append(para('This project is not currently a Git repository. These SHA-256 fingerprints identify the main source files used for printed references in this edition; they are not a complete toolchain/dependency or reproducible-build manifest. Generated PDFs are reference artifacts, not firmware backups.'))
for path in [*SOURCES, 'web/accelerometer.html', 'web/accelerometer.css',
             'START_ACCELEROMETER.bat', 'accelerometer_settings.json',
             'scripts/measure_accelerometer.cjs', 'scripts/check_atom_node.py']:
    if path == 'accelerometer_settings.json' and not (ROOT / path).exists():
        story.append(para('Local endpoint settings are absent from this checkout and are intentionally not published; their fingerprint is omitted.', 'GuideSmall'))
        continue
    digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    story.append(para('`' + path + '`', 'GuideSmall'))
    story.append(Preformatted(digest, styles['GuideCode']))
records = [json.loads(line) for line in (ROOT/'experiments/atom-performance.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
baseline = next(record for record in records if record.get('label') == '0.6.4-freertos')
current_hash = hashlib.sha256((ROOT / INO).read_bytes()).hexdigest()
story.append(para('The current sketch ' + ('matches' if current_hash == baseline['source_sha256'] else 'DOES NOT MATCH') + ' the source fingerprint in the original 0.6.4 timed physical PASS. That comparison covers the sketch file only; other source/dependency changes require their own validation.', 'GuideSmall'))
story.append(para('Original timed-measurement firmware binary SHA-256:', 'GuideSmall'))
story.append(Preformatted(baseline['binary_sha256'], styles['GuideCode']))
story.append(para('Evidence: `experiments/atom-performance.jsonl`; original record time `' + baseline['at'] + '`. Later records include uncontrolled since-boot counters, the forced-reconnect test, Wi-Fi-only recovery and operator acceptance. Treat each counter according to its stated scope. Do not interpret all records as equivalent timed benchmarks.', 'GuideSmall'))
story.append(para('Local credential header contents and firmware binary contents are not included. This guide was generated by `scripts/build_atom_programmers_guide.py` from the maintained Markdown design record. No hardware access is performed during generation.', 'GuideSmall'))


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Link validation above accepts the PDF self-reference on the first build.
    doc = GuideDoc(str(OUT), pagesize=(612, 792), leftMargin=48, rightMargin=48,
                   topMargin=54, bottomMargin=57,
                   title="ATOM Matrix 1.0 - Programmer's Guide and Source Reference",
                   author='SDL Engineering', subject='FreeRTOS acquisition, TCP gateway and responsive browser telemetry')
    frame = Frame(48, 57, WIDTH, 681, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(PageTemplate(id='guide', frames=[frame], onPage=footer))
    doc.multiBuild(story)
    print(f'Generated {OUT} ({len(REFS)} resolved source references)')


if __name__ == '__main__':
    main()
