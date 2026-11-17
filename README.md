# ModelMate

`sr` เป็นเป้าหมาย CLI ที่ช่วยเลือกโมเดล ระดับการคิด และขั้นตอนทำงาน
สำหรับงานโค้ด วิเคราะห์ วางแผน และเอกสาร ผ่าน ChatGPT/Codex subscription

**สถานะ: มี manual live chat แบบทดลอง; auto routing/workflow ยังไม่เชื่อมครบ**

## เริ่มใช้งาน

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
รุ่นนี้เลือกโมเดลเอง ไม่มี classifier/auto routing หรือวงจร plan→implement→review
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
python3 -m py_compile modelmate.py doctor.py verify.py
```

Default tests ใช้ JSONL subprocess/fake controller ไม่ใช้ quota จริง
ตัวเชื่อม live chat ผ่านการทดสอบจำลองแล้ว แต่ยังรอผลใช้งานสดจาก Terminal ของผู้ใช้
ผลตรวจสดที่ได้รับแล้วครอบคลุม account/catalog/quota, synthetic context recall,
การปฏิเสธ scratch command/patch และการรัน printf ตาม native policy

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
ยังไม่มี CLI entry point สำหรับโหลด workflow และยังไม่ต่อกับ native backend จึงไม่มี auto execution ในรุ่นนี้
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
ไม่มี built-in native transport หรือ command runner เพิ่ม และยังไม่รับ tool approval ใน workflow
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
