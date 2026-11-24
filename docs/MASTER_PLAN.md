# ModelMate — แผนหลักสำหรับ implementation

สถานะ: แผนงาน ไม่ใช่การรับรองว่าฟังก์ชันทั้งหมดทำงานแล้ว
ฐานโค้ดขณะเขียน: `66994ef` — doctor, live verification harness และ offline tests 13 รายการ

## 1. วิธีใช้แผนนี้

เอกสารนี้แบ่งงานให้โมเดลขนาดเล็กทำทีละใบงาน โดยไม่ต้องออกแบบระบบใหม่เอง
อ่าน sections 1–6 แล้วอ่านเฉพาะใบงานที่ได้รับและไฟล์ที่เกี่ยวข้อง
`DESIGN.md` คือข้อกำหนดที่ตกลงกับผู้ใช้; แผนนี้กำหนดวิธีส่งมอบและการพิสูจน์
ถ้าพบความขัดแย้งต้องบอก ไม่ใช้แผนเป็นเหตุลดทอนข้อกำหนด

สถานะที่อนุญาต: TODO, IN_PROGRESS, MOCK_VERIFIED, LIVE_VERIFIED, BLOCKED, DONE
DONE ของใบงานพัฒนาไม่ได้หมายความว่า live gate ผ่าน
ทุกสถานะที่อ้างผลตรวจต้องมีคำสั่ง ผล และข้อจำกัดรองรับ

เป้าหมายสุดท้าย: `sr` เป็นแชต Terminal ที่เลือก workflow, model และ effort
ผ่าน ChatGPT/Codex subscription โดยอัตโนมัติตามโหมดและสิทธิ์ที่ผู้ใช้เลือก

## 2. ข้อกำหนดที่ห้ามเปลี่ยนเอง

| ID | ข้อกำหนด | งานที่รับผิดชอบ |
| --- | --- | --- |
| R01 | ใช้ ChatGPT/Codex เท่านั้น ไม่ใช้ API key หรือซื้อเครดิต | P01, P04, P16 |
| R02 | แชตต่อเนื่อง รับ prompt เริ่มต้นได้ และ help เปิดได้โดยไม่ล็อกอิน | P08, P15 |
| R03 | รองรับงานโค้ด วิเคราะห์ วางแผน และเอกสาร | P06, P10, P16 |
| R04 | เลือกตัวที่คาดว่าผ่านเกณฑ์ ใช้ตัวเก่งเฉพาะจุดยาก/เสี่ยง | P05, P06, P16 |
| R05 | Auto / Ask to escalate / Approve plan; default Ask to escalate | P07 |
| R06 | เลือกสิทธิ์ได้; default read-only + on-request ตาม Codex; คำสั่งที่ sandbox อนุญาตรันเองได้ | P03, P09 |
| R07 | แก้แล้วตรวจซ้ำไม่เกิน 2 รอบต่อขั้นก่อนหยุดถาม | P10 |
| R08 | ตัวเก่งตรวจเฉพาะงานซับซ้อน/เสี่ยง | P06, P10 |
| R09 | เซฟ local แยกโปรเจกต์ เลือก resume และลบได้ | P11, P12 |
| R10 | ค้นเว็บเมื่อจำเป็น อ้างอิง ถามก่อนส่งข้อมูลส่วนตัวเป็นคำค้น | P13 |
| R11 | โควตาหมดหรือไม่ทราบ: พัก; ตรวจใหม่หลัง reset | P04, P12 |
| R12 | แสดงเวลารวม โมเดลจริงที่ทราบ และ usage โดยไม่แต่งตัวเลข | P14 |
| R13 | runtime Python ไฟล์เดียว; ติดตั้งและเรียก sr บน Linux/WSL2 | P02, P15 |

ไม่รวม: ผู้ให้บริการอื่น, งานขนานหลาย agent, web UI, cloud sync, vector memory,
plugin marketplace, จัดการ billing, streaming reasoning ภายในโมเดล

## 3. Release gates และข้อจำกัดที่ต้องแก้ก่อน

### G1 — เชื่อมบัญชีและส่งต่องาน

ต้องมีหลักฐานสดของ login, catalog, quota, model/effort override และ context recall
จาก Terminal ปกติ ปัจจุบันตรวจ source/schema และ mocks แล้ว แต่ live ยังไม่ผ่าน
`/status` ที่ผู้ใช้ส่งมายืนยันบัญชีได้ ไม่แทนการทดสอบ App Server ของโปรแกรม

### G2 — บังคับสิทธิ์ก่อนลงมือ

อัปเดตตามผู้ใช้เลือก native Codex policy เมื่อ 2026-11-17:
ใช้ read-only + on-request; ไม่บังคับถามก่อนคำสั่งที่ sandbox อนุญาต
ต้องพิสูจน์ว่า server-requested approval แสดง command/diff ได้และตอบเฉพาะ
คำขอที่ตรงกับ active thread/turn/token; deny/EOF/cancel ไม่เป็น accept
ห้ามยกระดับ workspace/full-access เอง และคง managed restrictions ที่เข้มกว่า
คำขอที่ไม่รองรับต้องหยุด/ปฏิเสธโดยไม่อนุมัติ
User ยอมรับ native readable roots; ไม่อ้าง project-only isolation ที่ไม่ได้บังคับ
Manual live prototype เปิด opt-in ได้ตามนโยบายใหม่ แต่ไม่ถือว่า G2 ทั้งหมดผ่าน
Auto workflow และ private web isolation ยังมี gates แยก; decision classifier ถูกตัดจาก scope

### G3 — การค้นเว็บไม่รับข้อมูลส่วนตัวโดยอัตโนมัติ

พิสูจน์การแยก context, filesystem และ tools ของขั้นค้นเว็บ
Hosted web search ไม่ผ่าน local tool hooks; ไม่มีการอนุมัติรายคำค้นโดยตรง
หากบังคับไม่ได้ ให้ปิดฟังก์ชันนั้นและระบุว่ายังไม่ครบ release requirements
ห้ามเรียกรุ่นที่ปิด requirement นี้ว่ารุ่นสมบูรณ์

### G4 — Subscription และค่าใช้จ่าย

ไม่ใช้ API key ไม่ซื้อเครดิต ไม่เปลี่ยน auto-reload โดยเด็ดขาด
การอ่าน quota ไม่ได้จองโควตา และไม่ได้รับประกันการไม่ใช้เครดิตเพิ่มระหว่าง turn
หากบริการไม่มี hard cap ให้ระบุเป็นข้อจำกัดที่ผู้ใช้ต้องยอมรับอย่างชัดเจน
ห้ามสัญญาว่ารับประกัน no-extra-credit เพียงเพราะมี preflight check
ไม่มีเครดิตและปิด auto-reload เป็นสถานะบัญชี ณ เวลาหนึ่ง ไม่ใช่ค่าถาวร

### G5 — คุณภาพและความคุ้มค่า

ต้องมีงานจริงเทียบ manual selection ก่อนกล่าวอ้างว่าประหยัดหรือคุณภาพดีขึ้น
รุ่นทดลองที่ผ่าน mocks อย่างเดียวไม่ใช่ production-ready

ทำใบงานที่เป็น pure logic และ offline tests ต่อได้ระหว่างรอ live evidence
manual live prototype เปิด opt-in ได้ตามนโยบายที่ผู้ใช้เลือก
แต่ห้ามเผยแพร่เป็น agent สมบูรณ์ก่อนตรวจ G1/G2 และ gates ที่เกี่ยวข้อง

## 4. โครงสร้างไฟล์และข้อตกลงร่วม

โครงสร้างเป้าหมาย (ยังไม่ใช่ไฟล์ที่มีอยู่ทั้งหมด):

```text
modelmate.py                 runtime เดียว: protocol, policy, session, CLI
doctor.py                   diagnostic entry point ใช้ runtime ร่วมเมื่อย้ายแล้ว
verify.py                   opt-in synthetic live checks
tests/test_*.py             offline tests + fake server
tests/fixtures/             protocol fixtures สังเคราะห์ที่จำเป็น
docs/DESIGN.md              ข้อกำหนด
docs/MASTER_PLAN.md         แผน/สถานะใบงาน
docs/VERIFICATION.md        หลักฐานตรวจแบบไม่ระบุตัวบุคคล
docs/INSTALL.md             วิธีติดตั้ง/อัปเดต/ถอนติดตั้ง
```

P02 ย้าย shared protocol จาก doctor.py ไป modelmate.py และแก้ทุก caller/test
ไม่ copy reader เป็นสองชุด ไม่รวม diagnostic live command เข้า default chat path
ไฟล์ runtime ต้อง import ได้โดยไม่สร้าง process หรือ network request
ติดตั้งตัว runtime ไฟล์เดียวได้โดยไม่ต้องมี doctor.py หรือ verify.py
เริ่มด้วย Python standard library; ไม่เพิ่ม dependency เพื่อแต่งหน้าจอ

ขอบเขตฟังก์ชันใน runtime (ชื่อเสนอ ใช้ชื่อเดิมได้ถ้ามีหน้าที่ตรงกัน):

| ส่วน | รับเข้า → คืนออก | สิ่งที่ห้ามทำ |
| --- | --- | --- |
| Protocol reader | bytes → validated message | ไม่อนุมัติเอง ไม่ทิ้ง event ที่จำเป็น |
| Account/catalog | RPC result → validated snapshot | ไม่คัดลอก credentials |
| Quota policy | snapshot → allow/pause + reason | ไม่เรียก inference หรือเปลี่ยน billing |
| Plan validator | model JSON + catalog → validated plan | ไม่ execute คำสั่งจาก JSON |
| Routing policy | plan + mode + grant → choice/ask | ไม่เพิ่มสิทธิ์เครื่องมือ |
| Permission gate | exact action + grant → ask/allow/deny | ไม่ใช้ output ของโมเดลเป็น grant |
| Step controller | step + evidence → next state | ไม่เชื่อคำว่า tests passed จากโมเดลลอย ๆ |
| Persistence | metadata → atomic local save | ไม่เก็บ token/login secret |
| UI | input/event → display/user choice | ไม่ถือ timeout/EOF ว่ายอมรับ |

