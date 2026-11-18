# ModelMate

`sr` เป็นเป้าหมาย CLI ที่ช่วยเลือกโมเดล ระดับการคิด และขั้นตอนทำงาน
สำหรับงานโค้ด วิเคราะห์ วางแผน และเอกสาร ผ่าน ChatGPT/Codex subscription

**สถานะ: มี manual live chat แบบทดลอง; auto routing/workflow ยังไม่เชื่อมครบ**

## เริ่มใช้งาน

ติดตั้ง runtime ไฟล์เดียวเป็นคำสั่ง `sr`: [คู่มือติดตั้ง/อัปเดต/ถอนติดตั้ง](docs/INSTALL.md)

ต้องมี Python 3.9+ และ Codex CLI (ตรวจ protocol กับ 0.169.0)
ใช้ Python standard library ไม่ต้องติดตั้ง `openai` หรือ Python dependency เพิ่ม
เข้าสู่ระบบด้วย ChatGPT ผ่าน `codex login` หากยังไม่ได้ล็อกอิน

ตรวจบัญชี โมเดล และ quota จาก Terminal ปกติก่อน:

```bash
python3 modelmate.py --doctor
```

คำสั่งนี้ไม่เรียก inference ข้อมูล `null` หมายถึงไม่ทราบ
Exit 0 หมายถึงอ่านสำเร็จ ไม่ใช่รับประกันว่าเริ่มงานได้
การเปิด App Server อาจเขียน runtime state ของ Codex ตามปกติ
ใน sandbox พัฒนาปัจจุบันติดสิทธิ์เขียน SQLite จึงยังรันการเชื่อมสดจากที่นั่นไม่ได้

## แชตกับโมเดลจริง (ทดลอง)

เลือก model ID และ effort ที่บัญชีแสดงในผล doctor:

```bash
python3 modelmate.py --live --model gpt-6.1-sol --effort low
python3 modelmate.py --live --model gpt-6-astra --effort medium "ช่วยวิเคราะห์โจทย์นี้"
python3 modelmate.py --live --model gpt-6-luna --effort low
python3 modelmate.py --live --model gpt-6.1-terra --effort low
```

**--live ใช้ quota subscription จริง** อ่านบัญชี/catalog/quota ใหม่ก่อนเริ่ม turn
หากอ่านไม่ได้ หมด quota ข้อมูลเก่า หรือบัญชีเปลี่ยน จะไม่เริ่ม turn ใหม่
ไม่ fallback ไป API key ไม่ซื้อเครดิตหรือเปลี่ยน Automatic reload
Preflight ไม่ใช่การจอง quota หรือ hard spending cap ของบริการ

โปรแกรมใช้ thread เดิมคุยต่อและส่งข้อความเพิ่มระหว่างตอบได้
เลือกโมเดลผ่าน manual selection หรือ explicit workflow role bindings
ตัด decision model/classifier แยกออกจากขอบเขตตามผู้ใช้ยืนยัน 2026-11-18
ไม่มีการเรียกโมเดลเพิ่มเพื่อเลือกโมเดลเริ่มต้น; auto routing จาก prompt ยังไม่เปิด

แกนบันทึก, native transport และ CLI ทดลองของ recheck มี offline tests แล้ว:
จองรอบแบบ durable แยกจาก work attempt, จำกัดรอบและไม่ replay ผลที่ยังไม่ทราบ
ค่าเริ่มต้นยังไม่เปิด tool-check resume; รุ่นทดลองต้องระบุ `--experimental-rechecks`
กับ `--resume-workflow`, command bindings และ `--execute-workflow`
`/recheck STEP.CHECK` แสดงคำสั่ง/โมเดล แล้ว `/confirm-recheck TOKEN` ใช้โควตาเพิ่ม
หนึ่ง verification turn Native threads ถูกเก็บไว้; unknown outcomes ยังต้องหยุด
และการลบ metadata ที่มี recheck ถูกปิดจนกว่าจะมี scoped cleanup
ดู [ข้อกำหนด native recheck](docs/NATIVE_RECHECK.md) สำหรับขอบเขตที่เหลือ
อัตโนมัติ ไม่เปิด effort ultra ที่มี automatic delegation
การส่ง model ID เป็นการร้องขอโมเดล ไม่ใช่ execution telemetry ที่ยืนยัน actual dispatch

## สิทธิ์ที่ใช้ใน live chat

ผู้ใช้เลือกพฤติกรรม Codex เมื่อ 2026-11-17:

- ค่าเริ่มต้น **read-only + on-request** คำสั่งที่ sandbox อนุญาตทำเองได้โดยไม่ถามทุกครั้ง
- คำขอขยายสิทธิ์ที่ Codex ส่งมาจะให้อนุมัติเป็นรายครั้ง
- แสดง exact command/cwd หรือ patch preview ก่อน `/approve TOKEN`
- `/decline TOKEN` ปฏิเสธ; `/pause TOKEN` ปฏิเสธและขอหยุด turn
- ไม่ใช้ acceptForSession และไม่เปิด workspace-write/full-access อัตโนมัติ
- ไม่มี patch preview, คำขอซ้อน หรือคำขอที่ยังไม่รองรับ จะปฏิเสธ/หยุด
- คง managed restrictions; ไม่อ้างว่า native readable roots จำกัดเฉพาะโปรเจกต์

ปิด hosted web search, apps/plugins และ agents ผ่าน config ของเส้นทาง live
แต่ยังไม่อ้างว่าเป็น universal no-tools isolation; native local tools ยังมีได้
project/user Codex configuration และ managed policy ยังมีผล
อ่านสถานะหลักฐานใน [PERMISSIONS.md](docs/PERMISSIONS.md)

