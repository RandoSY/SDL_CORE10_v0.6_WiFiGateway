"""Generate the formal report from the recorded physical measurement ledger."""
from pathlib import Path
import hashlib
import json
import re
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'output' / 'pdf' / 'ATOM_Matrix_1_0_50Hz_Validation_Report.pdf'
records = [json.loads(line) for line in (ROOT/'experiments/atom-performance.jsonl').read_text().splitlines() if line.strip()]
r = next(item for item in reversed(records) if item['label'] == '0.6.4-freertos' and item['passed'])
b = next(item for item in records if item['label'] == '0.6.3-coupled')
for file, key in [('arduino/SDL_ATOM_Gateway_Node/SDL_ATOM_Gateway_Node.ino','source_sha256'),
                  ('artifacts/atom-bin/SDL_ATOM_Gateway_Node.ino.bin','binary_sha256')]:
    assert hashlib.sha256((ROOT/file).read_bytes()).hexdigest() == r[key], 'Recorded source/build fingerprint changed'

NAVY=colors.HexColor('#15354F'); BLUE=colors.HexColor('#1C6F9F'); MUTED=colors.HexColor('#526B7F')
PALE=colors.HexColor('#EDF4F8'); LINE=colors.HexColor('#CFDCE6'); GREEN=colors.HexColor('#176C50')
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='ReportTitle',fontName='Helvetica-Bold',fontSize=27,leading=31,textColor=NAVY,spaceAfter=8))
styles.add(ParagraphStyle(name='ReportSub',fontName='Helvetica',fontSize=11,leading=15,textColor=MUTED,spaceAfter=12))
styles.add(ParagraphStyle(name='Section',fontName='Helvetica-Bold',fontSize=13,leading=17,textColor=NAVY,spaceBefore=10,spaceAfter=6,keepWithNext=True))
styles.add(ParagraphStyle(name='BodyTextReport',fontName='Helvetica',fontSize=9,leading=12,textColor=NAVY,spaceAfter=6))
styles.add(ParagraphStyle(name='SmallReport',fontName='Helvetica',fontSize=8,leading=11,textColor=MUTED,spaceAfter=6))
styles.add(ParagraphStyle(name='CodeReport',fontName='Courier',fontSize=7.3,leading=10,textColor=NAVY,spaceAfter=7,wordWrap='CJK'))
story=[]
def p(text,style='BodyTextReport'):
    return Paragraph(text,styles[style])
def add(text,style='BodyTextReport'):
    story.append(p(text,style))
def section(text): add(text,'Section')
def table(headers,rows,widths):
    data=[[p(escape(str(x)),'SmallReport') for x in headers]]
    data.extend([[p(escape(str(x)),'BodyTextReport') for x in row] for row in rows])
    t=Table(data,colWidths=widths,hAlign='LEFT',repeatRows=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),PALE),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LINEBELOW',(0,0),(-1,0),.7,LINE),('LINEBELOW',(0,1),(-1,-1),.35,LINE),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),3)]))
    story.append(t)
def callout(text):
    t=Table([[p(text)]],colWidths=[504]);t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),PALE),('BOX',(0,0),(-1,-1),.6,LINE),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.append(t)

add('ATOM MATRIX 1.0','ReportTitle')
add('50 Hz telemetry validation report','ReportTitle')
add('SDL CORE 10 / Wi-Fi Gateway | Firmware 0.6.4 | Report SDL-ATOM-50HZ-20261108','ReportSub')
callout('<b>RESULT: PASS - short physical functional test.</b><br/>751 accepted samples over 15.02 seconds. Measured acquisition and receipt rate: <b>50.00 Hz</b>. No sequence gaps, sampler skips, queue overflows, CRC/parse errors, or test-client delivery drops were recorded in this window.')
section('1. Scope and configuration')
table(['Item','Verified configuration'],[
 ('Hardware','Original M5Stack ATOM Matrix release 1.0; ESP32-PICO-D4; MPU6886; USB COM30'),
 ('Firmware','0.6.4; FreeRTOS sampler, 20 ms period, priority 2 on core 1; 128-reading queue'),
 ('Toolchain','Arduino CLI; M5Stack ESP32 core 3.3.8; Adafruit NeoPixel 1.15.5; Python 3.14; Node 22.20'),
 ('Data path','ATOM 192.168.0.214:8766 TCP server -> Python gateway -> WebSocket -> monitor on PC port 8799'),
 ('Measurement','Acceleration magnitude in milli-g (mg); original device timestamps in ms; simulated=false'),
 ('Evidence time',r['at']+' UTC record; local date 8 November 2026, America/Indianapolis')],[112,392])
