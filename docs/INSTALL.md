# ติดตั้ง ModelMate บน Linux / WSL2

Runtime คือ `modelmate.py` ไฟล์เดียว ใช้ Python standard library ไม่ต้อง
`pip install openai` หรือ API key แต่การคุยจริงต้องมี Codex CLI ที่ล็อกอิน ChatGPT
ดูขั้นตอนบัญชีและข้อจำกัดการใช้งานใน [README](../README.md)

เป้าหมาย Python 3.9+; offline suite รอบนี้ทดสอบบน Python 3.12.0
ตรวจ protocol กับ Codex CLI 0.169.0 รายงาน live มีขอบเขตตาม
[VERIFICATION.md](VERIFICATION.md) การติดตั้งไม่ได้เปลี่ยนสถานะ release gates

## ตรวจ prerequisites

```bash
python3 --version
command -v codex
codex --version
```

`--help`, local inspection และ plan preview ใช้ได้โดยไม่ต้องมี Codex หรือล็อกอิน
การเปิดแชต/doctor ต้องหา `codex` เจอใน PATH ของ Terminal ที่รันจริง
หากไม่พบ โปรแกรมจะบอกให้ตรวจ `command -v codex` ก่อนเชื่อมต่อ

## ติดตั้งคำสั่ง sr

รันจากโฟลเดอร์ ModelMate ที่มีไฟล์ `modelmate.py`:

```bash
install -Dm755 modelmate.py "$HOME/.local/bin/sr"
"$HOME/.local/bin/sr" --help
```

คำสั่งนี้คัดลอก runtime เดียว ไม่ต้อง sudo และไม่ติดตั้ง dependency ให้เงียบ ๆ
หาก `~/.local/bin` อยู่ใน PATH แล้ว เรียก `sr --help` ได้ทันที

หากต้องการผูก alias ใน Bash ให้เพิ่มบรรทัดนี้ใน `~/.bashrc` ครั้งเดียว
คงเครื่องหมายคำพูดไว้เพื่อรองรับ path ที่มีช่องว่าง:

```bash
alias sr='"$HOME/.local/bin/sr"'
```

โหลดใหม่แล้วตรวจว่ากำลังเรียกไฟล์ใด:

```bash
source "$HOME/.bashrc"
type -a sr
sr --help
```

หากต้องการรันจาก checkout โดยตรงแทนการติดตั้ง:

```bash
chmod +x modelmate.py
./modelmate.py --help
```

## เริ่มแบบไม่ใช้โควตา

จาก repo ที่มีไฟล์ตัวอย่าง:

```bash
sr --workflow examples/explain-lists.json --role-model standard=gpt-6.1-sol
sr --sessions
# เพิ่ม --suggest-models ใน plan preview เพื่อดูข้อเสนอ model/effort
```

ตัวอย่าง/เอกสาร/verifier ไม่ถูกฝังใน runtime ที่คัดลอก ให้ระบุ path ของแผนจริง
เมื่อรันจากโปรเจกต์อื่น คำสั่งอ้างอิงโปรเจกต์ตาม cwd ไม่ใช่ที่ตั้งไฟล์ sr
การย้ายหรือตั้งชื่อโฟลเดอร์โปรเจกต์ใหม่ทำให้ canonical project identity เปลี่ยน

## ตรวจการเชื่อมต่อและใช้จริง

```bash
sr --doctor
```

doctor อ่านบัญชี/catalog/quota ไม่ส่ง inference แต่อาจเขียน Codex runtime state
ผล null หมายถึงยังไม่ทราบ ไม่ใช่สิทธิ์เริ่มงานหรือการจองโควตา
เลือก model/effort จากบัญชีจริงก่อนใช้คำสั่งต่อไปนี้ ซึ่งใช้โควตาเมื่อส่งข้อความ:

```bash
sr --live --model gpt-6.1-sol --effort low
```

Explicit workflow ใช้ `--execute-workflow` และ START ก่อนเปิด session
จากนั้น `/next` จึงเริ่ม model turn; โปรดอ่านขั้นตอนใน [คู่มือใช้งาน](USAGE.md#explicit-plan-cli-experimental-manual-steps)
Verifier ต้องรันจาก checkout และต้องมี `--run-live` จึงใช้โควตา

## อัปเดต

อัปเดต source ที่ตรวจแล้ว จากโฟลเดอร์ repo ใช้คำสั่งเดิม:

```bash
install -Dm755 modelmate.py "$HOME/.local/bin/sr"
sha256sum modelmate.py "$HOME/.local/bin/sr"
```

Hashes ต้องตรงกัน เพื่อไม่ทดสอบ installed runtime คนละรุ่นกับ checkout
การคัดลอก runtime ไม่ย้ายหรือลบ session data รุ่นที่อ่าน schema ไม่ได้จะปฏิเสธ
แทนการแปลงไฟล์โดยเดา ใช้ source/runtime ที่รองรับข้อมูลรุ่นนั้น

## ถอนติดตั้งและข้อมูลที่ยังอยู่

```bash
rm -- "$HOME/.local/bin/sr"
```

นำ alias sr ที่เพิ่มไว้ออกจาก `~/.bashrc` แล้วเปิด Terminal ใหม่
ข้อมูล ModelMate ยังอยู่ใต้ `${XDG_STATE_HOME:-$HOME/.local/state}/modelmate`
แยกตาม canonical project; Codex native history เป็นข้อมูลอีกส่วนหนึ่ง
การถอน binary ไม่ลบ metadata, Codex login หรือ native threads
การลบ session/thread ใช้ flow ที่แสดงขอบเขตและยืนยันต่างหาก
โดยเฉพาะ scratch ของ durable resume probe ที่ตั้งใจเก็บไว้ตรวจย้อนหลัง

## ผลทดสอบการติดตั้ง

`tests/test_standalone.py` คัดลอกเฉพาะ runtime เป็น executable ชื่อ sr ไปยัง
path ที่มีภาษาไทย/ช่องว่าง และรันจากโปรเจกต์ scratch ที่ไม่มี repo imports
ใช้ PATH ที่มี Python แต่ไม่มี Codex ตรวจ help/offline preview/alias quoting
และข้อความ missing-Codex ของ doctor, manual live และ workflow entry points
ไม่เรียกโมเดลและไม่แก้ `.bashrc` หรือ binary ที่ติดตั้งจริงของผู้ใช้

ตรวจติดตั้งแบบแยกจาก checkout บน WSL2 ด้วย system Python 3.11.2
โดยวาง `sr` ใน path ภาษาไทยที่มีช่องว่างและเรียกจากโปรเจกต์ว่าง
ไฟล์ที่ติดตั้งตรงกับต้นฉบับทุกไบต์ เปิด help, plan preview และ session listing
ได้โดยไม่สร้าง state และ doctor แสดงวิธีแก้เมื่อไม่มี Codex ใน PATH
รอบนี้เพิ่มหลักฐานสำหรับ Python อีกเวอร์ชันบน WSL2 เดิม