## 5. Data contracts

ใช้ plain dict + validation ตอนรับข้อมูลภายนอก ไม่สร้าง type framework
สิ่งที่โมเดลส่งมาเป็นข้อเสนอจนกว่า controller ตรวจผ่าน

### Plan proposal (schema version 1)

```json
{
  "version": 1,
  "goal": "เพิ่มการค้นหาตามชื่อสินค้า",
  "clarifications": [],
  "success_criteria": ["ค้นพบชื่อที่ตรงกัน", "ไม่พบแล้วแสดงผลว่าง"],
  "steps": [{
    "kind": "implement",
    "objective": "เพิ่มการค้นหาตามรูปแบบเดิมของโปรเจกต์",
    "role": "standard",
    "effort": "medium",
    "risk": "normal",
    "reason": "ขอบเขตจำกัดและมีการทดสอบตรวจผลได้",
    "checks": [{"kind": "test", "criterion": "กรณีพบและไม่พบผ่าน"}]
  }]
}
```

Allowed kind: plan, implement, review. Allowed role: economy, standard, strong.
Allowed risk: normal, high. Check kind: test, lint, source, rubric, manual.
Effort ต้องอยู่ในรายการที่โมเดลที่ resolve ได้รองรับ ไม่สร้างระดับใหม่เอง
ข้อความต้องไม่ว่างและมีเพดานขนาด; เริ่มที่ 64 KiB ต่อ proposal และไม่เกิน 12 steps
เพดานเหล่านี้เป็น implementation defaults ที่ทดสอบได้ ไม่ใช่ข้อจำกัดของ Codex
Reject unknown fields, malformed JSON, invalid enum, missing criterion
ห้ามมี executable permission, shell command, completion status หรือ retry count ใน proposal
checks ระบุสิ่งที่ต้องตรวจ ไม่ให้อำนาจรันคำสั่ง
Controller สร้าง task ID/step ID และ attempt counters เอง

หาก clarifications ไม่ว่าง ให้ถามก่อนเริ่มขั้นที่ขึ้นกับคำตอบ
ผลแผนผิดรูปแบบ: แสดงข้อผิดพลาด/พัก ไม่เดาเป็น SIMPLE แล้วลงมือ
ไม่เรียก decision classifier เพื่อสร้างหรืออนุมัติแผน

### Task state ที่ controller เป็นเจ้าของ

READY → CLARIFYING / AWAITING_MODEL_APPROVAL / RUNNING
RUNNING → AWAITING_TOOL_APPROVAL / CHECKING / PAUSED / FAILED
CHECKING → RUNNING (correction) / DONE / UNVERIFIED / PAUSED

PAUSED มี reason: quota_unknown, quota_exhausted, user_pause, connection_lost,
approval_needed, correction_limit, unsupported_capability
สถานะรอ approval ต้องเก็บประเภท, action digest, thread/turn/item IDs ที่เกี่ยวข้อง
ตอบ stale approval ไม่ได้; การเปลี่ยน action ทำให้ต้องขอใหม่
DONE ต้องมีผลตรวจตาม criteria; UNVERIFIED ไม่ใช่ DONE

### Evidence

เก็บ step ID, check kind, result (pass/fail/unknown), timestamp และแหล่งหลักฐาน
สำหรับ tool check เก็บ exit code/status ที่รับจากเครื่องมือจริง
สำหรับ source check เก็บ URL และ claim ที่ตรวจ ไม่ใช้การมี URL อย่างเดียวแทนความถูกต้อง
stdout/stderr ที่อาจมีข้อมูลส่วนตัวไม่เก็บใน metrics โดย default

### Grant

เก็บ scope, step ID, model/effort หรือ exact action digest, decision และเวลา
Model grant กับ tool grant คนละชนิด ไม่สามารถแทนกันได้
Approve plan ใช้ plan digest; เปลี่ยนขั้น/โมเดล/effort แล้ว invalidate grant ที่เกี่ยวข้อง
Session grant ที่ขยายสิทธิ์ต้องชัดเจนใน UI; ไม่ restore สิทธิ์ชั่วคราวข้าม process โดยเงียบ ๆ

## 6. วิธีทำงานของโมเดลตัวเล็ก

1. รับ task ID เดียว ตรวจ dependency และ git status
2. อ่านใบงานและโค้ดที่แตะ ค้นทุก caller ก่อนแก้ shared function
3. ระบุสิ่งที่จะเปลี่ยนและสิ่งที่ไม่รวม จากนั้น implement เฉพาะงานนั้น
4. เพิ่ม tests ที่พิสูจน์พฤติกรรมและ failure case ไม่ใช่แค่ assert ค่า hardcode
5. Run targeted tests; ถ้าแตะ shared behavior ให้รันทั้ง suite
6. อัปเดต evidence/status แล้วส่ง handoff แบบ section 10

หยุดเฉพาะส่วนที่ติดเมื่อ: ต้องเปลี่ยน security boundary, ต้องลด requirement,
ไม่มี supported protocol ที่ต้องใช้, tests fail หลังแก้สองแนวทางโดยไม่เข้าใจสาเหตุ,
หรือขอบเขตลามเกินใบงานอย่างมีนัยสำคัญ ส่งตัวใหญ่ตรวจพร้อมหลักฐาน
ไม่ถามผู้ใช้เรื่อง implementation จุกจิกที่แก้ได้ตามแผน
ไม่ spawn agents เพิ่มโดยไม่มีคำสั่งผู้ใช้หรือข้อกำหนดที่เกี่ยวข้อง

## 7. ลำดับและสถานะงาน

| ID | งาน | Dependencies | สถานะเริ่มต้น | Review โดยตัวใหญ่ |
| --- | --- | --- | --- | --- |
| P00 | ทำ diagnostic harness ให้เชื่อถือได้ | — | MOCK_VERIFIED | ใช่: lifecycle |
| P01 | เก็บ live compatibility evidence | P00 | IN_PROGRESS: live recall และ shell/patch denial ผ่าน; actual dispatch ยังไม่ทราบ | ใช่ |
| P02 | รวม protocol เป็น runtime ไฟล์เดียว | P00 | MOCK_VERIFIED | เฉพาะ failure/lifecycle |
| P03 | พิสูจน์ permission boundary | P01 | IN_PROGRESS: user ยอมรับ native policy; live prototype tests | จำเป็น |
| P04 | Quota policy และ pause | P02 | MOCK_VERIFIED | จำเป็น |
| P05 | Model roles และ effort policy | P02 | MOCK_VERIFIED; live mapping ยังไม่กำหนด | ตรวจตารางบทบาทครั้งแรก |
| P06 | Plan schema / policy routing | P04, P05 | MOCK_VERIFIED: explicit plan validation; decision classifier removed by user scope | จำเป็น |
| P07 | สามโหมดและ grants | P06 | MOCK_VERIFIED (offline policy) | จำเป็น |
| P08 | Terminal chat shell | P02, P07 | IN_PROGRESS: explicit-plan CLI/command-check happy path user LIVE_VERIFIED; broader routing/recovery pending | ไม่จำเป็นถ้าไม่แตะ policy |
| P09 | Tool approval UI และ enforcement | P03, P08 | IN_PROGRESS: native command/patch UI MOCK_VERIFIED | จำเป็น |
| P10 | Workflow / checks / correction limit | P07, P09 | IN_PROGRESS: explicit-plan command-check happy path user LIVE_VERIFIED; broader permission/recovery gates pending | จำเป็น |
| P11 | Local session persistence | P02 | MOCK_VERIFIED: storage API และ manual live checkpoints | ตรวจ data loss/privacy |
| P12 | Resume / cancel / delete | P10, P11 | IN_PROGRESS: manual resume and synthetic tool recheck happy paths scoped LIVE_VERIFIED; native workflow cancellation scoped LIVE_VERIFIED; synthetic two-root scoped cleanup LIVE_VERIFIED | จำเป็น |
| P13 | Web privacy boundary | P03, P09 | IN_PROGRESS: Thai Wikipedia lookup scoped LIVE_VERIFIED; SearXNG general search MOCK_VERIFIED; hosted search remains disabled | จำเป็น |
| P14 | Metrics และรายงาน | P10, P11 | IN_PROGRESS: local session elapsed/attempts/requested selections MOCK_VERIFIED; usage/backend telemetry unknown | ไม่จำเป็นถ้าไม่แตะ policy |
| P15 | ติดตั้งและเอกสารผู้ใช้ | P08, P12, P14 | IN_PROGRESS: standalone install/help/preview/alias MOCK_VERIFIED; full release guide follows remaining gates | ตรวจคำกล่าวอ้าง |
| P16 | End-to-end / evaluation / release | P01–P15 | IN_PROGRESS: scoped evaluation pilots and requirement coverage audit; release dependencies/gates remain open | จำเป็น |

Dependency ไม่ได้อนุญาตทำงานขนานโดยอัตโนมัติ
ลำดับแนะนำระหว่างรอ P01: P00 → P02 → P04 → P05 → P06 → P07 → P08 → P11
P08 มี opt-in manual live prototype ตาม native policy ที่ผู้ใช้เลือก
ต้องแยกผล fake/live และยังไม่เปิด auto workflow จน dependencies ผ่าน

## 8. ใบงาน

### P00 — ตรวจและแก้ diagnostic harness ก่อนเชื่อผล

ไฟล์: doctor.py, verify.py, tests/test_doctor.py, tests/test_verify.py
อ่าน: Connection.receive/request, inspect, ensure_quota, run_turn, interrupt และ main

- ตรวจลำดับ notifications ก่อน/หลัง RPC response และ response ที่ส่งติดกัน
- ตรวจ stdout มีข้อมูลสุดท้ายพร้อม EOF ต้องไม่ทิ้ง message ที่อ่านไว้แล้ว
- ตรวจ approval ที่ไม่ตรง thread/turn, unknown server request, malformed payload
- ตรวจ deadline เป็นของ turn ทั้งรอบ ไม่รีเซ็ตทุก notification
- ตรวจ cleanup: ขอ interrupt ก่อนลบ scratch; interrupt ล้มเหลวไม่กลบ error ต้นเหตุ
- ตรวจระหว่างรอ turn/start หาก server เริ่มแล้วแต่ client ยังไม่มี turn ID
  ต้องรายงาน outcome unknown และไม่ retry inference อัตโนมัติ
