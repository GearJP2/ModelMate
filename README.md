<div align="center">

# ModelMate

**เลือกโมเดลให้เหมาะกับงาน ทำงานต่อใน Terminal และตรวจผลก่อนจบ**

เครื่องมือ CLI สำหรับจัดการโมเดล ระดับการคิด และขั้นงานผ่าน ChatGPT/Codex subscription

![Status: Experimental](https://img.shields.io/badge/status-experimental-orange)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform: Linux / WSL2](https://img.shields.io/badge/platform-Linux%20%2F%20WSL2-lightgrey)
![Python dependencies: stdlib only](https://img.shields.io/badge/python_dependencies-stdlib_only-green)

[เริ่มใช้งาน](#quick-start) · [ตัวอย่าง Workflow](#workflow-example) · [คู่มือ](docs/USAGE.md) · [Roadmap](docs/MASTER_PLAN.md) · [แจ้งปัญหา](https://github.com/GearJP2/ModelMate/issues)

</div>

> **Experimental:** ใช้แชตแบบเลือกโมเดลเองและ workflow ที่กำหนดแผนได้แล้ว
> การเลือกโมเดลอัตโนมัติจาก prompt และ agent ที่ทำงานครบวงจรยังไม่เปิดใช้งาน
> ผลทดสอบสดยืนยันเฉพาะเส้นทางที่ระบุใน [Verification](docs/VERIFICATION.md)

## Why ModelMate?

งานเดียวอาจต้องใช้โมเดลต่างกันในแต่ละช่วง เช่น วางแผนด้วยตัวเก่ง ลงมือด้วยตัวทั่วไป
แล้วตรวจเฉพาะจุดที่ซับซ้อน ModelMate ตั้งใจทำให้กระบวนการนี้จัดการได้จาก Terminal
พร้อมแผน เกณฑ์ตรวจ และประวัติการทำงานที่ย้อนดูได้

เป้าหมายคือใช้โมเดลและระดับการคิดเท่าที่งานต้องการ คุณภาพและการประหยัดโควตา
ยังต้องประเมินกับงานจริง จึงยังไม่มีตัวเลข benchmark รับรอง

## Features & status

| ความสามารถ | สถานะปัจจุบัน |
| --- | --- |
| แชตต่อเนื่อง เลือก model / effort | ใช้ได้แบบทดลอง; มีผลทดสอบสดเฉพาะเส้นทาง |
| บันทึก session แยกโปรเจกต์และกลับมาคุยต่อ | มี autosave และผลทดสอบสด reconnect / recall / delete ของ manual chat |
| Workflow จากแผน JSON และ role bindings | ใช้ได้แบบทดลอง; สั่งแต่ละขั้นด้วย `/next` |
| ตรวจงานจาก manual checks หรือผล native test / lint | มีผลทดสอบสดเส้นทางสังเคราะห์; ไม่รับคำกล่าวของโมเดลแทนผลเครื่องมือ |
| จำกัดการแก้ไข | เริ่มหนึ่งครั้ง + แก้ไม่เกินสองรอบต่อขั้น ก่อนให้เลือกว่าจะทำต่ออย่างไร |
| Tool recheck หลัง resume | ต้องเปิด experimental opt-in และยืนยันแยกก่อนใช้โควตาเพิ่ม |
| Recovery ของ recheck ที่มี native IDs ครบ | มีผลทดสอบสดการอ่าน terminal status; หลักฐานเดิมยังเป็นประวัติ |
| สามโหมด `auto` / `ask_to_escalate` / `approve_plan` | มี policy สำหรับ explicit workflow; ทุกโหมดยังต้องสั่ง `/next` |
| ตัวช่วยเลือกโมเดลรายขั้น | `--suggest-models` เสนอ role และ effort จาก risk และ checks ในแผน; ยังรอผลเปรียบเทียบงานจริง |
| ค้นแหล่งอ้างอิงพร้อมยืนยันคำค้น | `--search-wikipedia en\|th` รองรับ Wikipedia แบบแยกจากแชต มีผลทดสอบออฟไลน์ |

รายละเอียดสถานะอยู่ใน [Master plan](docs/MASTER_PLAN.md) และ [Release checklist](docs/RELEASE_CHECKLIST.md)

<a id="quick-start"></a>
## Quick start

### 1. เตรียมเครื่อง

- Linux / WSL2 พร้อม **Python 3.9+**
- **Codex CLI** อยู่ใน `PATH` และล็อกอินด้วยบัญชี ChatGPT
- บัญชีมีสิทธิ์ใช้โมเดลและโควตาที่ต้องการ

Runtime ใช้ Python standard library ไม่ต้องติดตั้ง Python dependencies หรือเซ็ต
`OPENAI_API_KEY` ตรวจ protocol กับ Codex CLI **0.169.0**; รุ่นอื่นยังต้องตรวจ compatibility

```bash
git clone https://github.com/GearJP2/ModelMate.git
cd ModelMate
python3 --version
codex --version
```

หากยังไม่ได้ล็อกอิน ให้รัน `codex login` แล้วเลือกการเข้าสู่ระบบด้วย ChatGPT

### 2. ตรวจการเชื่อมต่อ

```bash
python3 modelmate.py --doctor
```

อ่านบัญชี รายชื่อโมเดล ระดับ effort และ quota โดยไม่ส่ง inference
ค่า `null` หมายถึงยังไม่ทราบ; การอ่านสำเร็จไม่ได้จองโควตาหรือรับประกันค่าใช้จ่าย
Codex อาจเขียน runtime state ตามปกติระหว่างเชื่อมต่อ

### 3. เริ่มคุย

เลือก model ID และ effort ที่ปรากฏในผล doctor ตัวอย่าง:

```bash
python3 modelmate.py --live --model gpt-6.1-sol --effort low
```

หรือส่งโจทย์แรกพร้อมคำสั่ง:

```bash
python3 modelmate.py --live --model gpt-6.1-sol --effort low "อธิบาย Python list แบบสั้น ๆ"
```

**`--live` ใช้โควตา subscription จริงเมื่อส่งข้อความ** โปรแกรมตรวจบัญชี/catalog/quota
ก่อนเริ่ม turn ใหม่ หากข้อมูลไม่ชัดเจนหรือโควตาหมดจะหยุด ไม่มี API-key fallback
ไม่ซื้อเครดิตหรือเปลี่ยน auto-reload; preflight ไม่ใช่ hard spending cap ของบริการ

เมื่อไม่ใส่ `--live` จะเปิด shell ออฟไลน์ ไม่เรียกโมเดล

### ติดตั้งเป็นคำสั่ง `sr`

```bash
install -Dm755 modelmate.py "$HOME/.local/bin/sr"
```

เมื่อ `~/.local/bin` อยู่ใน `PATH` แล้ว:

```bash
sr --help
sr --live --model gpt-6.1-sol --effort low
```

ดูวิธีตั้ง PATH / alias, อัปเดต และถอนติดตั้งใน [Installation guide](docs/INSTALL.md)
Runtime ติดตั้งเป็นไฟล์เดียว; ตัวอย่างและ verifier ใช้จาก checkout แยกต่างหาก

<a id="workflow-example"></a>
## Workflow example

ทดลองดูแผนแบบออฟไลน์ก่อน โดยยังไม่เปิด backend หรือใช้โควตา:

```bash
python3 modelmate.py \
  --workflow examples/explain-lists.json \
  --role-model standard=gpt-6.1-sol
```

เพิ่ม `--execute-workflow` เพื่อเริ่มใช้งานจริง:

```bash
python3 modelmate.py \
  --workflow examples/explain-lists.json \
  --role-model standard=gpt-6.1-sol \
  --execute-workflow
```

ตรวจแผนแล้วพิมพ์ `START` จากนั้นใช้:

```text
/next               ← เริ่มขั้นงานและใช้โควตา
                    ← รอ backend จบ แล้วอ่านตรวจคำตอบ
/verify 1 pass      ← บันทึกว่าคุณตรวจ manual check ข้อ 1 แล้ว
/check              ← ประเมินขั้นงาน
/finish 1=1.1       ← ผูกเกณฑ์ข้อ 1 กับหลักฐานที่ยอมรับจากขั้น 1 check 1
/exit
```

บรรทัดด้านบนอธิบายลำดับการใช้ ให้พิมพ์เฉพาะคำสั่งก่อนเครื่องหมาย `←`
ใช้ `pass` เมื่อได้ตรวจจริงแล้วเท่านั้น งานเสร็จเมื่อสถานะเป็น **DONE**;
การตอบเสร็จของโมเดลหรือการออกจากโปรแกรมไม่เท่ากับผ่านเกณฑ์

ตัวอย่างนี้ใช้ manual check สำหรับ test / lint ต้องผูกคำสั่งและ cwd ผ่าน
`--check-commands` แล้วรับผลจาก native command events ดู [คู่มือ Workflow](docs/USAGE.md#explicit-plan-cli-experimental-manual-steps)

## Sessions & recovery

Session metadata บันทึกอัตโนมัติแยกตาม canonical project directory
ให้รันจากโปรเจกต์เดิมเพื่อดูหรือกลับมาทำต่อ:

```bash
python3 modelmate.py --sessions
python3 modelmate.py --show-workflow SESSION_ID
python3 modelmate.py --live --resume SESSION_ID --model gpt-6.1-sol --effort low
```

แทน `SESSION_ID` ด้วย local ID จากรายการ คำสั่ง `--live --resume` ใช้กับ manual chat;
workflow ใช้ `--resume-workflow` และตรวจหลักฐานใหม่ตาม [คู่มือ](docs/USAGE.md)

Recovery ของ recheck ที่บันทึก native thread/turn ID ครบ:

```bash
python3 modelmate.py --recover-recheck SESSION_ID
```

ไม่เริ่ม model turn ใหม่ หากยัง active จะถาม `STOP` / `PAUSE` ก่อนดำเนินการ
สถานะที่จบแล้วเป็นประวัติ ไม่ทำให้ผลตรวจเก่ากลายเป็นหลักฐานปัจจุบัน
ใช้ `python3 modelmate.py --delete-session SESSION_ID` จากโปรเจกต์เดิมเพื่อดูขอบเขต
work thread, recheck threads และ descendants แล้วพิมพ์รหัสยืนยันที่แสดง
คำสั่งนี้ไม่เริ่ม model turn; เส้นทางลบ recheck ผ่านการทดสอบจำลองแล้ว
ดู [Native recheck contract](docs/NATIVE_RECHECK.md)

## Permissions & data

- ใช้ native Codex **read-only + on-request**: คำสั่งที่ sandbox อนุญาตอาจรันได้เอง
- Manual chat แสดง command / cwd หรือ patch preview ก่อนอนุมัติคำขอขยายสิทธิ์ที่รองรับ
- Workflow รุ่นทดลองปฏิเสธ/พักเมื่อพบคำขอขยายสิทธิ์ ไม่ยกระดับ workspace/full access เอง
- ไม่ replay งานให้อัตโนมัติเมื่อ timeout หรือ reconnect แล้วผลยังไม่ทราบ
- เส้นทาง live ปิด hosted web search, apps/plugins และ agents แต่ไม่อ้าง universal no-tools isolation
- Metadata ในเครื่องและ Codex native history เป็นข้อมูลคนละส่วน การถอน runtime ไม่ลบข้อมูลเหล่านี้

รายละเอียดขอบเขตสิทธิ์อยู่ใน [Permissions](docs/PERMISSIONS.md)

## Development

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile modelmate.py doctor.py verify.py probe_policy.py
git diff --check
```

ชุดทดสอบเริ่มต้นใช้ fake transport / controller ไม่ใช้โควตา model
ผลล่าสุดที่บันทึก: **469 tests ผ่าน** ดูขอบเขตและ source versions ใน
[Verification](docs/VERIFICATION.md) Live probes เป็น opt-in และอาจใช้โควตา
จึงควรเลือกเฉพาะเส้นทางที่ต้องตรวจ ไม่รันซ้ำทุกครั้งที่แก้เอกสาร

```text
modelmate.py      Single-file CLI runtime
examples/         ตัวอย่างแผนและ command bindings
tests/            Offline tests
doctor.py         ตัวเรียก diagnostics
verify.py         Verification harness
probe_policy.py   Standalone native-policy diagnostic
docs/             คู่มือ สถาปัตยกรรม แผนงาน และหลักฐาน
```

## Documentation

| เอกสาร | เนื้อหา |
| --- | --- |
| [Installation](docs/INSTALL.md) | ติดตั้ง `sr`, alias, อัปเดตและถอนติดตั้ง |
| [Usage](docs/USAGE.md) | คำสั่ง chat / workflow, checks, resume และ diagnostics |
| [Design](docs/DESIGN.md) | พฤติกรรมและสถาปัตยกรรมที่ตกลงไว้ |
| [Roadmap](docs/MASTER_PLAN.md) | สถานะ P00–P16 และงานที่ยังเหลือ |
| [Permissions](docs/PERMISSIONS.md) | นโยบายสิทธิ์และขอบเขตที่ตรวจแล้ว |
| [Native rechecks](docs/NATIVE_RECHECK.md) | Recheck ledger, consent และ recovery |
| [Verification](docs/VERIFICATION.md) | ผล offline / live พร้อมเวอร์ชันและข้อจำกัด |

## Contributing

ยินดีรับ [bug reports และข้อเสนอ](https://github.com/GearJP2/ModelMate/issues)
แนบขั้นตอนทำซ้ำ เวอร์ชัน Python/Codex และผลที่คาดหวัง โดยตัดข้อมูลบัญชี
credentials, prompts ส่วนตัว และ raw session logs ออกก่อนส่ง

ก่อนแก้โค้ดให้อ่าน [AGENTS.md](AGENTS.md) และใบงานใน Master plan
ทดสอบ offline ก่อน; การทดสอบสดและการเปลี่ยนนโยบายสิทธิ์ต้องมีขอบเขตชัดเจน