## คำสั่งแชต

| คำสั่ง | สถานะปัจจุบัน |
| --- | --- |
| `/help`, `/status` | แสดงคำสั่งและสถานะล่าสุด; quota ที่แสดงอาจเป็น snapshot เก่า |
| `/model` | แสดง catalog และโมเดลที่เลือก |
| `/model ID [EFFORT]` | เลือกอย่างชัดเจนสำหรับงานถัดไปเมื่อไม่มีงาน active |
| `/approve TOKEN`, `/decline TOKEN`, `/pause TOKEN` | ตอบคำขอขยายสิทธิ์ครั้งเดียว |
| `/cancel`, Ctrl+C | ขอหยุดและรอ confirmation ไม่ถือว่า RPC acknowledgement แปลว่าหยุดแล้ว |
| `/exit`, EOF | ขอหยุดถ้ามีงาน active แล้วออก |
| `/mode` | สามโหมดมี policy ออฟไลน์; live ยังเป็น manual selection |
| `/permissions` | แสดง read_only; ยังไม่เปลี่ยน profile ทั้ง session |
| `/sessions` | แสดง session metadata ของโปรเจกต์ปัจจุบันใน live chat |
| `/sessions ID` | เปิด session เดิมเมื่อไม่มี turn/RPC ที่ค้างอยู่ |
| `/delete [ID]`, `/confirm-delete TOKEN` | แสดงขอบเขตแล้วลบ Codex thread/subtree และ metadata หลังยืนยัน |
| `/acknowledge TOKEN` | ยอมรับว่า outcome เดิมยังไม่ทราบ หลังตรวจไฟล์/process แล้ว; อนุญาตเฉพาะข้อความใหม่ |

**มี autosave/resume สำหรับ manual live chat และผ่านการทดสอบสดเส้นทางปกติแล้ว**
ใช้ thread แบบบันทึกลง Codex และเก็บ metadata ในเครื่องอัตโนมัติ
ผลสดครอบคลุม reconnect/recall/delete ในโปรเจกต์สังเคราะห์; ยังไม่ครอบคลุม crash recovery
หากขาดการเชื่อมต่อหรือหยุดไม่ได้ ผลของคำสั่งอาจไม่ทราบ
ไม่ retry หรือ replay คำสั่งให้อัตโนมัติ การอนุมัติให้เขียนอาจเปลี่ยนไฟล์จริง

เมื่อรันโดยไม่มี --live จะเปิด shell ออฟไลน์โดยไม่เปิด Codex/inference:

```bash
python3 modelmate.py
python3 modelmate.py --help
```

