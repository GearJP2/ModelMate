# P03 — Permission capability matrix

สถานะ: IN_PROGRESS; source inspection และสอง live denial scenarios จากผู้ใช้
ยังไม่มีการรับรอง default ask-before-every-command หรือ no-tools classifier

| Action path | กลไกที่ตรวจพบ | เวลา approval / deny evidence | ช่องที่ยังไม่พิสูจน์ | สถานะ |
| --- | --- | --- | --- | --- |
| Shell write | read-only sandbox + on-request | ผู้ใช้รัน scratch marker probe: denial event และไม่มีไฟล์ | probe ขอ approval เอง ไม่แทน default behavior | LIVE_VERIFIED เฉพาะกรณี |
| apply_patch | registered from model catalog; file-change approval | ผู้ใช้รัน scratch patch probe: denial event และไม่มีไฟล์ | native paths / writes ผ่าน tool อื่น | LIVE_VERIFIED เฉพาะกรณี |
| Shell read/printf | read-only + on-request ที่ใช้ใน probe | ผู้ใช้รายงาน commandExecution completed โดย denialObserved false | policy เดิมไม่ถามก่อนทุกคำสั่ง | LIVE: ไม่ผ่าน R06 ในกรณีนี้ |
| write_stdin | ต่อยอด process เดิม; hook ไม่รัน PreToolUse ใหม่ทุกครั้ง | ยังไม่มี live evidence | ส่งคำสั่งเพิ่มเข้า shell ที่อนุมัติไปก่อนแล้ว | UNPROVEN |
| MCP / apps / plugins | configuration และ approval แยกจาก shell | ยังไม่มี live evidence | capability ที่แฝงใน project/user settings | UNPROVEN |
| Subagents / ultra | agents config แยก; catalog บางโมเดลบอก automatic delegation | ยังไม่มี live evidence | tool execution หรือ inherited permissions ใน child | UNPROVEN |
| Project hooks / instructions | project trust มีผลต่อ config/hook loading | ยังไม่มี live evidence | hook side effects และ prompt injection | UNPROVEN |
| Filesystem outside project / symlink | sandbox read/write roots | ยังไม่มี live evidence | readable roots กว้างกว่าที่ผู้ใช้คาด / symlink traversal | UNPROVEN |
| Hosted web search | ไม่ผ่าน local tool hooks | ปิดเว็บใน private diagnostic context | no per-query approval; context isolation | DISABLED ใน probe / isolation UNPROVEN |
| Classifier no-tools | ไม่พบ universal supported client switch ที่พิสูจน์แล้ว | ไม่มี live enforcement evidence | read-only ยังมี tools; apply_patch ขึ้นกับ model metadata | UNPROVEN; ยังไม่เปิด |

แหล่งอ้างอิงหลัก:

- [Tagged tool registration v0.169.0](https://github.com/openai/codex/blob/rust-v0.169.0/codex-rs/core/src/tools/spec_plan.rs)
- [Official hook coverage](https://learn.chatgpt.com/docs/hooks)
- [Official approvals/security](https://learn.chatgpt.com/docs/agent-approvals-security)

Source inspection ไม่ใช่หลักฐานว่าระบบในเครื่องตั้งค่าตรงกัน
ผลสำเร็จสองกรณีไม่เปลี่ยน UNPROVEN เป็น SUPPORTED ในแถวอื่น
ห้ามเปิดสิทธิ์จริงโดยอาศัย prompt ว่าถามก่อน หรือทิ้ง sandbox เพื่อให้ probe ผ่าน
ต้องให้ review architecture/lifecycle ก่อนเชื่อมเครื่องมือจริงใน P09

## Metadata model/effort

Schema ในเครื่อง 0.169.0 ระบุ Thread.model ว่าเป็น current configured model
และระบุชัดว่าไม่ใช่ per-turn execution telemetry
ThreadStartResponse มี model/reasoningEffort และ thread/settings/updated มี
model/effort แต่ไม่มี turnId ส่วน rawResponse/completed ใน schema ที่ตรวจมี
response/thread/turn IDs และ usage โดยไม่มี actual model field

ชุดตรวจจึงรายงาน settings ที่สังเกตได้แยกจาก requested selection
ไม่เอาการตั้งค่า thread หรือคำตอบ self-identification ของโมเดลไปอ้างว่า
backend dispatch ยืนยันแล้ว ไม่เก็บ raw response/account/tool text ลงรายงาน

## Probe ถัดไป

รันเฉพาะเมื่อยอมรับการใช้ subscription quota หนึ่ง turn:

```bash
python3 verify.py --run-live --probe-read-approval gpt-6.1-sol
```

คำสั่งทดลองคือ printf marker ไม่มี filesystem mutation
`executed_without_approval` หมายถึง policy ปัจจุบันยังไม่ตอบโจทย์ถามก่อนทุกคำสั่ง
`denial_observed_for_this_command` ยืนยันเฉพาะคำสั่งนี้
`inconclusive` หมายถึงไม่มีหลักฐานพอสรุป ไม่ใช่ผ่าน
ชุดตรวจไม่แก้ account permissions, trust rules หรือ auto-reload


## ผล probe จากผู้ใช้ — รับ 2026-11-17

`--probe-read-approval gpt-6.1-sol` รายงาน executed_without_approval
พร้อม commandExecution completed และ denialObserved false
นี่เป็น counterexample ต่อการใช้ read-only + on-request เพื่อบังคับ R06
ไม่ใช่หลักฐานว่าคำสั่งทุกชนิดข้าม approval ได้ และไม่ยกเลิกผล denial ของ write probes

ยังไม่เปลี่ยน R06 หรือเปิด live tool execution ใน ModelMate
ทางเลือกที่ต้องให้ผู้ใช้ตัดสินคือรักษา ask-every-command แล้วพัฒนาขอบเขต
execution ที่บังคับได้จริง หรือปรับ requirement ให้ sandbox อนุญาตงานอ่านบางอย่าง
โดยอัตโนมัติ การปรับ default ต้องไม่ถูกตีความว่าอนุญาตเขียน/ติดตั้ง/ส่งข้อมูลออก
และยังต้องพิสูจน์ paths ที่เกี่ยวข้องหลังเลือกแนวทาง