- ห้าม mark model switch ผ่านจากการส่งชื่อ model อย่างเดียว
  แยก requested model กับ reported model หาก API ไม่คืน actual model ให้ระบุ unknown
- ตรวจ quota malformed/empty/multiple buckets และ account identity

ผ่านเมื่อ: offline regressions ครอบคลุมทุกข้อ; doctor ไม่มี code path เริ่ม inference;
verify ไม่ถือ no approval event เป็นผ่าน; จำนวน tests เพิ่มตาม bug ที่พบจริง
ไม่รวม: full CLI หรือ live test ที่อ้างว่าประหยัด quota

### P01 — Live compatibility report

ไฟล์: docs/VERIFICATION.md; แก้ harness ได้เฉพาะ bug ที่พบและต้องเพิ่ม regression
รัน doctor ก่อน verify จาก Terminal ปกติ ด้วยข้อมูลสังเคราะห์เท่านั้น
บันทึกเวอร์ชัน, OS, methods ที่ตรวจ, model IDs/effort ที่ใช้, pass/fail/inconclusive,
คำสั่งและผลสรุปที่ไม่มี account identifiers ห้าม commit raw report

ผ่านเมื่อ: อ่านสถานะจริงได้, context recall ตรวจได้, denial ของ shell/patch ตรวจได้
ต้องไม่สรุปจากสอง denial ว่า G2 ครบ ให้แยก matrix ของ paths ที่ยังไม่ได้ตรวจ
หาก quota unknown ให้ BLOCKED ไม่เพิ่ม bypass flag เพื่อผ่าน gate

### P02 — Protocol runtime เดียว

ไฟล์: modelmate.py (ใหม่), doctor.py, verify.py, tests ที่ import protocol
ย้ายโค้ด shared โดยรักษา validation/error handling และ diagnostic read-only allowlist
แบ่ง notification dispatch กับ RPC response correlation; จำกัดขนาด buffer/event queue
unknown server request ต้องหยุด/ปฏิเสธอย่างชัดเจน ไม่มี implicit accept
stderr ไม่เผย raw secrets; shutdown ไม่ทิ้ง child process

ผ่านเมื่อ: diagnostics ยังผ่าน tests เดิม, imports ไม่มี side effects,
fake stream ทดสอบ fragmentation/interleaving/EOF/invalid ID/timeout ได้
ไม่รวม: reconnect แล้ว replay งาน, generic RPC framework, dependency ใหม่

### P03 — Permission capability spike และการตัดสินใจสถาปัตยกรรม

ไฟล์: docs/VERIFICATION.md, tests/fixtures และ test เฉพาะเมื่อจำเป็น
จัด matrix: action path, enforcement mechanism, approval timing, deny behavior,
possible bypass, live evidence และสถานะ supported/disabled/unproven
ตรวจขอบเขต filesystem รวม symlink และ paths นอกโปรเจกต์
ตรวจโปรเจกต์ที่มี AGENTS/hooks/plugins ไม่ให้ขยายสิทธิ์เอง

พิจารณาใช้ capability ที่ Codex รองรับก่อน; ถ้าใช้ client-owned tools
ต้องพิสูจน์ว่าปิด native paths ที่ข้าม gate ได้จริง ไม่เลือกเองจากการคาดเดา
ตัวใหญ่ต้องตรวจข้อสรุปก่อน P09 ไม่มีอำนาจเปลี่ยน requirement แทนผู้ใช้
ผ่านเมื่อ: มีแนวทางที่พิสูจน์ G2 ได้ หรือรายงาน BLOCKED ที่เจาะจงและ review แล้ว
ไม่รวม: ปิด sandbox ทั้งหมดเพื่อให้ tests ผ่าน

### P04 — Quota gate

ไฟล์: modelmate.py, tests/test_quota.py; migrate ensure_quota callers ถ้าใช้ร่วม
ผลลัพธ์ allow/pause พร้อม reason, checked_at และบัญชีที่ใช้สำหรับตรวจในหน่วยความจำ
account mismatch, null, error, exhausted window, stale snapshot ต้องไม่เริ่ม turn ใหม่
เริ่มต้น refresh ก่อนทุก controller-started turn; ไม่ใช้ snapshot ของ doctor เก่าตลอด session
ตรวจทุก applicable bucket ตามข้อมูล backend ไม่เดาว่าโมเดลอื่นไม่มี limit
บันทึกข้อจำกัดของการเลือก bucket หาก mapping ไม่พอ และ pause เมื่อไม่แน่ใจ

ผ่านเมื่อ: fake server ยืนยัน turn/start ไม่ถูกส่งเมื่อ gate ไม่ผ่าน;
ครบ quota unknown/exhausted/refreshed/account changed/network error
ไม่รวม: hard cap ที่บริการไม่รองรับ, ซื้อ reset/credit, timer เริ่มงานเองโดยไม่ refresh

### P05 — Model roles และ effort

ไฟล์: modelmate.py, tests/test_models.py
Catalog เป็นแหล่ง model IDs/efforts ที่รองรับ แต่ไม่ใช่คะแนนคุณภาพหรือราคา
เก็บ policy mapping รุ่นแรกเป็นข้อมูลชัดเจนสำหรับโมเดลที่ทดสอบแล้ว
ตัวใหญ่ review mapping; ชื่อไม่รู้จักต้องให้ผู้ใช้เลือกหรือพัก ไม่จัดอันดับจากชื่อ
ไม่เพิ่ม API decision classifier; ใช้ explicit bindings ตาม scope ปัจจุบัน
role economy/standard/strong เป็น policy ไม่ใช่ข้อเท็จจริงถาวรของ vendor

ผ่านเมื่อ: unsupported model/effort ถูกปฏิเสธ, catalog pagination,
missing role, hidden model, catalog เปลี่ยนตอน resume และ manual selection
การเปลี่ยน model/effort ที่ยังไม่มี comparative policy ให้ถือว่าอาจยกระดับและถาม
ไม่รวม: auto benchmarking ทุก startup หรือ scraping ราคา

### P06 — Plan และ routing

ไฟล์: modelmate.py, tests/test_routing.py, synthetic plan fixtures
อัปเดตตามผู้ใช้ 2026-11-18: ไม่ทำ decision model/classifier แยก
ใช้ validator ตาม section 5 กับ explicit plan/role bindings และ controller policy
ไม่เพิ่ม inference หรือบริการภายนอกเพื่อเลือกโมเดลเริ่มต้น
แสดง goal, criteria, steps และเหตุผลสั้น ๆ; ห้ามแสดง private reasoning

ผ่านเมื่อ: งานง่ายไม่ถูกบังคับ plan+strong review, งานเสี่ยงมี check,
clarification หยุด dependent work, invalid proposal ไม่เริ่ม tools,
prompt injection ขอเปลี่ยน policy ไม่เปลี่ยนสิทธิ์
ไม่รวม: แค่ keyword COMPLEX/SIMPLE แล้วเชื่อโดยไม่ตรวจ output

### P07 — Routing modes และ grants

ไฟล์: modelmate.py, tests/test_modes.py
Auto แจ้งการเลือก; Ask to escalate ถามก่อนเพิ่ม model/effort รวมตัวเลือกเริ่มต้น strong;
Approve plan รอ plan grant และ invalidate เมื่อแผนเปลี่ยน
การปฏิเสธให้เลือกลด scope/model หรือพัก ไม่ยกระดับเงียบ ๆ
ระบุ baseline ต่อ task เพื่อไม่ให้ task ก่อนที่ใช้ strong กลายเป็นสิทธิ์ถาวร
Manual model selection เป็นการอนุมัติเฉพาะขอบเขตที่แสดง ไม่ขยาย tool permission

ผ่านเมื่อ: matrix ทั้ง 3 modes × initial selection/escalation/downgrade/plan change;
ไม่มีการถามซ้ำเมื่อ grant เดิมยังตรง และ stale grant ใช้ไม่ได้
ไม่รวม: predictive quota percentages หรือ auto permission approval

### P08 — Terminal chat

ไฟล์: modelmate.py, tests/test_cli.py
รองรับ sr, sr "prompt", --help, blank input, EOF, Unicode ไทย และคำสั่งตาม DESIGN
เริ่มจาก line-oriented UI; แสดง streaming text ที่ปลอดภัยและ progress
UI ต้องรับ approval/cancel ขณะมี events โดยไม่ทำ deadlock
ห้ามให้ escape sequences จาก model/tool ควบคุม Terminal โดยไม่กรอง
ถ้าใช้ thread อ่าน input ต้องกำหนด owner ของ state และ shutdown ชัดเจน

ผ่านเมื่อ: fake conversation หลาย turn, input ระหว่าง streaming,
Ctrl+C/EOF ระหว่างรอ approval, invalid slash command ไม่ส่งเป็นงานโดยไม่ตั้งใจ
ไม่รวม: full-screen TUI, syntax highlighter หรือ UI framework

Workflow UI milestone: ChatShell/run_chat รับ controller และ trusted workflow_action callback
แสดงแผน/status/check results และรับ /next, model approval, pause/continue/revise ตาม exact token
ไม่เชื่อ event ที่อ้าง state/DONE จากภายนอก; workflow_changed เป็นสัญญาณให้ UI อ่าน controller เอง
ยังไม่มี native workflow CLI entry point; ห้ามผูก workflow กับ manual send/backend โดยข้าม integration gates
WorkflowHost รับ executor_stream ผ่าน selector แยกจาก model text/UI events; /check ประเมินเฉพาะหลักฐาน host-bound

### P09 — Tool approvals