## ชุดตรวจ

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile modelmate.py doctor.py verify.py probe_policy.py
```

Default tests ใช้ JSONL subprocess/fake controller ไม่ใช้ quota จริง
ตัวเชื่อม live chat ผ่านการทดสอบจำลองแล้ว แต่ยังรอผลใช้งานสดจาก Terminal ของผู้ใช้
ผลตรวจสดที่ได้รับแล้วครอบคลุม account/catalog/quota, synthetic context recall,
การปฏิเสธ scratch command/patch และการรัน printf ตาม native policy

ตรวจเส้นทาง standalone command โดย **ไม่เรียกโมเดล** (เป็น diagnostic แยกจาก runtime):

```bash
python3 probe_policy.py --run
```

สร้าง config/rules สังเคราะห์ในโฟลเดอร์ชั่วคราว ตรวจ rule decisions และลอง native
`printf` ไม่เกินสองคำสั่ง ไม่แก้ config จริง ไม่เปิด tool recheck ให้เอง
Exit `1` หมายถึงคำสั่งใน deny fixture ยังรันได้; `2` หมายถึงยังยืนยันไม่ได้
ไม่มีผลจาก probe นี้ที่รับรอง permission parity อ่านขอบเขตใน
[ผลตรวจ standalone policy probe](docs/VERIFICATION.md#p03--no-inference-standalone-policy-probe-2026-11-18)

คำสั่งต่อไปนี้ **ใช้ quota จริง** เลือกรันเฉพาะกรณีที่ต้องตรวจ:

```bash
python3 verify.py --run-live --models gpt-6.1-sol gpt-6-astra
python3 verify.py --run-live --probe-read-approval gpt-6.1-sol
python3 verify.py --run-live --probe-sessions gpt-6.1-sol
```

`--probe-sessions` ใช้สอง turn ที่ effort low และเปิด App Server ใหม่ระหว่าง turn
เพื่อทดสอบบริบทหลัง reconnect ตรวจผ่าน runtime autosave/resume/delete จริง
สร้างโปรเจกต์และ state แยกในโฟลเดอร์ชั่วคราว ใช้เฉพาะรหัสสังเคราะห์
ยืนยันลบอัตโนมัติเฉพาะ thread ที่ตัวตรวจสร้าง เมื่อ preview มี thread เดียวตรงกัน
หากพบ descendants จะไม่ยืนยันลบ ตรวจ sentinel ก่อน/หลังลบ และตรวจประวัติ
ทั้ง active/archived listings หากผ่านจะล้าง scratch; หากผิดพลาดจะเก็บไว้พร้อมบอก path
ไม่มีการยืนยัน tool approval: ถ้าพบเครื่องมือจะไม่ถือว่าผ่านและขอหยุด turn
native sandbox อาจให้บางคำสั่งรันได้เองก่อนตรวจพบ จึงไม่อ้างว่าเป็น no-tools isolation
รายงาน JSON ไม่มี prompt/รหัส/บัญชี/thread ID/path และมี SHA-256 ของ runtime/verifier
เพื่อระบุรุ่นที่ตรวจ ไม่ยืนยัน actual model dispatch หรือการลบข้อมูลทั้งหมดฝั่งบริการ
ถ้าไม่ใส่ `--run-live` จะโชว์ help โดยไม่เปิด Codex

Read probe คืน `executed_without_approval` ได้ตาม native policy ที่ผู้ใช้เลือก
เป็นข้อมูลเกี่ยวกับพฤติกรรม ไม่ใช่ข้อรับประกันทุกเส้นทาง
Harness ยังคืน exit 1 สำหรับผลนี้เพื่อแยกจาก denial-scenario success
รายงานแยก requested model, observed thread settings และ actual dispatch ที่ยังไม่ทราบ
ไม่ commit raw account report, credentials, prompts หรือ local session logs

## เอกสารโครงการ

- [Design](docs/DESIGN.md)
- [Master plan และใบงาน](docs/MASTER_PLAN.md)
- [ผลตรวจและข้อจำกัด](docs/VERIFICATION.md)
- [กติกาสำหรับ agent ที่พัฒนาโครงการ](AGENTS.md)

ยังไม่รองรับผู้ให้บริการอื่น งานขนานหลาย agent หรือ web UI
การประหยัด quota และคุณภาพ routing ยังต้องประเมินกับงานจริง ไม่มี benchmark รับรอง

มี `WorkflowController` สำหรับทดสอบลำดับขั้น/ผลตรวจ/งบแก้ไขแบบออฟไลน์แล้ว
ผูกกับ `SessionStore.workflow(...)` เพื่อบันทึกแต่ละ transition และคืนสถานะข้าม process ได้
มี Workflow UI แบบ host-injected ผ่าน `run_chat(..., workflow=controller, workflow_action=host)` แล้ว
มี experimental explicit-plan CLI ตามหัวข้อด้านล่าง; ยังไม่มี auto execution และ CLI build นี้ยังรอ user-run live verification
รายละเอียดสัญญา trusted host callbacks และข้อจำกัดอยู่ใน [ผลตรวจ P10](docs/VERIFICATION.md)

เมื่อ host ผูก workflow เข้า shell จะมี `/workflow`, `/status`, `/next`, `/check`, `/mode`
และคำตอบตาม token เช่น `/approve`, `/decline`, `/continue`, `/revise`, `/pause`
แสดงแผน โมเดลที่เสนอ ขั้นปัจจุบัน จำนวนรอบ ผลตรวจ และจำนวนหลักฐานของแต่ละเกณฑ์
การอนุมัติไม่เริ่มงานเอง; `/next` ส่งคำขอไปยัง trusted host ซึ่งต้องตรวจ quota/catalog/model gates
ถ้าไม่มี host จะไม่ใช้ attempt slot หรือส่งงานใด ๆ `/cancel` และ `/exit` ขณะ active
จะขอหยุดและรอ controller terminal event; ยืนยันไม่ได้ภายใน deadline จะออกโดยระบุ outcome unknown
UI ไม่รับคำยืนยันผลตรวจจากข้อความโมเดล และไม่ให้ model approval แทน tool approval
คำสั่งเหล่านี้ยังไม่เปิดในแชตปกติหรือ `--live`; host integration ปัจจุบันทดสอบด้วยข้อมูลจำลอง

มี `WorkflowHost` สำหรับเชื่อม controller กับ transport callbacks ที่เชื่อถือได้แล้ว
host ต้องส่ง preflight ใหม่ และคืน thread/turn binding ก่อนส่ง protocol events เข้ามา
ลงทะเบียน check ด้วย command/cwd ที่ host ตรวจไว้ก่อน attempt; adapter จะรับผลเฉพาะ
item ที่มี start/completion ตรงกัน ผลจากคำสั่งอื่นหรือข้อความว่า “tests passed” ไม่ผ่านเป็นหลักฐาน
ใช้ `/check` ประเมินผลหลัง terminal event; ยังต้องมี host ยืนยัน coverage ของเกณฑ์ก่อน DONE
`executor_stream` ของ `run_chat` แยกจากข้อความโมเดลและ UI events และรับได้เฉพาะเมื่อผูก WorkflowHost
มี experimental native transport สำหรับ host API แต่ไม่มี command runner แยก และยังไม่รับ tool approval ใน workflow
producer ที่เชื่อถือได้ต้องบังคับ sandbox/approval policy แยกต่างหาก; การลงทะเบียน check ไม่อนุมัติคำสั่ง
timeout/disconnect ไม่ retry; binding/check registrations ไม่ถูก restore โดยเดา ต้องตรวจ native state ใหม่


## Session และการกลับมาทำต่อ (P11/P12)

เมื่อเปิด `--live` จะแสดง Session ID ใช้ `/sessions` เพื่อดูรายการ หรือเปิดใหม่ด้วย:

```bash
python3 modelmate.py --live --model gpt-6.1-sol --effort low --resume SESSION_ID
```

ต้องอยู่ในโปรเจกต์เดิม ใช้บัญชีเดิม และเลือก model/effort อย่างชัดเจนอีกครั้ง
ตรวจ account/catalog/quota ใหม่ และขอ read-only + on-request เสมอ ไม่คืน approval grants
การเปิด session ไม่ส่ง prompt หรือ replay งานเดิม การส่งข้อความใหม่ยังผ่าน quota preflight
เมื่อ quota หมดแต่ยังอ่านสถานะบัญชีได้ เปิดแชตเพื่อจัดการ/ลบ session ได้โดยไม่เริ่ม inference
`/sessions ID` ใช้เปลี่ยน session ระหว่างแชตเมื่อ backend ว่าง

หาก checkpoint ค้าง RUNNING/รอ tool approval จะตรวจสถานะ thread และ turn ล่าสุด
ถ้า backend ยัง active หรือข้อมูลไม่ครบ จะไม่ resume ถ้าจบแล้วแต่ผลเครื่องมือยังไม่ทราบ
จะพักและขอ `/acknowledge TOKEN` หลังผู้ใช้ตรวจไฟล์/process ใน Codex เอง
การยอมรับนี้อนุญาตให้ส่งข้อความใหม่ ไม่รับรองผลเดิมหรือทำให้เกณฑ์งานผ่าน
Ctrl+C หรือ `/exit` ระหว่างทำงานต้องรอ terminal event; RPC interrupt ack ไม่พอ

ใช้ `/delete ID` (หรือ `/delete` สำหรับ session ปัจจุบัน) เพื่อดูชื่อและรายการ
thread/descendants ก่อน `/confirm-delete TOKEN` ยืนยันครั้งเดียว
ตรวจขอบเขตซ้ำก่อนลบ หากเปลี่ยนต้องขอ preview ใหม่ ไม่ลบหรือย้อนแก้ไฟล์งาน
ลบ session ปัจจุบันสำเร็จแล้วจะออกจากแชต หาก remote deletion ล้มเหลว/ไม่ทราบผล
จะเก็บ metadata และบล็อกการส่งงานใน session นั้นเพื่อไม่ใช้ thread ที่อาจถูกลบแล้ว
หากยืนยัน remote deletion ได้แล้วแต่ลบ metadata ไม่สำเร็จ ให้ `/delete ID` อีกครั้ง
จะเก็บกวาดเฉพาะ metadata โดยไม่ส่ง remote delete ซ้ำ
หลังเปิดโปรแกรมใหม่ ใช้ live chat ใหม่แล้ว `/delete ID` จัดการรายการที่ลบค้างได้

ข้อจำกัด: scan ขอบเขตลบแบบมีเพดาน รวม archived subagents; หากอ่านไม่ครบจะไม่ลบ
หาก descendant มี ModelMate metadata แยก ต้องลบ descendant นั้นก่อน
protocol ไม่มี delete แบบล็อกตาม scope ที่ preview จึงไม่รับประกันกรณี client อื่น
เปลี่ยน subtree พร้อมกัน หากขาดการเชื่อมต่อหลัง remote delete แต่ก่อนบันทึก receipt
อาจเหลือ metadata ที่ต้องตรวจใน Codex เอง; ไม่ตีความ missing thread ว่าลบสำเร็จ
ไม่รับรองการลบข้อมูลทั้งหมดฝั่งบริการ

เก็บใต้ `$XDG_STATE_HOME/modelmate` หรือ
`~/.local/state/modelmate` แยกโปรเจกต์ด้วย SHA-256 ของ canonical real path
ใช้ session ID ที่ controller สร้าง ไม่ใช้ชื่อจากโมเดลเป็น filename
schema v2 เพิ่ม account fingerprint, turn ID และ deletion state จาก v1
ยังอ่าน v1 ได้ แต่ไม่ resume/delete thread ที่ไม่เคยผูกบัญชี และไม่อัปเกรดโดยเดาบัญชี
เก็บเป้าหมายจากข้อความแรกสูงสุด 4,096 ตัวอักษร ชื่อจาก 80 ตัวแรก เกณฑ์ ขั้นงาน
จำนวนรอบแก้ สถานะ สรุปของ controller และ Codex thread ID
ไม่มีสำเนา transcript, credentials หรือ approval grants
metadata เป้าหมาย/สรุปอาจมีข้อมูลส่วนตัว จึงใช้ directory 0700 และไฟล์ 0600
ไม่มีการเข้ารหัสหรือ cloud sync

Storage API รองรับ create/read/list และ `with store.edit(id)` เพื่อถือ exclusive
writer lock ตลอด context พร้อม atomic save ตอนออกตามปกติ
เรียก `store.save(record)` ภายใน context เพื่อ checkpoint ระหว่างงานได้
Live chat ถือ lock ตลอดเวลาที่เปิด session; process ที่สองเปิดเขียน session เดียวกันไม่ได้
Exception ก่อน save จะไม่เขียนข้อมูลค้าง
symlink path ของโปรเจกต์เดียวกันใช้ identity เดียวกัน แต่ state-file symlink ถูกปฏิเสธ
ไฟล์ JSON เสียหรือ schema รุ่นที่ไม่รู้จักจะไม่ถูกเขียนทับ
ค่า permission profile ที่บันทึกเป็น metadata ไม่ใช่สิทธิ์อนุมัติให้กลับมาทำงานเอง
มี persistence API ของ workflow/correction controller แล้ว แต่ยังไม่เชื่อม UI หรือ execution
session ที่ผูก workflow ใช้ schema v3 และ manual `--resume` จะปฏิเสธ เพื่อไม่ข้าม controller
P10/P12 ทั้งใบงานยังไม่ถือว่าเสร็จ

สำหรับ host integration: `SessionStore.workflow` ถือ lock ตลอด context และบันทึกก่อนคืน
dispatch descriptor/ผล transition หากเขียนดิสก์ไม่สำเร็จจะ raise และไม่คืน descriptor ให้ส่งงาน
เมื่อออกจาก context controller นั้นใช้ต่อไม่ได้ ต้อง restore ใหม่
เก็บ step IDs, attempts/cycles, ledger และหลักฐาน แต่ไม่เก็บ approval grants/tokens หรือ raw account ID
อ่าน schema v1/v2 เดิมได้ตามปกติ และไม่อัปเกรดจนกว่าจะผูก workflow อย่างชัดเจน
การ restore ต้องมี quota/account/catalog snapshot ใหม่และตรวจ baseline ที่ยังรองรับ
งานที่กำลังรันจะพักเป็น outcome_unknown; งาน DONE เดิมคืนเป็น UNVERIFIED
host ต้องตรวจ native thread/process/files และหลักฐานปัจจุบันก่อนยืนยันผลหรือทำต่อ
checkpoint เต็มไฟล์จำกัด 1 MiB และ ledger 4,096 events; เกินเพดานจะไม่บันทึกทับหรือตัดประวัติทิ้ง

ดูข้อมูลที่บันทึกไว้ของโปรเจกต์ปัจจุบันโดยไม่เปิด Codex หรือล็อกอิน:

```bash
python3 modelmate.py --sessions
python3 modelmate.py --show-workflow SESSION_ID
```

`--show-workflow` ใช้กับ session ที่มี workflow checkpoint เท่านั้น แสดงขั้นงาน
จำนวน attempt และผลตรวจที่บันทึกไว้ ไม่ resume ไม่คืน approval และไม่สร้าง
state directory หรือ lock เพิ่ม สถานะ `DONE` เป็นผลเก่าใน checkpoint ไม่ใช่
การตรวจไฟล์หรือ backend ปัจจุบัน คำสั่งอ่านข้อมูลไม่ใช้โควตาโมเดล

เมื่อ restore workflow ผลตรวจเดิมเป็น `stale` จน trusted host ตรวจหลักฐานปัจจุบัน
แล้วเรียก `revalidate_check(evidence_id, origin=..., exit_code=..., reference=..., finding=...)`
ให้ครบก่อนประเมิน attempt หรือจบงาน การยืนยัน terminal status อย่างเดียวไม่ยืนยันผลตรวจ
ผลใหม่ต้องทราบและตรงกับผลเดิม มิฉะนั้นคง unverified เพื่อให้ host จัดการต่ออย่างชัดเจน
การยืนยันนี้ไม่ถูกเก็บข้าม restore และไม่สั่งรันคำสั่งหรือโมเดลซ้ำเอง

### Experimental native workflow transport

`NativeWorkflowConnection` เชื่อม explicit `WorkflowController` กับ Codex App Server
และ `run_chat(..., workflow=controller, workflow_action=host, backend=connection)`
โดย `connection.connect(controller, cwd, role_policy)` คืน host สำหรับลงทะเบียน checks
ใช้ native read-only/on-request และ model/effort override ราย turn; host API ที่ไม่ส่ง store ยังเป็น ephemeral แต่ explicit CLI ใหม่ใช้ durable thread
ตัว transport ตรวจ subscription/catalog/quota ก่อนส่งงาน และยืนยัน sandbox จาก thread/start
คำขอ tool approval จะถูก decline และพัก; ไม่ยกระดับสิทธิ์ ไม่เปิด classifier/auto routing

มี explicit-plan CLI แบบ opt-in และ experimental durable resume สำหรับ manual/rubric ตามหัวข้อด้านล่าง
caller ต้องปิด connection ใน `finally` และถือ timeout/start failure ว่า outcome unknown
ไม่เรียก dispatch ซ้ำเอง การเรียก native host API จริงใช้โควตา; tests ใช้ fake server เท่านั้น
การตั้ง model/effort เป็นเพียงค่าที่ร้องขอ ไม่ใช่หลักฐาน backend dispatch

Native workflow แสดงข้อความจาก `agentMessage` ที่ completed และตรง thread/turn
ปัจจุบันเพียงครั้งเดียวต่อ item ผ่าน UI ที่กรอง terminal controls ไม่พิมพ์ delta ซ้ำ
ข้อความเป็นข้อมูลแสดงผลเท่านั้น ไม่ยืนยัน checks หรือเปลี่ยนสถานะงาน และไม่ถูก
คัดลอกลง checkpoint; ข้อความจาก thread/turn อื่นหรือหลัง terminal event ถูกละทิ้ง

### ทดสอบ native workflow จริงแบบ opt-in

```bash
python3 verify.py --run-live --probe-workflow gpt-6.1-sol
```

ใช้ได้หลังติดตั้ง Codex และล็อกอิน ChatGPT; ใช้โควตา subscription สูงสุด 4 turns
ที่ effort low ไม่มี retry: จำรหัส/ถามกลับ 2 turns, ทดลองปฏิเสธการเขียน
`sentinel.txt` ในโฟลเดอร์ scratch ที่ verifier สร้าง 1 turn และ cancel 1 turn
ไม่ใช้โปรเจกต์ปัจจุบันเป็นพื้นที่ทดสอบ ไม่อนุมัติคำขอเครื่องมือหรือขยาย sandbox

ผล JSON แยก `passed`, `failed`, `unverified` พร้อม hashes ของ runtime/verifier
หากไม่เกิด approval หรือ turn จบก่อน cancel จะเป็น unverified ไม่ใช่ผ่าน
exit 0 เฉพาะทุกการตรวจผ่าน; exit 1 เมื่อมี failed/unverified อย่ารันซ้ำอัตโนมัติ
กรณีไม่ครบจะเก็บ scratch พร้อมพิมพ์ตำแหน่งทาง stderr เพื่อตรวจ ก่อนลองใหม่ให้
ตรวจสถานะ Codex เดิมด้วย เพราะ timeout ไม่ได้ยืนยันว่าหยุดแล้ว

`disconnectGuard` ทดสอบเฉพาะ local host ปฏิเสธ dispatch หลัง disconnect
ไม่ใช่หลักฐาน network-drop recovery ผลนี้ไม่พิสูจน์ทุก tool path, actual model
backend dispatch หรือการลบข้อมูลทั้งหมดฝั่งบริการ; ephemeral ไม่ใช่ delete guarantee
การผ่าน verifier ยังไม่เปิด auto routing/native workflow CLI โดยอัตโนมัติ

Verifier ตรวจคำตอบจากข้อความที่ UI เขียนจริง แยกจากแผน/status และตรวจ disconnect
จากสถานะ READY พร้อม tripwire ป้องกันการเรียกโมเดลเพิ่มแม้ guard เสีย
ผล `answerDisplay`/`disconnectGuard` จาก verifier ก่อนแก้ PR #7 ยังไม่ถือเป็น
หลักฐาน live สำหรับสองหัวข้อนี้ ต้องใช้ผลจาก verifier ที่แก้แล้วพร้อม hash ใหม่

### Explicit-plan CLI (experimental, manual steps)

Preview แผนและ model bindings แบบ offline ไม่เปิด backend หรือสร้าง session:

```bash
python3 modelmate.py --workflow examples/explain-lists.json --role-model standard=gpt-6.1-sol
```

เริ่มแบบ opt-in โดยใช้โควตาเมื่อสั่ง `/next`:

```bash
python3 modelmate.py --workflow examples/explain-lists.json --role-model standard=gpt-6.1-sol --execute-workflow
```

อ่านแผนแล้วพิมพ์ `START` เพื่อยืนยัน จากนั้นใช้คำสั่งตามลำดับ:

```text
/next
/verify 1 pass
/check
/finish 1=1.1
/exit
```

รอคำตอบและ terminal event ก่อน `/verify` ตรวจคำตอบเองก่อนระบุ `pass`
`/verify` รับเฉพาะ manual/rubric checks; ค่าที่รับคือ pass/fail/unknown
หมายเลข check เริ่มที่ 1 ในขั้นปัจจุบัน ใช้ `/check` เพื่อประเมินและไปขั้นถัดไป
หาก fail จะใช้ correction budget เดิม; unknown/missing ไม่ถือว่าผ่าน
`1.1` หมายถึงขั้น 1 check 1 ตาม `ref` ที่แสดง ใช้ได้หลัง `/check` ยอมรับขั้นนั้นแล้ว
`/finish` ต้องระบุหลักฐานสำหรับทุกเกณฑ์ เช่น `/finish 1=1.1 2=2.1,2.2`
เลือกเฉพาะหลักฐานที่รองรับเกณฑ์จริง UUID เดิมยังใช้ได้ แต่ไม่ต้องคัดลอกแล้ว
ไม่อนุญาตให้โมเดลจบงานเอง
การออกจาก CLI สำเร็จไม่ได้แปลว่างานผ่านเกณฑ์ ต้องดูสถานะ DONE แยกต่างหาก

ทุก role ที่แผนใช้รวม standard baseline ต้องมี `--role-model ROLE=MODEL`
ใช้ `--workflow-mode auto|ask_to_escalate|approve_plan` ได้; default ask_to_escalate
นี่คือ model policy เท่านั้น ทุกโหมดยังต้องสั่ง `/next` เอง และไม่อนุมัติ tools
เพิ่มสิทธิ์จะถูก decline/pause ตาม native transport รุ่นนี้; read-only/on-request
ยังอนุญาตคำสั่งที่ sandbox อนุญาตให้ทำงานเองตามพฤติกรรม Codex

รุ่นนี้รับแผนที่ไม่มี clarifications, manual/rubric checks และ test/lint ที่ผูก
คำสั่งผ่าน --check-commands ตามหัวข้อด้านล่าง; source checks ยังไม่เปิด
checkpoint บันทึกอัตโนมัติแยกโปรเจกต์ ดูด้วย `--sessions`/`--show-workflow ID`
session ใหม่เป็น durable; experimental resume รองรับ manual/rubric ตามหัวข้อด้านล่าง
ห้ามใช้ manual chat ข้าม checkpoint ผลค้าง และห้ามเริ่มคำสั่งเดิมซ้ำเมื่อผลยังไม่ทราบ

The explicit command-check happy path has user-supplied live evidence recorded in
docs/VERIFICATION.md, including its version limitations. Classifier/auto routing,
broader permission paths, private-web isolation and native recovery remain gated.


ตอนจบ explicit workflow session จะแสดง `สถิติ workflow` เป็น JSON: elapsedSeconds
รวมเวลารอผู้ใช้, จำนวน attempts, requestedSelections และ state ส่วน reportedModels
และ tokenUsage เป็น null เมื่อยังไม่มีข้อมูล ไม่ได้คำนวณค่าใช้จ่ายหรืออ้างว่าประหยัด


### ผูก test/lint กับคำสั่งที่ผู้ใช้ยืนยัน

แยกคำสั่งจากแผนโมเดลเป็นไฟล์ JSON version 1: `checks` แต่ละรายการต้องมี
`step`, `check` (เลขเริ่มที่ 1), `command`, `cwd` เท่านั้น ดูตัวอย่าง
`examples/check-model-policy.commands.json` cwd สัมพัทธ์อ้างอิงโฟลเดอร์โปรเจกต์
ปัจจุบัน และถูก resolve เป็น absolute path ก่อนแสดงยืนยัน ไฟล์จำกัด 64 KiB
ห้ามผูก check ซ้ำ หรือใช้ command/cwd เดียวกันซ้ำหลาย checks ภายในขั้นเดียว

ดู preview แบบ offline ก่อน:

```bash
python3 modelmate.py --workflow examples/check-model-policy.json --check-commands examples/check-model-policy.commands.json --role-model standard=gpt-6.1-sol
```

เพิ่ม `--execute-workflow` เพื่อเริ่มแบบ opt-in แล้วตรวจคำสั่ง/cwd ก่อนพิมพ์ START
ทุก test/lint ต้องมี binding ครบก่อนเปิด backend รูปแบบ preview ใช้ JSON escapes
เพื่อแสดง control/bidi characters อย่างชัดเจน ไม่แอบตัดออกจาก command ที่ยืนยัน

Native Codex จะได้รับคำสั่งตรวจของขั้นปัจจุบัน ให้รันหลังทำงานในขั้นนั้นเพียงครั้งเดียว
ภายใน model turn เดียวกัน จากนั้นรอ terminal event แล้วใช้:

```text
/check
/finish 1=1.1
/exit
```

ตัวอย่างนี้ไม่ต้อง `/verify`: exit code มาจาก native command start/completion
ที่ตรง thread/turn/item/command/cwd จริง รหัส 0 คือผ่าน รหัสอื่นคือไม่ผ่าน
missing/declined/unknown หรือคำสั่งเปลี่ยนรูปแบบเป็น UNVERIFIED; ข้อความโมเดล
ว่า tests passed ไม่ใช่หลักฐาน และ `/verify` ไม่รับ test/lint โดยตรง

ไม่มี local shell fallback, command/exec ทางลัด หรือการเพิ่ม sandbox permissions
การยืนยัน START ไม่ใช่ tool approval; native read-only/on-request ยังคงบังคับ
คำสั่งที่ sandbox อนุญาตอาจรันเองได้ ส่วน approval requests จะถูก decline/pause
คำสั่งที่รันซ้ำหลาย item ภายใน attempt ไม่ถูกนับเป็น hidden correction
check failure ใช้ initial attempt + corrections 2 รอบเหมือนเดิม แล้วต้องหยุดถาม

นี่คือการผูกผลคำสั่งใน turn นั้น ไม่ใช่การรับประกันไฟล์ทั้งหมดไม่เปลี่ยนภายหลัง
bindings ไม่ถูก persist และ public resume ของ test/lint ยังไม่เปิด; metadata เก็บผล/IDs
ตามเดิมโดยไม่คัดลอก stdout/stderr ตัวอย่าง test_models.py มีผล user-run live ถึง DONE แล้ว
ดูขอบเขตและข้อจำกัดของหลักฐานใน docs/VERIFICATION.md


สำหรับขั้นที่มีเฉพาะ test/lint: หากสั่ง `/check` ระหว่าง RUNNING ระบบจะรอ
terminal event ของ attempt นั้นแล้วตรวจครั้งเดียว ไม่มี model turn เพิ่ม
การกดซ้ำไม่เพิ่มงาน และ `/cancel` หรือ `/exit` ล้างคำขอที่รอไว้
manual/rubric ไม่รองรับการรอตรวจล่วงหน้า ต้องรอ CHECKING และ `/verify` ก่อน
ถ้าไม่ได้สั่งล่วงหน้า เมื่อเห็น CHECKING ให้พิมพ์ `/check` ก่อน `/finish`
ข้อความโมเดลที่เริ่มพูดหรือบอกผลไม่ได้หมายความว่า backend จบ turn แล้ว


START confirmation ข้ามบรรทัดว่างที่อาจค้างจากการ paste โดยไม่ถือว่ายืนยัน
รองรับ bracketed-paste wrapper ที่ครบในบรรทัดเดียว ข้อมูลอื่น/EOF/ข้อความยาว
เกิน 256 bytes ไม่เปิด backend wrapper ที่ไม่ครบจะถูกปฏิเสธ ให้พิมพ์ START เอง
การอ่านยังไม่กินคำสั่ง /next ที่อยู่ถัดไป และการยืนยันไม่ใช้ TextIO read-ahead


Command matching รับ literal command หรือ shell argv wrapper หนึ่งชั้นจาก
`/bin/bash`, `/usr/bin/bash`, `/bin/sh`, `/usr/bin/sh` พร้อม `-c`/`-lc` เท่านั้น
inner command ต้องตรงทุกตัวอักษร, ไม่มี argv เพิ่ม และ cwd ต้องตรงเดิม
ไม่ทำ generic token normalization, ไม่ตัด `cd`/`&&`/`;` หรือเปลี่ยน quoting ภายใน
command code เพื่อให้ผ่าน Wrapper support เป็นขอบเขต matcher ที่ทดสอบ offline;
ไม่ได้พิสูจน์ว่า wrapper คือต้นเหตุของ live UNVERIFIED ที่ผู้ใช้ส่งมา

เมื่อไม่มี matching command completion จะเก็บ check เป็น unknown และแสดง
`diagnostics` เฉพาะจำนวน started/completed/command_mismatches/cwd_mismatches
ไม่มี raw command, path, stdout/stderr ใน diagnostics; เก็บ counts ใน finding
ของ unknown evidence เพื่อย้อนตรวจได้ ไม่ยอมรับคำว่า tests passed จากโมเดลแทน


Interactive TTY confirmation ใช้ Python input/readline เพื่อรองรับการแก้ข้อความ
และ paste ที่มี newline ภายใน wrapper; stdin/stdout ที่เป็น pipe ยังคงใช้ byte
reader เดิมเพื่อไม่กินคำสั่งถัดไป หากยืนยันไม่ตรง จะแสดง input diagnostics
เฉพาะ byte count/ascii/control count/paste-marker flag ไม่คัดลอกข้อความดิบ
EOF, CANCEL และข้อความอื่นยังไม่เปิด backend; ไม่มีการยืนยันโดยอัตโนมัติ


### Durable workflow resume (experimental, manual/rubric)

explicit CLI session ใหม่บันทึก durable native thread; host API/verifier ที่ไม่ส่ง
SessionStore ยังใช้ ephemeral ตามเดิม session เก่าที่เป็น ephemeral จะไม่ถูกแปลง
หรือสร้าง thread ใหม่แทนโดยอัตโนมัติ หาก native thread หาย/ยัง active/identity
หรือ permissions ไม่ตรง จะหยุดโดยไม่ replay งาน

ใช้ `--sessions` เพื่อเลือก ID จริงในโปรเจกต์ แล้วแทน `SESSION_ID` ด้านล่าง:

```bash
python3 modelmate.py --resume-workflow SESSION_ID --role-model standard=gpt-6.1-sol
python3 modelmate.py --resume-workflow SESSION_ID --role-model standard=gpt-6.1-sol --execute-workflow
```

คำสั่งแรกเป็น preview แบบ offline คำสั่งที่สองต้องยืนยัน START เช่นเดิม
ตรวจบัญชี/project/catalog/quota/native thread/ล่าสุด turn และ read-only/on-request
ใหม่ทั้งหมด writer lock ถือจน connection ปิด; ไม่มีการคืน model/tool grants เดิม
ต้อง `/continue TOKEN` ที่แสดงใหม่ก่อน `/next` ไม่เริ่มงานเองหลัง reconnect
step IDs/attempts/correction budget เดิมยังอยู่ ถ้า native start outcome ไม่ทราบ
หรือ turn ID ไม่ตรง checkpoint จะไม่เดา ไม่ใช้ turn เก่าแทน และไม่เริ่ม turn ใหม่

ผลตรวจที่ restore มาเป็น stale ตรวจผลปัจจุบันก่อนยืนยัน เช่น:

```text
/revalidate 1.1 pass
```

รับเฉพาะ manual/rubric และผลที่ตรงกับหลักฐานเดิม ยืนยันนี้ไม่ข้าม restore รอบใหม่
`/finish` ยังต้องมี accepted evidence ครบและไม่มี stale checks
ผล test/lint เก่าต้องตรวจด้วย trusted tool ใหม่ จึงยังไม่เปิด public CLI resume
สำหรับแผนที่มี test/lint แทนที่จะให้มือยืนยัน exit code ข้าม gate
Native recovery ที่ active turn จบแล้วอาจเปิดเป็น CHECKING/PAUSED; terminal status
ไม่เท่ากับ tests ผ่าน หาก cached/native state ขัดกันจะไม่ทำงานต่อ

ตรวจ happy path แบบ opt-in ด้วยคำสั่งเดียว (สูงสุด 2 turns, ไม่มี retry):

```bash
python3 verify.py --run-live --probe-workflow-resume gpt-6.1-sol
```

ตรวจ context หลัง process restart, IDs/counters, stale-evidence gate และ DONE
รายงาน hashes โดยไม่พิมพ์ nonce/account/thread IDs ตัว probe จะ **เก็บ scratch
และ durable thread ไว้** พร้อมตำแหน่งทาง stderr เพื่อให้ตรวจย้อนหลัง ไม่ลบ thread
หรืออ้าง complete erasure หากมี failed/unverified ให้หยุด ไม่รันซ้ำอัตโนมัติ
ผลนี้ไม่ใช่ proof ของ no-tools security boundary, network/crash recovery ทุกกรณี
หรือ backend dispatch telemetry; synthetic manual-check resume มีผล user-run live
ผ่านแล้วที่ hashes ใน docs/VERIFICATION.md ส่วน tool-check recovery ยังไม่เปิด

สถิติ `attemptsScope=workflow_total` รวมประวัติเดิม ส่วน `elapsedScope=current_cli_session`
วัด session CLI ปัจจุบันรวมเวลารอผู้ใช้ requestedSelections รวมค่าที่ร้องขอในประวัติ
ไม่ใช่จำนวน model calls ใหม่ในรอบ reconnect และ reportedModels/tokenUsage ยังเป็น null


Resume verifier แยก userMessage/metadata ออกจาก tool items ตาม schema
`firstTurn`/`recallTurn` แสดงเฉพาะ counts, terminal status และ exact-answer boolean
ไม่แสดงคำตอบ/nonce; `failureReason` แยกคำตอบไม่ตรง, turn ไม่จบ, tool activity
และชนิด item ไม่รู้จัก ถ้าหยุดก่อน reconnect ค่า durableResume เป็น unverified
ผล sentinel ที่ตรวจได้ยังรายงานแยกตามจริง โดยไม่ต้องรันโมเดลซ้ำเพื่อเช็กไฟล์
