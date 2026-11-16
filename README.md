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
| `/sessions`, `/delete` | ยังไม่พร้อม รอ P11/P12 |

**ยังไม่มี autosave/resume ของ ModelMate** live thread เป็น ephemeral
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
```

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


## Session metadata storage (P11)

มี `SessionStore` ใน runtime แล้ว แต่ **ยังไม่เชื่อม autosave หรือ /sessions ในแชต**
ส่วนการ resume/cancel/delete จริงอยู่ใน P12

เก็บ schema version 1 ใต้ `$XDG_STATE_HOME/modelmate` หรือ
`~/.local/state/modelmate` แยกโปรเจกต์ด้วย SHA-256 ของ canonical real path
ใช้ session ID ที่ controller สร้าง ไม่ใช้ชื่อจากโมเดลเป็น filename
เก็บเฉพาะเป้าหมาย เกณฑ์ ขั้นงาน จำนวนรอบแก้ สถานะ สรุป และ Codex thread ID
ไม่มีสำเนา transcript, credentials หรือ approval grants
metadata เป้าหมาย/สรุปอาจมีข้อมูลส่วนตัว จึงใช้ directory 0700 และไฟล์ 0600
ไม่มีการเข้ารหัสหรือ cloud sync

Storage API รองรับ create/read/list และ `with store.edit(id)` เพื่อถือ exclusive
writer lock ตลอด context พร้อม atomic save ตอนออกตามปกติ
เรียก `store.save(record)` ภายใน context เพื่อ checkpoint ระหว่างงานได้
Exception ก่อน save จะไม่เขียนข้อมูลค้าง; process ที่สองแก้ session เดียวกันไม่ได้
symlink path ของโปรเจกต์เดียวกันใช้ identity เดียวกัน แต่ state-file symlink ถูกปฏิเสธ
ไฟล์ JSON เสียหรือ schema รุ่นที่ไม่รู้จักจะไม่ถูกเขียนทับ
ค่า permission profile ที่บันทึกเป็น metadata ไม่ใช่สิทธิ์อนุมัติให้กลับมาทำงานเอง