Controller foundation: workflow checkpoint v3 records the latest bound tool
request and decision status without a confirmation token or raw action. The
AWAITING_TOOL_APPROVAL transition, exact one-use decisions, expiry on action
change/pause/completion/restore and persistence-failure freeze are offline-tested.
Only trusted host/UI calls can reach these APIs. The native workflow adapter is
not connected to them yet and still declines requests; no live gate is passed.
Host/UI wiring now supports explicitly supplied trusted preview/response adapters.
It binds the printable preview digest to the current turn, displays it before
offering a tool token, and persists a decision before the callback. Cancel, EOF,
pause, timeout and disconnect decline and interrupt; unknown sends never replay.
No CLI flag or native acceptance path has been enabled by this offline increment.

Manual patch approval hardening: each token retains its thread/turn/item and
displayed diff. A changed, invalid, completed or type-reused item immediately
declines the pending request and expires the token, even if the old diff returns.
Each displayed change must contain a nonempty path and diff. Offline evidence is
in VERIFICATION.md; workflow approval acceptance and the full live G2 matrix are
still gated.
Duplicate pending request IDs also decline once and expire the original token;
they cannot later receive an accept through the stale confirmation.
Codex 0.171.0 generated-schema review identified `item/fileChange/patchUpdated`;
it now shares the validated preview cache/invalidation path. Unsupported callback,
stdin, managed-human, environment, network and session-root scopes are declined
without showing an accept token. This is offline/schema evidence, not live G2 proof.

ไฟล์: modelmate.py, tests/test_permissions.py และ integration fixtures
Implement กลไกที่ P03 พิสูจน์แล้วเท่านั้น
แสดง exact command/cwd หรือ patch ก่อนถาม accept-once/decline
ตัวเลือก scope กว้างแสดงผลให้เห็น; model grant ไม่อนุมัติเครื่องมือ
ตอบ approval ตรง request/thread/turn/item เท่านั้น
การ reconnect ต้องไม่อนุมัติ action ที่เปลี่ยนหรือหมดอายุ

ผ่านเมื่อ: approval matrix G2, deny/timeout/EOF/disconnect ไม่มี side effect,
unknown tool และ malformed approval หยุด, stronger managed policy ยังคงบังคับ
ไม่รวม: acceptForSession โดย default หรือใช้ shellCommand ที่ข้าม sandbox แทน executor

### P10 — Workflow และ correction budget

Source-check CLI increment: explicit `/verify-source` records a human-checked
URL, claim finding and verdict only after confirmed turn completion. Restored
source evidence requires `/revalidate-source` against the saved URL and verdict.
This adds no search/model call or tool grant; offline verification is recorded
in VERIFICATION.md. Broader live workflow/recovery gates remain open.
Durable source-check integration is also offline verified across two synthetic
backend processes; local source URLs/findings are absent from later turn inputs.

ไฟล์: modelmate.py, tests/test_workflow.py
มี WorkflowController แบบ offline แล้ว: ไม่มี network/process/tool execution
เชื่อม ModelApprovals และ quota_decision; dispatch descriptor ยังไม่ถูกส่งไป backend
เก็บ controller IDs, attempts/cycles/evidence และ user-choice ledger
ใช้ SessionStore.workflow เพื่อ autosave ทุก transition ภายใต้ writer lock และ restore จาก session schema v3
restore ไม่คืน approval/token/grant; active turn ที่ยังไม่ทราบผลต้อง reconcile ก่อน ไม่ replay
controller methods รับเฉพาะ trusted host/UI events ไม่ใช่ API ที่เปิดให้โมเดลเรียกโดยตรง
Controller ถือ state/step IDs/counters; explicit plan ไม่ให้อำนาจขยายสิทธิ์
initial attempt + correction 1 + correction 2 จากนั้นหยุดถาม
user เลือกทำต่อแล้วเริ่ม budget ใหม่ได้เฉพาะ explicit choice พร้อมเก็บรอบเก่า
แก้ permission/model ต้องผ่าน gates ทุกครั้ง
checks ใช้ผลเครื่องมือจริง; model review เป็นหลักฐานประเภท review เท่านั้น
ขั้น risky work ต้องมี strong review ตามหลัง ไม่ใช่แค่มี review อยู่ก่อนหน้า
จบทุกขั้นแล้วยังต้องมี trusted checker จับคู่เกณฑ์สำเร็จกับ accepted evidence IDs จึงเป็น DONE
การ revise ขั้นเดิมจำกัด objective/role/effort/reason และไม่ล้าง ID/budget/criteria
WorkflowHost ผูก attempt กับ thread/turn/item และ approved command/cwd; ไม่ใช้ exit code จากคำสั่งอื่นแทน test
preflight/dispatch/interrupt ยังเป็น trusted callbacks ไม่มี native transport/command runner ในตัว
request approval ของ workflow ยังไม่รองรับ: ขอหยุดและไม่ตอบ accept; ultra delegation ยังถูกปิด

ผ่านเมื่อ: simple code, plan-heavy code, document task เดินครบ;
fail 3 attempts แล้วหยุด, model เปลี่ยนชื่อ step ไม่ reset,
quota หมดกลางงานพัก, tests unavailable → UNVERIFIED, interrupted ≠ DONE
ไม่รวม: agent spawn, infinite reflection loop หรือให้โมเดลรับรองผลเอง

### P11 — Local metadata

ไฟล์: modelmate.py, tests/test_sessions.py
เก็บใต้ XDG_STATE_HOME/modelmate หรือ ~/.local/state/modelmate
project key ใช้ normalized real path + hash; filename ไม่ใช้ชื่อจากโมเดลโดยตรง
metadata schema version 1, local permissions restrictive, atomic replace
โปรเจกต์หนึ่งเปิดหลาย session ได้ แต่ห้ามสอง process เขียน session เดียวพร้อมกัน
ใช้ file lock ของ Linux; ไม่มี database หรือ cloud sync
ไม่เก็บ credentials; transcript ยังเป็นของ Codex ไม่ทำสำเนาโดยปริยาย

ผ่านเมื่อ: path มีช่องว่าง/ภาษาไทย, symlink identity, interrupted write,
corrupt JSON ไม่ถูกทับ, unsupported future version ไม่แก้, concurrent writer ถูกปฏิเสธ
ไม่รวม: migration framework; เพิ่ม migration เมื่อมี version ถัดไปจริง

### P12 — Resume / cancel / delete

Latest offline increment: recovery-observer connection loss and a terminated owned
fake server preserve the attached unknown recheck checkpoint and stale evidence.
Reopening the controller retains the same binding without replay or automatic
interrupt. `test_native_recheck.py`: 42 tests passed outside the socket-restricted
sandbox. This is MOCK_VERIFIED only; live workflow/server-loss recovery remains open.
Abrupt workflow-owner exit is also covered offline: 14 ledger tests passed;
reopening releases the writer lock but retains the unresolved turn binding and
blocks new work/rechecks until reconciliation. No live process-loss gate is claimed.
Active WebSocket disconnect is covered before and after a successful command
result but before turn completion: 14 transport tests passed with sockets enabled.
Both paths retain unknown outcomes and stale evidence without replay on restore.
The opt-in verifier now has `--terminate-recheck-server` for this live gate,
with offline coverage for active-owner checks, shutdown, durable unknown state,
and blocking work/recheck replay. Live execution remains user-run and unverified.
Owned-server cleanup now terminates its process group even if the leader exited
first; a regression reproduces and fixes a surviving SIGTERM-resistant descendant.
Experimental shared-recheck CLI now has offline pseudoterminal coverage from
main/START through disconnect, recovery, cancelled/stale STOP tokens and exit.
The test uses synthetic stdio substitutes for shared transports; live interactive
and server-loss gates remain unverified.

ไฟล์: modelmate.py, tests/test_lifecycle.py
ขอบเขตที่เริ่มได้โดยไม่ใช้ P10: manual live chat checkpoints, resume และ deletion
เพิ่ม schema v2 ผูก account fingerprint/turn/deletion receipt; v1 ไม่เดาบัญชีเพื่อ resume
เพิ่ม schema v3 เฉพาะเมื่อผูก workflow: checkpoint schema v1 พร้อม validated ledger/counters/evidence
v1/v2 ไม่ถูกอัปเกรดจากการอ่าน; manual chat ปฏิเสธการ resume workflow เพื่อไม่ทิ้ง controller state
หลักฐาน offline อยู่ใน VERIFICATION.md; ยังไม่อ้าง workflow lifecycle หรือ live gate ผ่าน
มี `verify.py --run-live --probe-sessions MODEL` สำหรับเก็บหลักฐานสอง turn ข้าม reconnect
พร้อมตรวจ deletion เฉพาะ scratch thread; ผู้ใช้รันสดผ่านบน 5647656 และ hashes ตรงกัน
ผลสดเฉพาะ happy path ไม่แทน live crash recovery, tool paths หรือ workflow integration
Resume ตรวจบัญชี/โปรเจกต์/catalog/quota ใหม่ก่อน turn
RUNNING ที่หลงเหลือหลัง crash → outcome unknown จน reconcile กับ Codex
ห้าม replay side effects; ถ้าไม่ทราบให้ผู้ใช้ตัดสินหลังแสดงหลักฐาน
Ctrl+C ส่ง interrupt และรอ confirmation มี deadline; ไม่ยืนยันว่า stopped ถ้าไม่ทราบ
/exit ไม่ทิ้งกำลังทำงานโดยเงียบ ๆ
/delete แสดง session/descendants ที่เกี่ยวข้องและขออนุมัติ ไม่ลบไฟล์งาน
หาก remote deletion ไม่สำเร็จ ให้เก็บ metadata เพื่อ retry ไม่อ้างว่าลบครบ

ผ่านเมื่อ: crash ก่อน/หลัง tool result, disconnect ก่อน response,
resume missing thread/account mismatch, duplicate delete, partial delete failure
ไม่รวม: rollback ไฟล์งาน หรือการรับรองว่าลบข้อมูลฝั่งบริการทั้งหมด

### P13 — Private-context web search