section('2. Measured acceptance results')
table(['Criterion','Observed','Verdict'],[
 ('Device / receive rate',f"{r['device_rate_hz']:.2f} / {r['receiver_rate_hz']:.2f} Hz",'PASS'),
 ('Device interval median / p95 / maximum','20 / 20 / 20 ms','PASS'),
 ('Sequence gaps / sampler skips / queue drops','0 / 0 / 0','PASS'),
 ('CRC / parse / test-client delivery drops','0 / 0 / 0','PASS'),
 ('Stationary functional check','Mean 1017.6 mg; SD 2.7 mg','PASS')],[232,204,68])
add('The live monitor reported a 50.2 Hz five-second rolling count. Small 49.8/50.2-style variations are compatible with a 50 Hz stream because window boundaries include discrete samples. Device timing was measured at millisecond resolution.','SmallReport')
add('This is not a calibration certificate, hard real-time guarantee, extended soak test, or vibration-response validation. Only acceleration magnitude is transmitted.','SmallReport')

story.append(PageBreak())
add('Architecture and improvement','ReportTitle')
section('3. Change from the previous firmware')
add('The earlier shared loop performed acquisition, frame construction/TCP writes, LED updates and button/serial work sequentially. A slow publishing operation could therefore skip acquisition deadlines. CRC remained correct while sample continuity degraded.')
add('Firmware 0.6.4 moves sensor reads into a periodic FreeRTOS task. Original timestamps and sequence numbers pass through a bounded queue to the existing publishing loop. No synthetic catch-up samples are generated. Queue overflow drops a reading explicitly and increments a counter; sequence identity exposes the gap downstream.')
table(['Stage','Current responsibility'],[
 ('Acquisition task','Read MPU6886 every 20 ms; timestamp and sequence real readings; count skipped deadlines and queue-full drops.'),
 ('128-reading queue','Nominal 2.56 s of buffering at 50 Hz; ordering preserved; volatile RAM only.'),
 ('Existing main loop','TCP publishing and ping/pong; buttons and serial diagnostics; display image updates only when changed.'),
 ('Browser monitor','Capture all received readings up to 4096 retained rows; plot latest 60 s with rendering capped at 10 Hz. Export raw ms/mg with identity and loss counters.')],[126,378])
section('4. Before / after evidence')
table(['Version / observation','Rate','Sequence gaps'],[
 ('0.6.3 coupled loop: last 500 logged readings',f"{b['device_rate_hz']:.2f} Hz",str(b['sequence_gaps'])),
 ('0.6.4 FreeRTOS: 751 samples / 15.02 s','50.00 Hz','0')],[330,90,84])
add('These are different observation windows, not a controlled equal-duration benchmark. Earlier rolling snapshots also fell near 40-42 samples/s. The defensible improvement is that the current short test met the 50 Hz target without the gaps observed in the reconstructed baseline.','SmallReport')
section('5. Timing instrument findings')
table(['Stage','Largest observed time since boot'],[
 ('Sensor read','2.232 ms'),('Network command handling','3.716 ms'),('Display update','1.143 ms'),('Publishing batch','1962.551 ms')],[260,244])
add('These maximum counters were unchanged before and after the measured window: the long publishing stall was observed earlier in this boot, not newly during the 15-second test. The publishing stage includes JSON construction and TCP writes; instrumentation does not isolate the socket call alone.','SmallReport')
callout('<b>Important distinction:</b> acquisition cadence is now isolated from publishing stalls. Transmission latency, button response and UI latency are not thereby guaranteed. The finite buffer can still overflow during longer or compounded stalls.')

