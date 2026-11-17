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
Auto workflow, no-tools classifier และ private web isolation ยังมี gates แยก

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
ผล classifier ผิดรูปแบบ: แสดงข้อผิดพลาด/พัก ไม่เดาเป็น SIMPLE แล้วลงมือ
classifier ต้องผ่าน quota/model policy เช่นเดียวกับ execution

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
| P06 | Plan schema / classifier / routing | P04, P05 | IN_PROGRESS: validator/preparation MOCK_VERIFIED; live classifier รอ P03 | จำเป็น |
| P07 | สามโหมดและ grants | P06 | MOCK_VERIFIED (offline policy) | จำเป็น |
| P08 | Terminal chat shell | P02, P07 | IN_PROGRESS: shell/workflow host UI MOCK_VERIFIED; native workflow entry point ยังไม่เปิด | ไม่จำเป็นถ้าไม่แตะ policy |
| P09 | Tool approval UI และ enforcement | P03, P08 | IN_PROGRESS: native command/patch UI MOCK_VERIFIED | จำเป็น |
| P10 | Workflow / checks / correction limit | P07, P09 | IN_PROGRESS: controller/checkpoints/UI/native transport MOCK_VERIFIED; public entry point pending live permission gates | จำเป็น |
| P11 | Local session persistence | P02 | MOCK_VERIFIED: storage API และ manual live checkpoints | ตรวจ data loss/privacy |
| P12 | Resume / cancel / delete | P10, P11 | IN_PROGRESS: manual happy path LIVE_VERIFIED; workflow checkpoint recovery MOCK_VERIFIED; live workflow/UI pending | จำเป็น |
| P13 | Web privacy boundary | P03, P09 | TODO | จำเป็น |
| P14 | Metrics และรายงาน | P10, P11 | TODO | ไม่จำเป็นถ้าไม่แตะ policy |
| P15 | ติดตั้งและเอกสารผู้ใช้ | P08, P12, P14 | TODO | ตรวจคำกล่าวอ้าง |
| P16 | End-to-end / evaluation / release | P01–P15 | TODO | จำเป็น |

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
ห้ามเรียก API classifier ที่ไม่อยู่ใน subscription catalog
role economy/standard/strong เป็น policy ไม่ใช่ข้อเท็จจริงถาวรของ vendor

ผ่านเมื่อ: unsupported model/effort ถูกปฏิเสธ, catalog pagination,
missing role, hidden model, catalog เปลี่ยนตอน resume และ manual selection
การเปลี่ยน model/effort ที่ยังไม่มี comparative policy ให้ถือว่าอาจยกระดับและถาม
ไม่รวม: auto benchmarking ทุก startup หรือ scraping ราคา

### P06 — Plan และ routing

ไฟล์: modelmate.py, tests/test_routing.py, synthetic plan fixtures
Implement validator ตาม section 5 ก่อนต่อ classifier
Classifier เป็น read-only/no-tools step ผ่าน quota gate และ model policy
เรียกเมื่อโจทย์ใหม่/ขอบเขตเปลี่ยน ไม่เรียกเพราะ approval reply หรือ status command
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

ไฟล์: modelmate.py, tests/test_workflow.py
มี WorkflowController แบบ offline แล้ว: ไม่มี network/process/tool execution
เชื่อม ModelApprovals และ quota_decision; dispatch descriptor ยังไม่ถูกส่งไป backend
เก็บ controller IDs, attempts/cycles/evidence และ user-choice ledger
ใช้ SessionStore.workflow เพื่อ autosave ทุก transition ภายใต้ writer lock และ restore จาก session schema v3
restore ไม่คืน approval/token/grant; active turn ที่ยังไม่ทราบผลต้อง reconcile ก่อน ไม่ replay
controller methods รับเฉพาะ trusted host/UI events ไม่ใช่ API ที่เปิดให้โมเดลเรียกโดยตรง
Controller ถือ state/step IDs/counters; classifier แค่เสนอ
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