ไฟล์: modelmate.py, tests/test_web_policy.py, docs/VERIFICATION.md
ใช้การออกแบบที่ผ่าน G3: execution context ปิด hosted search,
search context ได้เฉพาะ approved/public query และไม่มี access ไปข้อมูลส่วนตัว
query ที่ provenance เป็นไฟล์/บทสนทนาส่วนตัวหรือไม่ทราบต้องถาม
ไม่อ้างว่าตรวจ privacy ได้จาก keyword/regex อย่างสมบูรณ์
ผลเว็บเป็น untrusted data; อ้างอิง claim ที่รองรับ ไม่เชื่อคำสั่งในหน้าเว็บ

ผ่านเมื่อ: synthetic secret ใน file/history ไม่เข้า search context,
ไม่สามารถอ่านไฟล์คืนผ่าน tools, user ปฏิเสธแล้วไม่ค้น,
public query เดินได้และแสดงแหล่งอ้างอิง, prompt injection ไม่เพิ่มสิทธิ์
ไม่มี supported isolation → BLOCKED และปิด feature; ไม่แทนด้วย prompt-only guard

### P14 — Metrics

ไฟล์: modelmate.py, tests/test_metrics.py
แสดง elapsed monotonic time, requested model, reported model ถ้ามี,
phase, attempts, outcome และ usage ที่ server รายงาน
แยก user wall time รวมรออนุมัติกับ model/tool elapsed ที่วัดได้
แยก reasoning/cached tokens เมื่อมี ไม่บวกซ้ำยอด output/total
quota delta เป็น observed change ไม่ระบุว่าเกิดจากงานเดียวหากมี concurrent use
JSONL logging เลือกเปิดได้; ไม่เก็บ prompt/output/secrets โดย default

ผ่านเมื่อ: failed/partial/cancelled turns, missing usage → unknown,
no duplicate completed-event counts, log write failure ไม่ทำงานหาย,
reporting ไม่สร้าง extra inference เพื่อสรุปสถิติ
ไม่รวม: ประเมินราคา API สำหรับ subscription หรือ token-to-quota สูตรที่ไม่ยืนยัน

### P15 — Installation และ user guide

ไฟล์: README.md, docs/INSTALL.md, modelmate.py CLI help
ระบุ Python/Codex versions ที่ทดสอบจริง, chmod, alias sr ที่ใช้ path ถูกต้อง,
วิธี login ด้วย ChatGPT, diagnostics, อัปเดต, ถอนติดตั้ง และข้อมูลที่เหลือหลังถอน
รองรับ path มีช่องว่าง; ไม่แก้ .bashrc ของผู้ใช้โดยไม่จำเป็น แสดงคำสั่งให้เลือกใช้
ใช้ stdlib ไม่ต้อง pip install openai สำหรับ architecture นี้

ผ่านเมื่อ: runtime ไฟล์เดียวทำงานจาก scratch folder บน Linux/WSL2,
--help ไม่ต้อง auth/network, missing codex แสดงวิธีแก้,
ตัวอย่างไม่เปิด live test โดยไม่บอกว่าใช้ quota
ไม่รวม: package registry publish, auto updater หรือติดตั้ง dependencies เงียบ ๆ

### P16 — Release candidate และ evaluation

ไฟล์: tests/, docs/VERIFICATION.md, docs/EVALUATION.md, README.md
ใช้ชุดงานเริ่มต้น 12 งานสังเคราะห์/ได้รับอนุญาต: code 8, analysis/document 4
รวมงานง่าย, หลายไฟล์, ความเสี่ยงสูง, ambiguity, review, source-backed writing
กำหนดเกณฑ์ก่อนรัน; ใช้ inputs/version/checks เดียวกันกับ baseline ที่เลือกโมเดลเอง
บันทึก model mix, pass rate, corrections, wall time, tokens และ quota observations
ไม่ให้โมเดลผู้เขียนเป็นผู้ตัดสินคุณภาพเพียงผู้เดียว

**งานถัดไปใน P16 (แผน 2026-11-20)** เลือกขั้นงานจริงที่ทำซ้ำได้หนึ่งชนิด
และเขียนเกณฑ์ผ่านก่อนออกแบบกฎเลือกโมเดล ชุด pilot 12 งานข้างต้นยังใช้เทียบผลเดิมได้
การทดลองนี้เลือกจากข้อมูลจริงที่มีสิทธิ์ใช้ โดยพิจารณาคุณภาพของหลักฐานก่อนชนิดของไฟล์

1. ถ้ามี ticket ที่ใช้ประเมินได้ ให้เริ่มจากการเลือกทีมรับเรื่อง ใช้เฉพาะข้อความที่รู้ตอนรับเรื่อง
   ซ่อนผลภายหลังไว้ให้ผู้ตรวจ ระบุทีมแรกที่เหมาะสมหรือข้อมูลที่ต้องถามเพิ่ม เคสที่ตัดสินไม่ได้ให้บันทึก unknown
   หากไม่มีข้อมูลดังกล่าว ให้ใช้ขั้นงานที่มีเฉลยตรวจได้ เช่น คัดรายการผิดปกติใน CSV หรือบั๊กจริงพร้อม regression test
2. แยกตัวอย่างสำหรับตั้งกฎออกจากงานชุดใหม่สำหรับวัดผล ใช้ทั้งเคสที่ผ่านและเคสที่พลาด
   ร่างข้อเสนอที่บอกขอบเขตงาน เกณฑ์ผ่าน เงื่อนไขถามเพิ่มหรือยกระดับ และตัวอย่างที่รองรับ
   ให้ผู้ใช้พิจารณาก่อนนำกฎไปใช้ตามโหมดที่เลือก
3. บนชุดวัดผล เปรียบเทียบกฎกับการใช้รุ่นใหญ่ตลอด ด้วยข้อมูลตั้งต้นและเกณฑ์เดียวกัน
   รายงานจำนวนผ่านครั้งแรก ผ่านสุดท้าย และ unknown จำนวนครั้งที่ขอรุ่นใหญ่ รอบแก้
   และเวลาจนรับงาน รวมต้นทุนการแก้ผิดทางที่สังเกตได้ เช่น จำนวน ticket ที่ต้องส่งต่อใหม่
   รายงานโควตาเฉพาะที่วัดได้ การทดลองแบบจับคู่ทำเฉพาะตอนประเมินกฎ

ผลส่งมอบแรกคือชุดตัวอย่างที่ได้รับอนุญาตพร้อมเกณฑ์ตัดสินและการแบ่งชุดตั้งกฎ/วัดผล
ส่วนการสร้าง benchmark จากประวัติ PR อัตโนมัติอยู่นอกขอบเขตใบงานนี้

เงื่อนไข release: ทุก R มี implementation + tests + evidence ที่จำเป็น,
ไม่มี known permission bypass/data loss/unauthorized inference,
งานค้างแสดงตามจริง และ failure cases สำคัญผ่าน
เกณฑ์คุณภาพเบื้องต้น: ทุก critical check ผ่านและคุณภาพไม่ด้อย baseline
เกณฑ์นี้เป็นแผนประเมิน ไม่ใช่ผล benchmark; หากไม่ประหยัดให้รายงานตามจริง
G1–G4 ที่ยังติดต้องแก้หรือให้ผู้ใช้ตัดสิน requirement ก่อนเรียกว่า complete
ไม่ publish release หรือเปลี่ยน visibility repo โดยถือว่าอนุญาตจากการเขียนแผน

## 9. Test strategy และคำสั่งมาตรฐาน