story.append(PageBreak())
add('Reproducibility and limits','ReportTitle')
section('6. Build, flash and test evidence')
add('Build: <b>PASS</b>, 992,649 bytes program (31% of selected application capacity); 49,016 bytes globals. Existing vendor pin-macro redefinition warnings were recorded. Flash: <b>PASS</b> on COM30 at 115200 baud; written-image hashes verified. NVS was not erased. Physical sensor and network test: <b>PASS</b> within the recorded window.')
add('The actual monitor JavaScript processed the physical WebSocket stream using DOM substitutes. Nine JavaScript behavior tests passed, including high-rate capture, five-second stationary checking, source rejection, exports and explicit buffer eviction. The user reported a steadier 50 Hz display and previously observed green matrix feedback. Automated graphical layout validation was unavailable.')
add('Reproduce the physical measurement and recall its ledger:')
add('node scripts/measure_accelerometer.cjs 0.6.4-freertos<br/>node scripts/measure_accelerometer.cjs --history','CodeReport')
add('Requires the gateway on port 8799, Node 22+, Python with pyserial, and COM30 free. The script records 15 seconds and USB timing counters. Results append to <b>experiments/atom-performance.jsonl</b>. See RUNBOOK.md for build, flash and launch commands.')
section('7. Provenance')
add('Firmware source: arduino/SDL_ATOM_Gateway_Node/SDL_ATOM_Gateway_Node.ino','CodeReport')
add('Source SHA-256:<br/>'+r['source_sha256'],'CodeReport')
add('Application image SHA-256:<br/>'+r['binary_sha256'],'CodeReport')
add('Measurement boot ID: '+r['boot_id']+'. The generator checked both current source and binary against these recorded fingerprints. The workspace was not a Git repository, so no commit ID is asserted. Network credentials are intentionally excluded from this report.','SmallReport')
section('8. Remaining validation')
for text in [
 'Run a longer soak test and compare delivered count, queue/skipped counters, latency percentiles and reconnect behavior under realistic interference.',
 'Measure physical button and LED response latency during a publishing stall. Their servicing remains in the main loop.',
 'Validate calibrated scale, orientation response, filtering and aliasing before claiming metrology or vibration performance.',
 'Initial cached RSSI is not meaningful before refresh. The -72 dBm result is node-reported; median application RTT was 9.89 ms, not an independent RF measurement.',
 'Monitor retention is finite (4096 rows, about 82 s at 50 Hz); export important captures. Gateway logs retain current plus one previous 20 MiB file.',
 'No M5Stick S3, ATOM 1.1, ESP32-C3 or C6 application was modified or validated. This result is for the original ATOM Matrix 1.0 only.'
]:add('- '+text)
section('Engineering conclusion')
add('<b>The FreeRTOS acquisition/queue change is a verified functional improvement for this ATOM workload.</b> It meets the requested 50 Hz stream rate in the measured window with no observed sample continuity or validation errors. Keep the timing and queue counters in place; longer-duration and response-latency claims require further measurement.')

def page(canvas,doc):
    canvas.setStrokeColor(LINE);canvas.line(54,42,558,42)
    canvas.setFillColor(MUTED);canvas.setFont('Helvetica',8)
    canvas.drawString(54,29,'SDL | ATOM Matrix 1.0 | 50 Hz validation | 0.6.4')
    canvas.drawRightString(558,29,f'{doc.page}')

OUT.parent.mkdir(parents=True,exist_ok=True)
doc=SimpleDocTemplate(str(OUT),pagesize=(612,792),leftMargin=54,rightMargin=54,topMargin=42,bottomMargin=54,
    title='ATOM Matrix 1.0 - 50 Hz Telemetry Validation',author='SDL Engineering',subject='Physical FreeRTOS acquisition and telemetry validation')
doc.build(story,onFirstPage=page,onLaterPages=page)
print(OUT)