- Unit: pure policy/state/validation ไม่เรียก network
- Protocol integration: subprocess fake server ส่ง JSONL จริง แบ่ง bytes และสลับ events
- Filesystem: TemporaryDirectory ตรวจ no-side-effect/atomicity/locks
- CLI: subprocess stdin/stdout/exit code/cancel ไม่เช็คแค่ข้อความ mock
- Live: opt-in เท่านั้น ไม่อยู่ใน default CI และไม่ใช้ account credentials ใน fixtures

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile doctor.py verify.py
# เพิ่ม modelmate.py ใน compile checks หลัง P02 สร้างไฟล์แล้ว
git diff --check
```

CI (ถ้าเพิ่ม) รันเฉพาะ offline checks ไม่มี secrets หรือ inference
ห้ามลบ test เพราะเครื่องมือติด sandbox; แยก skipped/inconclusive/blocked จาก passed

## 10. Prompt และ handoff สำหรับมอบหมายงาน

ใช้ template นี้กับโมเดลตัวเล็ก โดยแทน TASK_ID เท่านั้น:

```text
ทำใบงาน TASK_ID ใน docs/MASTER_PLAN.md เท่านั้น
อ่าน AGENTS.md, MASTER_PLAN sections 1–6 และใบงาน TASK_ID
ตรวจ dependency/status และอ่านโค้ด/callers ที่แตะก่อนแก้
รักษาข้อกำหนดใน docs/DESIGN.md และอย่าลด validation/permissions
ใช้ smallest complete change; ไม่เพิ่ม dependency หรือ abstraction เผื่ออนาคต
เพิ่มและรัน tests ตามเกณฑ์ผ่านของใบงาน ห้ามเรียก inference โดยปริยาย
หากติด capability/security decision ให้รายงานหลักฐานและทำส่วนอิสระต่อ
ส่งมอบ: สิ่งที่เปลี่ยน, ไฟล์, tests/ผลจริง, ข้อจำกัด, สถานะงาน และงานถัดไป
ไม่อ้างว่า live verified หากมีเพียง mocked tests
```

รูปแบบ handoff:

```text
Task: Pxx
Status: MOCK_VERIFIED / LIVE_VERIFIED / BLOCKED / DONE
Requirement IDs:
Changed files:
Behavior before → after:
Checks run and actual results:
Live evidence (or NOT RUN):
Known limits / remaining gates:
Next eligible task:
Commit:
```

ตัวใหญ่ตรวจเฉพาะ policy/security/architecture และจุดที่ระบุในตาราง
ไม่ต้องให้ตัวใหญ่เขียนทุกบรรทัดหรือ review เอกสารเล็กทุกครั้ง
การใช้โมเดลตัวเล็กทำตามแผนนี้ไม่ได้อนุญาตให้ทำงานขนานโดยปริยาย

## 11. Definition of done ของทั้งโครงการ

- ผู้ใช้เริ่มแชต sr และทำงาน code/document จริงจนถึงผลตรวจได้
- ระบบเลือก model/effort/workflow พร้อมเหตุผล และสามโหมดทำงานตรงข้อกำหนด
- ไม่มีสิทธิ์เพิ่มโดยโมเดล ไม่มีคำสั่งก่อน approval ที่จำเป็น ไม่มี retry ไม่จำกัด
- session/resume/delete และ crash recovery ไม่ทำข้อมูลหายหรือรันซ้ำเงียบ ๆ
- quota unknown/exhausted ทำให้พัก และไม่ fallback ไป paid API
- web privacy boundary มีหลักฐานรองรับ ไม่ใช่เพียงคำสั่งใน prompt
- ติดตั้งไฟล์ runtime เดียวบน Linux/WSL2 ได้พร้อมคู่มือ
- มีผล evaluation และระบุข้อจำกัดที่ยังมีอย่างตรงไปตรงมา
- สถานะ release แยกจาก development checklist และผู้ใช้รับรู้ข้อจำกัดบริการ

### Local inspection increment — P08/P12/P15 (2026-11-17)

MOCK_VERIFIED: CLI `--sessions` และ `--show-workflow SESSION_ID` อ่าน metadata
ของโปรเจกต์ปัจจุบันแบบ read-only โดยไม่เปิด backend ไม่สร้าง directory/lock
ไม่คืน approval หรือ resume controller แสดงผลตรวจและสถานะเป็น historical data
เท่านั้น Native workflow entry point และ auto routing ยังไม่เปิด; P03/P09 gates
ยังต้องมีหลักฐานเพิ่ม ไม่มีการเปลี่ยนสถานะ live gate จากงานนี้
ตรวจด้วย `tests/test_local_inspection.py` (7 offline tests) และ full offline suite

P10/P12 recovery fix (2026-11-18): restored checks are stale until explicit trusted
host revalidation. Attempt evaluation and task completion enforce this in the
shared controller, including restored DONE and partially checked attempts.
No native transport or live gate is enabled by this change.

### P10 native transport increment (2026-11-18)

MOCK_VERIFIED: NativeWorkflowConnection เชื่อม explicit plan/controller กับ native
protocol และ Terminal selector; queue events ระหว่าง synchronous turn/start จนผูก
thread/turn ได้ ตรวจ subscription/catalog/quota และ effective thread permissions
reuse thread ใน correction; decline tool approvals แล้วพัก; ไม่ replay unknown start
เฉพาะ new READY workflow และ ephemeral thread; native resume/classifier/auto routing
และ public CLI entry point ยังไม่เปิด ไม่มี live gate ผ่านจากข้อมูลจำลอง
Next: opt-in synthetic live verifier สำหรับ transport/deny/interrupt/context recall
ก่อนพิจารณาเปิด CLI โดยต้องตรวจ stronger managed policy และ private-web gates แยก

PR #6 display fix (2026-11-18): native transport forwards completed assistant
messages to UI as text only, scoped to current binding and deduplicated per turn.
Foreign/late messages and text claims cannot advance workflow or supply evidence.
No native permission or live gate status changes.

### P10 native workflow verification harness (2026-11-18)

MOCK_VERIFIED: `verify.py --run-live --probe-workflow MODEL` ใช้ native transport
จริงในเส้นทาง opt-in; offline tests ใช้ fake App Server เท่านั้น สูงสุด 4 turns
ใน ephemeral threads: exact displayed ACK/recall, approval denial + sentinel,
confirmed interruption และ local disconnect/no-new-dispatch guard ไม่มี retry
ไม่เกิด approval/cancel race เป็น UNVERIFIED; unknown outcome เก็บ scratch
No live gate passed: ผู้ใช้ต้องรันคำสั่ง live และตรวจหลักฐาน version/hash ก่อน
เปิด native workflow CLI; network-drop recovery และ tool paths อื่นยังไม่พิสูจน์

P10 scoped LIVE_VERIFIED update (2026-11-18): user-supplied workflow probe reports
all six checks passed at commit 326a819; runtime/verifier hashes match local files.
See VERIFICATION.md for hashes, provenance and scope. This verifies the synthetic
happy path and local disconnect guard only; full G2/G3, network recovery, native
workflow resume, classifier and public CLI remain gated. Next eligible work is a
review of the verifier/evidence and an explicit-plan CLI design constrained to
verified capabilities, without claiming full auto routing readiness.

PR #7 review correction (2026-11-18): answerDisplay/disconnectGuard in the original
live report could be false positives. Those two live claims are UNVERIFIED pending
a run with the fixed verifier. Offline regression tests now reject missing UI output
and a no-op disconnect; the latter uses READY state and preflight/dispatch tripwires
without additional inference. This supersedes the earlier blanket six-check claim.


P10 fixed-probe evidence update (2026-11-18): user-supplied rerun at commit 2679ca7
reports all six checks passed, including actual rendered answers and the corrected
READY-state local disconnect probe. Runtime/verifier hashes match local files;
see VERIFICATION.md. Scoped LIVE_VERIFIED for this probe only. Full permission/web
and native recovery gates remain open; this does not enable auto routing or CLI.

### P08/P10/P12 explicit-plan CLI increment (2026-11-18)

MOCK_VERIFIED: --workflow previews bounded validated JSON offline with explicit
role bindings, requested efforts, risk, reason and criteria. --execute-workflow
requires START before opening Codex, then manual /next dispatch under model gates.
Only no-clarification/manual-rubric plans execute. /verify records explicit user
observations; /check evaluates; /finish maps each criterion to accepted evidence.
SessionStore.workflow checkpoints precede dispatch; native sessions remain
inspection-only/ephemeral with no resume support. No automatic classifier or tool
approval acceptance was added. The new CLI needs user-run live verification before
claiming its happy path is live-verified. Commit milestones now follow the user's
latest autonomous-work instructions; no per-increment PR or merge is required.


P14 local metrics increment (2026-11-18): explicit workflow CLI prints a final
structured summary with local session duration including user wait, consumed
attempt count, distinct requested selections and workflow state. reportedModels
and tokenUsage stay null; no pricing, savings or actual-dispatch inference.
No persistent metrics file/schema change yet. Offline-tested; new CLI live test pending.


Explicit-plan CLI feedback (2026-11-18): user live transcript confirms startup,
answer/manual check/step acceptance and stats, but not final DONE (literal example
placeholder was rejected). Added short explicit evidence refs and removed duplicate
host state rendering. Offline tests verify final coverage and ref rejection; the
transcript does not establish native recovery or complete workflow live readiness.


### P10 explicit native command-check bindings (2026-11-18)

MOCK_VERIFIED: --check-commands loads separate user-owned bounded JSON bindings
for test/lint. Exact command/cwd are displayed before START; every test/lint must
be configured before backend startup. Future steps are registered by controller
step IDs; dispatch includes only current-step commands. Existing exact native
thread/turn/item/start/completion checks supply tool evidence. No local shell,
native command/exec bypass, model-based pass claims or manual test/lint override.
Known failures retain correction budget; missing/mismatched results UNVERIFIED.
No classifier, native recovery or expanded permission gate is enabled. Next live
check uses the small test_models.py sample, not the full suite inside a model turn.


P08/P10 deferred check fix (2026-11-18): user transcript exposed /check timing
confusion, not proof of accepted command evidence. Tool-only /check can now wait
for the current attempt terminal event; cancel/exit clears it. Manual checks remain
post-turn. This offline-tested fix does not change native permission/retry gates or
establish a new live verification result.


P08 confirmation feedback (2026-11-18): visible START was rejected before backend
startup on user's Terminal; exact raw input/cause unknown. Hardened blank-line and
complete single-line paste handling, with pseudo-terminal and offline regression
coverage. EOF and invalid/oversized input remain non-approval. An input-only check
can be run without Codex/inference before any further paid-quota live test.


P10 native evidence mismatch (2026-11-18): user's correctly timed /check returned
UNVERIFIED. Source of mismatch is unknown because old runtime omitted command
observations/diagnostics; do not claim a successful command-check live gate.
Offline-tested constrained shell-wrapper matching and persisted count-only unknown
evidence diagnostics now help future verification. No generic shell normalization,
permission expansion or acceptance of model assertions was introduced.


P08 full TTY confirmation fix (2026-11-18): input-only success did not prove full CLI
paste handling. A full pseudo-terminal regression reproduces multiline bracketed
paste rejection. Interactive input now uses stdlib readline; pipe handling remains
bounded and preserves subsequent commands. Cancellation remains fail-closed. User's
exact raw input and command-evidence live integration remain unverified; no new
inference is needed to check confirmation/exit without /next.


P08/P10 scoped live completion (2026-11-18): user-supplied explicit command-check
transcript reached DONE through observed tool pass and explicit 1=1.1 coverage,
with one requested gpt-6.1-sol/low attempt and no manual test override. See
VERIFICATION.md for provenance/version limitations. No further repeat is required
for this happy path. This does not close native recovery, all permission paths,
classifier/no-tools or private-web gates; no general production-ready claim.


### P12 durable native workflow resume increment (2026-11-18)

MOCK_VERIFIED: new explicit CLI workflows use durable threads and writer-locked
schema-v3 attachment. Local checkpoint exists before thread/start; each attempt
atomically clears the old native turn binding when reserved, and stores the new
turn ID only after a valid start response. Unknown response/save failure cannot
reassociate an old native turn with a new attempt.
Resume checks fresh account/catalog/quota, project/provider/thread identity,
non-ephemeral idle state, latest terminal/native binding and effective permissions.
It preserves IDs/counters, resets grants and requires explicit continuation.
Public --resume-workflow currently supports manual/rubric only; /revalidate cannot
accept tool checks. Previous accepted results remain stale until trusted rechecks.
Old ephemeral sessions and unknown/active/mismatched native state do not get a new
thread/turn fallback. --probe-workflow-resume is opt-in, two turns, retaining scratch
and durable thread for inspection. No live gate is passed by these offline tests.
Next: user-run synthetic resume probe before claiming the native happy path live;
then add trusted tool recheck recovery under separately verified permissions.


P12 verifier classification fix (2026-11-18): user test stopped before reconnect.
Retained checkpoint/rollout read-only inspection confirms completed ACK and unchanged
sentinel; schema-based regression shows userMessage metadata was miscounted as a
tool. Explicit metadata/tool classification and redacted prerequisite diagnostics
are offline verified; tool/unknown activity still stops. No new inference was run,
no test state was advanced, and native resume's live gate remains open.


P15 standalone installation increment (2026-11-18): documented user-local sr copy,
chmod, quoted Bash alias, update/hash comparison, uninstall and retained session/
native data. Four offline tests run only a copied executable from Thai/space paths
with no repo imports or Codex in PATH. Missing Codex is handled at shared process
startup with actionable guidance; missing plan files are not mislabeled as Codex
failures. No dependency, package registry, auto-update or user .bashrc edit added.


P12 scoped LIVE_VERIFIED update (2026-11-18): user-supplied corrected resume probe
passed durable reconnect, context recall, stale-evidence gate, final checkpoint and
sentinel. Runtime/verifier hashes match local 0a9c86b; diagnostics show userMessage
metadata and zero observed tool/unknown items. See VERIFICATION.md. This does not
close tool revalidation, crash/network, no-tools classifier or all permission gates.
No repeat is needed for this synthetic manual-check happy path.


P03/P12 tool recheck investigation (2026-11-18): standalone command/exec is a
candidate for checks without a model turn, but sandboxing alone does not establish
equivalence with native tool command rules and approval handling. Current upstream
source builds an execution request directly; the installed schema does not expose
a per-request approval policy. This approach is BLOCKED pending version-specific
enforcement evidence; P12 manual/rubric resume remains available. No direct-command
executor, local subprocess fallback or model turn was added. A transport regression
checks that standalone command requests are rejected before sending an RPC.
See VERIFICATION.md for sources, scope and the next required proof.


P03 standalone diagnostic increment (2026-11-18): probe_policy.py opt-in --run
evaluates a disposable allow/forbidden printf rules fixture with the installed CLI,
confirms its trusted project config before attempting at most two standalone
commands, and never sends account/thread/model RPCs. Configuration trust is scoped
to the disposable project and server process; user/managed settings remain in place.
The runtime RPC allowlists are unchanged. Connection accepts an optional subprocess
cwd so the server actually starts within the fixture project. Tests cover that cwd
and fail-closed prerequisites, bad outputs, approvals, EOF and no replay. This is
a negative diagnostic, not permission parity certification. Local Codex 0.169.0
matched fixture decisions but stopped at server_initialize, so no native command
was attempted. Next: run this no-inference probe from a normal user terminal to
collect version/hash-bound output; even a completed run does not close G2 or P12.

P03 probe correction (2026-11-18): user normal-terminal output reached project_config
with fixture decisions matched but no commands sent. Fix config/read to include the
fixture cwd explicitly; process cwd alone is insufficient for its project-layer
lookup. Add boolean-only prerequisite diagnostics and a fake-server regression
that does not supply project layers without the matching request cwd. Existing
trust/identity/marker checks remain required. Native result after this correction
is still pending; no permission gate is passed by the regression.

P03 trust encoding correction (2026-11-18): subsequent user boolean diagnostics
showed the fixture layer was discovered but disabled. Replace quoted dotted CLI
trust keys with a single projects inline-table value, because CLI override paths
split on literal dots. A regression covers dotted/space/Thai fixture paths, and
installed CLI accepts the new TOML value in a no-inference rule check. Do not
remove disabled-layer rejection or alter persistent/managed trust. Native result
after this correction remains pending.

P03 standalone probe completed (2026-11-18): version/hash-matched user report for
630cc24 reaches finished with all config booleans true; both baseline and forbidden
fixture printf commands execute. This is scoped negative evidence: standalone
permission parity is not established. Reject command/exec for current P12 tool
revalidation; do not repeat the probe seeking a pass or open the runtime allowlist.
See VERIFICATION.md for hashes and limits. Next eligible work: design an explicit
native-tool verification turn with model/quota consent, durable no-replay handling
and preserved correction/evidence gates. That alternative consumes model quota;
it is not the previously investigated zero-inference path and is not implemented.


P06 scope update and P12 durable recheck core (2026-11-18): user removed separate
decision models/classifiers. Delete unused classifier preparation/instructions,
keep explicit plan validation/role bindings/model approvals, and replace the offline
prompt's pending-classifier message with explicit entry-point guidance. Historical
verification entries above remain historical, not current classifier requirements.

P12 implementation contract: [NATIVE_RECHECK.md](NATIVE_RECHECK.md). Controller-only
recheck reservations now persist an append-only version-2 checkpoint ledger with
separate counters, native binding phases and observed terminal results. Existing
version-1 workflow checkpoints remain readable and unchanged until a reservation
is made; session metadata stays version 3. Writer lock, immutable ledger prefix and
poisoning after uncertain saves prevent silent replay/rollback. A known matching
completion can clear only its source stale tool evidence in the current process;
reconciliation after an unknown result or another restore cannot do so. Recheck
budgets survive model/command changes and require recorded continuation after 3
slots. Work counters/native bindings/criterion coverage are preserved. Metrics
separate work attempts from recheck reservations.

This is an offline state milestone, not enabled execution. No /recheck CLI, native
recheck transport or live verifier is connected yet. Test/lint resume remains
disabled. Next eligible P12 work is native observation/transport integration using
this ledger, then responsive UI/consent and retained-thread handling, then a scoped
opt-in live test. No user-run live test is needed for this core milestone.

P12 native recheck transport increment (2026-11-18): NativeRecheckConnection uses
the existing native protocol and command observer on a separate durable thread.
It checks fresh account/catalog/quota and work-thread identity/state, reserves the
parent ledger before thread creation, confirms native read-only/on-request settings,
and persists thread/turn phases before dispatch/draining. Selection/spec changes
cannot start a turn. Unsupported approvals are declined, cancellations never turn
late success into evidence, and conflicting later terminal observations invalidate
the earlier result without rewriting ledger history. Parent work bindings/counters
are unchanged. No command/exec or local runner is allowed.
This adapter is internal and offline-tested only. Public /recheck/tool-check resume
remain disabled. Next eligible work is event-loop/consent/CLI integration plus
retained-thread inspection/reconciliation/deletion handling, then the opt-in live
verifier. No live inference was run or requested for this increment.

P12 experimental recheck CLI (2026-11-19): explicit resume now offers an opt-in
--experimental-rechecks flag while default tool-check resume remains blocked.
START restores native ownership but /recheck only previews exact command/cwd and
standard/low model; a separate single-use /confirm-recheck token spends quota.
State/mode/policy/spec changes invalidate the preview. Budget continuation is a
separate explicit choice and does not dispatch. The existing selector multiplexes
parent and child native streams; status/cancel/exit/EOF stay responsive during a
bound turn, and child cleanup occurs while the parent writer attachment is held.
Known completed active tool evidence can be rebound without replaying old commands.
Missing/unknown active checks or unresolved rechecks refuse execution/resume.
Offline inspection displays retained native IDs; SessionStore.remove refuses to
discard recheck metadata. Native reconciliation/deletion remain unsupported.
Next: opt-in synthetic live verifier for this scoped experimental happy path;
not a no-tools boundary, production recovery or all-permission certification.

P12 live recheck verifier preparation (2026-11-19): --probe-rechecks MODEL with
--run-live requests at most two synthetic model turns, with no automatic retries.
It checks initial native command evidence, durable parent reconnect, stale evidence
blocking completion, inert consent preview, one explicitly confirmed native recheck,
unchanged work state/bindings and final checkpoint/sentinel. Reports are redacted
and versioned by runtime/verifier hashes; scratch and native threads remain retained.
Offline adversarial tests reject missing/unrelated tool observations, failure,
permission expansion, unsupported approval and unrelated errors masquerading as a
passed stale gate. The real account has not been exercised by the agent. Next:
user-run this one probe before claiming the experimental native happy path live.
Also fix native preflight to retain fresh catalog/policy in the parent host, so a
completed/failed recheck callback does not empty the UI catalog for the next preview.

P12 scoped live evidence update (2026-11-19): user ran --probe-rechecks gpt-6.1-sol
at version/hash-matched 732ac47. All seven checks passed; both completed turns had
one command start/completion and zero command/cwd mismatches. Mark only the
synthetic native recheck happy path LIVE_VERIFIED, not interactive Terminal timing,
unknown/crash/network recovery, scoped deletion, all permissions or actual dispatch.
See VERIFICATION.md for sanitized hashes/scope. No repeat of this probe is needed.
Next eligible P12 work is explicit reconciliation of known native recheck bindings
without replay or reusing historical evidence as current; scoped cleanup follows.


P12 known-binding recovery increment (2026-11-19): metadata-only recovery now
reconciles saved native recheck thread/turn identities under the session lock.
Active turns require explicit STOP and observed terminal status; historical
completion never restores current evidence or resets correction/recheck counters.
A metadata-only verifier reuses retained synthetic native threads on an isolated
local copy. Offline verification is complete; live metadata recovery remains
unverified because the agent environment did not complete App Server initialize.
Missing native bindings, scoped cleanup and broader crash/network recovery remain
open. No new model inference was requested for this increment.


P12 scoped recovery evidence update (2026-11-19): user-run metadata-only recovery
at 65d15f2 passed nativeTerminalObserved, metadataReconciled, historicalResultOnly
and sourceUnchanged with completed status, zero requested model turns, no native
deletion and no retained successful copy. Source hashes match; see VERIFICATION.md.
Known-binding terminal reconciliation is scoped LIVE_VERIFIED. Active interruption,
missing-binding discovery and broader crash/network recovery remain open. Next
eligible increment is scoped native-thread cleanup with preview and explicit
confirmation; no cleanup was performed by this documentation update.

P12 scoped cleanup implementation update (2026-11-19): `--delete-session SESSION_ID`
and existing session deletion cover ledger-bound recheck roots, work root and
previewed descendants. Explicit confirmation, per-root receipts and uncertain
outcome retention are MOCK_VERIFIED. Active interruption and scoped native deletion
still require evidence from a normal authenticated Terminal. See VERIFICATION.md.

P12 active-turn evidence update (2026-11-19): the user-run synthetic workflow
probe at `74dbba8` confirmed an interrupted terminal turn. This covers native
workflow cancellation in that probe. Scoped deletion and the separate retained
recheck STOP path still need live evidence. See VERIFICATION.md.

P05–P07 routing update (2026-11-19): opt-in `--suggest-models` recommends
role/effort from declared step kind, risk and check types using explicit role
bindings. Existing modes gate the resulting plan and Approve plan shows its
complete selections. Catalog acceptance and quota checks remain distinct from
quality evaluation. This policy has offline coverage; live comparison is P16.

P14/P16 follow-up (2026-11-19): workflow status shows current chat elapsed time,
step progress and activity counts, with full criteria and choices in /workflow.
EVALUATION.md defines the 12 planned paired cases. Actual telemetry and paired
live results are still pending.

P12 scoped deletion evidence update (2026-11-19): user Terminal output confirms
deletion of the two previewed roots in the original synthetic recheck scratch.
Local inspection found no remaining session and the scratch sentinel was intact.
Retained recheck STOP, missing-binding discovery and broader crash/network
recovery remain open. See VERIFICATION.md.

P12 missing-binding diagnostics (2026-11-21): scoped live recovery of a known,
already interrupted turn is recorded in VERIFICATION.md. Recovery now reports
the last persisted dispatch phase when a native binding is incomplete.
Offline coverage checks that all three incomplete phases leave metadata intact
and start no native process. P12 remains IN_PROGRESS. Discovery requires evidence
that uniquely ties a native thread or turn to the saved operation after a crash.
A project match or recent timestamp alone cannot establish ownership.
Active retained STOP still needs a live observation of an active binding.

P12 schema inspection (2026-11-21): Codex CLI 0.171.0 exposes a candidate
correlation field for new `turn_pending` rechecks with a known thread ID.
Next eligible P12 work is an opt-in synthetic persistence probe for that
field across reconnect before using it in recovery. `reserved` discovery
still lacks a verified native correlation mechanism. See VERIFICATION.md.

P12 turn correlation probe prepared (2026-11-21): the opt-in
`--probe-turn-correlation MODEL` verifier exercises one synthetic turn using
a checkpoint without a native turn ID, then looks up the client ID across a
fresh connection. All 24 verifier tests and 521 offline tests passed, covering
matching, missing and ambiguous history and the live opt-in. The next P12
gate is the user-run probe in VERIFICATION.md.

P12 correlated terminal recovery (2026-11-21): the user-run correlation
probe at `59bc1f0` passed on Codex CLI 0.171.0. New rechecks durably record
the client message ID before turn/start. Explicit recovery can now reconcile
a uniquely matched terminal turn in a known native thread. This integration
is MOCK_VERIFIED. The opt-in integration probe now simulates a missing turn ID
on an isolated copy after a completed synthetic recheck. The next eligible
P12 gate is the user-run probe documented in VERIFICATION.md. The case
without a saved thread ID remains open.

P12 scoped live integration evidence (2026-11-21): the user-run probe at
`b9349f0` passed all four missing-turn-ID recovery checks on Codex CLI
0.171.0, with zero recovery model turns. The fake-server suite separately
covers loss of the turn/start reply before local binding. The next eligible
P12 gate is active retained STOP on a confirmed active binding. A session
without a saved thread ID still lacks a verified correlation mechanism.

P12 active retained STOP probe prepared (2026-11-21): the recovery connection
is initialized before recheck dispatch and still checks fresh identity
before interruption. The probe requires proof of an acknowledged STOP RPC
and a terminal interrupted observation. The 13 focused probe tests and all
527 offline tests passed, including the race where the turn settles before
STOP is sent. The next eligible gate is the user-run STOP probe documented
in VERIFICATION.md.

P12 prewarmed STOP live result (2026-11-21): at `f864913` the independent
observer again reported interrupted before STOP. The live gate remains
unverified. The revised opt-in probe samples the owning connection around
the outside observation to diagnose cross-process disagreement separately
from a turn that settles early. The next eligible live check is the
diagnostic STOP run in VERIFICATION.md.

P12 STOP activation timing (2026-11-21): the user-run diagnostic showed the
owner transition from idle to active across the outside observation. The probe
now waits for owner activation before the outside read. Live retained STOP
is still unverified. Next evidence is an outside observation bracketed by
owner activation, or an acknowledged STOP followed by interrupted status.

P12 cross-server STOP result (2026-11-21): at `3fecef1` the owner was active
on both sides of an interrupted observation from the separate App Server.
Retained STOP remains unverified on the current transport. The next eligible
P12 work is a metadata-only shared-server connection spike. The initial
private Unix-socket smoke produced a listener but neither proxy initialized.
See VERIFICATION.md. The separate missing-thread-ID case remains open.

P12 shared-server connection spike (2026-11-21): the previous proxy smoke
sent newline JSON to a WebSocket listener. The diagnostic bridge now uses
WebSocket frames over the private Unix socket. Codex CLI 0.171.0 initialized
two clients and kept the first usable after the second disconnected, with
zero inference. The opt-in shared-server STOP probe is ready for scoped live
verification. Production transport and the separate-server STOP gate are
unchanged. See VERIFICATION.md.

P12 shared-server STOP evidence (2026-11-21): the user-run probe at
`b92db7b` passed all eight checks on Codex CLI 0.171.0. The live scope is
two connections to one private server while the recheck owner is connected.
P12 remains IN_PROGRESS. The next eligible work is scoping shared-server
ownership and lifecycle, including approval routing and owner disconnect,
before considering a production transport change. Separate-server STOP and
missing-thread discovery remain unverified. See VERIFICATION.md.

P12 shared-server owner disconnect probe prepared (2026-11-21): the verifier
drops the active synthetic recheck owner, checks the unknown checkpoint,
and observes the same binding through the surviving connection. Offline
tests cover a surviving active turn and a terminal turn. Next eligible live
evidence is the opt-in owner-disconnect run in VERIFICATION.md. Approval
ownership remains a separate shared-server check.

P12 shared-server owner disconnect evidence (2026-11-21): the user-run probe
at `ee5bc76` passed all nine checks on Codex CLI 0.171.0. The recheck turn
remained active after owner disconnect and a surviving client interrupted
it without replay. Next eligible P12 work is a synthetic shared-server
approval routing and owner-loss probe that grants no approval. This evidence
does not widen runtime transport or permission policy. See VERIFICATION.md.

P12 shared-server pending file approval probe prepared (2026-11-22):
the diagnostic observes one owner-bound request alongside a passive
metadata client, closes the owner without replying, and checks for terminal
state and absence of the marker. The next eligible gate is the opt-in
one-turn run in VERIFICATION.md; active subscribers and other approval
types remain outside this probe.

P12 shared approval evidence (2026-11-22): the user-run probe at da10207
established owner receipt and passive observation for one file approval.
The turn remained active after owner disconnect and the marker was absent.
The new explicit `--stop-orphaned-approval` probe checks whether the
surviving client can settle that active binding without an approval reply.
Next eligible gate is the user-run opt-in check in VERIFICATION.md.

P12 shared approval STOP evidence (2026-11-22): at `00c742f` all four checks
passed on Codex CLI 0.171.0. A passive observer interrupted an active turn
after the file-approval owner disconnected without replying. Next eligible
work is to design a private shared-server lifecycle for the standalone
runtime, including server lifetime, endpoint identity and approval boundaries.
Approval routing with additional subscribed clients, server loss and
missing-thread discovery remain open. See VERIFICATION.md.

P12 private recheck server design (2026-11-22): documented the first runtime
scope in NATIVE_RECHECK.md. An attached workflow owns the private server and
writer lock. Recheck execution and passive recovery use that server while the
parent is open. The next eligible implementation is the offline Unix WebSocket
and endpoint lifecycle spike for the standalone runtime. Runtime integration,
process-loss recovery and missing-thread discovery remain open.

P12 private transport spike (2026-11-22): the isolated standard-library
Unix WebSocket and process lifecycle prototype passed socket tests outside
the restricted bind environment. A metadata-only Codex CLI 0.171.0 smoke
initialized two clients and kept the first usable after the second closed.
Next eligible implementation is integrating the transport with the existing
JSON-RPC reader and selector without changing approval or ledger ownership.
See VERIFICATION.md.

P12 shared JSON-RPC integration (2026-11-23): the optional WebSocket wire
now feeds the existing runtime parser and selector. Offline checks cover
partial frames, notification/RPC ordering and rejection of observer
approval requests. The two-client metadata smoke passed on Codex CLI 0.171.0.
Next eligible work is folding the transport into the single-file runtime
and wiring experimental rechecks and recovery to the owning workflow.
See VERIFICATION.md.

P12 experimental runtime wiring (2026-11-23): the private transport lives
in the single-file runtime. The optional `--experimental-shared-rechecks`
path gives an attached experimental workflow lifecycle ownership of one
private recheck server. It keeps the parent available after recheck-client
loss and offers in-session inspection and single-use STOP confirmation.
Reconciliation is written through the attached controller so the ledger
on disk and in memory remains aligned. Next eligible work is an opt-in
runtime integration verifier for this path, followed by live verification.

P12 runtime-owned STOP probe prepared (2026-11-23): the opt-in verifier now
drives shared recheck and recovery through the attached runtime's private
server and ChatShell handlers. The offline fixture checks exact STOP,
single-use confirmation and coherent historical reconciliation. Next
eligible evidence is the user-run opt-in probe in VERIFICATION.md.

P12 runtime-owned STOP evidence (2026-11-23): the user-run probe at
`132d80c` passed all ten checks on Codex CLI 0.171.0. Verified scope is
the attached runtime and ChatShell handlers after recheck client loss,
while the workflow and private server stay open. Next eligible work is
interactive Terminal coverage of the experimental CLI path. Loss of the
runtime/server and missing-thread-ID discovery remain open.
