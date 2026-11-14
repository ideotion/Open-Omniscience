<!-- ar: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# البدء السريع — تشغيل التطبيق

هذا هو **الجوهر الموثوق** (التطبيق في مرحلة **ألفا** بصراحة — `v0.5.0`، دورة
`0.5` المسمّاة «مكتب المحقّق»، الموسومة في 2026-10-26؛ ويعرض التطبيق أثناء تشغيله
رقم إصداره الدقيق): أضِف مصدرًا ← اجمعه بطريقة أخلاقية ← خزّنه مع بيانات منشئه ←
ابحث في النص الكامل ببحث منطقي (Boolean) ← صدِّر. محلي أولًا، عبر الواجهة المحلية (loopback) فقط، بلا حسابات.

---

## 0. الطريقة السهلة — أمر واحد، ثم نقرة مزدوجة للتشغيل

إن كنت تريد استخدام التطبيق فحسب (دون الحاجة إلى أي معرفة بسطر الأوامر بعد ذلك):

**Linux / macOS** — في نافذة طرفية:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — في PowerShell. نزّله، *ثم* شغّله:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

قد يعزل Windows Defender الملف رغم ذلك — فهو غير موقَّع وجديد. هذا إنذار
كاذب؛ ويشرح [§C](#c-على-windows-11-powershell) السبب بالضبط، ويقدّم لك
مسارًا بلا سكربت لا يمكن لأي شيء أن يلتهمه.

دعم Windows أضيق من دعم Linux، والفرق مذكور بوضوح في
[§C](#c-على-windows-11-powershell) — اقرأه قبل الاعتماد عليه.

> **افحص قبل أن تثق.** تمرير سكربت إلى الصدفة (shell) يشغّل شيفرة على
> جهازك. كلا السكربتين صغيران عمدًا — اقرأهما أولًا إن شئت
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh)، [install.ps1](../install.ps1)).
> فهما يتحققان من وجود git و Python 3.13، ويستنسخان هذا المستودع إلى `~/open-omniscience`
> (`%USERPROFILE%\Open-Omniscience` على Windows)، ثم يسلّمان المهمة إلى
> المثبِّت الموجود داخل المستودع. ويمكنك بالقدر نفسه أن تستنسخه بنفسك وتشغّل `./install.sh` / `install.ps1`.

`install.sh` **لا يطرح أسئلة** — **لا توجد قائمة مكوّنات**. أمر واحد يثبّت
المجموعة الافتراضية المعقولة:

| ما يُثبَّت افتراضيًا | ما تحصل عليه |
|----------------------|--------------|
| **النواة (Core)** *(دائمًا)* | الجمع · التخزين مع بيانات المنشأ · البحث المنطقي · التصدير |
| **التحليل (Analysis)** | الكلمات المفتاحية · مقارنة التأطير · المشاعر |
| **الضغط (Compression)** | تخزين أسرع للمجموعة النصية على القرص |

إعداد النموذج اللغوي المحلي / Ollama **ليس** جزءًا من المثبِّت — فهو موجود بالكامل في
تبويب **الإعدادات ← ذكاء اصطناعي** في التطبيق (انظر §E). يمكنك تغيير المجموعة المثبَّتة بمتغير البيئة
`OO_COMPONENTS="…"` (مثلًا `OO_COMPONENTS="analysis,nlp"`)؛ وإعادة تشغيل
`./install.sh` آمنة التكرار (idempotent) ولا تثبّت إلا ما هو ناقص.

**ثم يُشغَّل تلقائيًا.** ينشئ المثبِّت مُشغِّلًا باسم **Open Omniscience** (في قائمة
التطبيقات + سطح المكتب) ويفتح التطبيق في متصفحك. لتشغيله مرة أخرى لاحقًا:

- افتح قائمة التطبيقات وابحث عن **Open Omniscience**، **أو**
- انقر نقرًا مزدوجًا على أيقونة **Open Omniscience** على **سطح المكتب**.

تظهر نافذة طرفية صغيرة، ويبدأ التطبيق، ويفتح متصفحك على
**http://127.0.0.1:8000**. **أغلق تلك النافذة (أو استخدم زر الطاقة / الإيقاف في الشريط
العلوي) لإيقاف التطبيق.** (على macOS يكون المُشغِّل هو `Open Omniscience.command` على
سطح المكتب؛ وعلى Windows هو اختصار على سطح المكتب وفي قائمة ابدأ ينشئه `install.ps1`.)

**التشغيل الأول.** في التثبيت الجديد يرشدك التطبيق عبر إعداد قصير لمرة واحدة
*قبل* الواجهة الرئيسية: **اختر لغتك ← اقرأ الشروط القانونية واقبلها**
(الرفض **يزيل تثبيت** التطبيق، بعد تأكيد مكتوب) **← أنشئ عبارة مرور
مجموعتك النصية**. المجموعة النصية **مشفّرة أثناء التخزين افتراضيًا** (SQLCipher 4) و**لا
توجد أي وسيلة استرداد** لعبارة مرور مفقودة (فقدان عبارة المرور يكلّفك وقت إعادة الجمع — إذ
تُعاد بناء المجموعة من الويب). ثم يبدأ التطبيق **دون اتصال (وضع الطيران)**؛
والانتقال إلى الاتصال يمرّ عبر **نافذة موافقة واحدة** تسمّي الإجراء وتعرض عناوين IP
لواجهاتك المحلية قبل أن يخرج أي طلب.

تفضّل الطرفية؟ الأمر `cd ~/open-omniscience && ./scripts/launch.sh` يفعل الشيء نفسه.

**للتحقق منه أو إزالته لاحقًا:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. على آلة تطبيقات (AppVM) بنظام Debian في Qubes OS (البيئة المستهدفة)

يعيد Qubes ضبط نظام الملفات الجذري لآلة AppVM عند كل إقلاع؛ ولا يبقى إلا `/home` (و
`/usr/local` و `/rw`). لذلك توضع حزم النظام في **آلة القالب (TemplateVM)**، ويقيم
التطبيق + البيئة الافتراضية + قاعدة البيانات تحت `/home` في **آلة AppVM**.

**1. في آلة TemplateVM (مرة واحدة):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
أوقف تشغيل آلة TemplateVM، ثم **أعد تشغيل آلة AppVM** حتى تصبح الحزم مرئية.

**2. في آلة AppVM (بحساب المستخدم الخاص بك، دون sudo):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. شغّله (يرتبط بالعنوان 127.0.0.1 فقط):**
انقر نقرًا مزدوجًا على مُشغِّل **Open Omniscience** (قائمة التطبيقات / سطح المكتب)، أو:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
افتح **http://127.0.0.1:8000** في متصفح آلة AppVM.

لا يستمع الخادم أبدًا خارج الواجهة المحلية (loopback). وللانتقال إلى وضع عدم الاتصال الكامل بعد التشغيل، افصل
آلة الشبكة (NetVM) عن آلة AppVM — فالواجهة لا تعتمد على أي شيء خارجي وتواصل العمل على البيانات المخزّنة.

---

## B. تشغيل تطويري محلي (أي توزيعة Linux مع Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

متغيرات بيئة مفيدة: `OO_DATA_DIR` (مكان قاعدة بيانات SQLite + البيانات)، `OO_HOST`/`OO_PORT`،
`OO_FETCH_MIN_INTERVAL` (مهلة اللباقة لكل مضيف، بالثواني).

### على Tails

توزيعات Debian/Ubuntu/Tails تشحن `venv`/`ensurepip` من المكتبة القياسية في **حزمة apt منفصلة**، لذا
يفشل `python3 -m venv` إلى أن تُثبَّت. والآن يثبّتها `install.sh`
**تلقائيًا** — وعلى Tails يتطلب ذلك **كلمة مرور الإدارة** (اضبطها في
شاشة الترحيب؛ وهي معطّلة افتراضيًا) و**اتصال Tor** عاملًا (إذ يُنزِّل apt عبر
Tor). يمكنك إلغاء ذلك بـ `OO_NO_APT=1` إن كنت تفضّل تشغيل apt بنفسك.

تحذيران صريحان خاصّان بـ Tails:

- **إصدار Python.** يقوم Tails على Debian 12 ← **Python 3.11**، لكن التطبيق يستهدف **3.13**.
  يجب أن يتوفر لديك مفسِّر 3.13 وأن توجّه المثبِّت إليه
  (`OO_PYTHON=python3.13 ./install.sh`)؛ والإصدار 3.13 وحزمته `python3.13-venv` **ليسا**
  في المستودعات الافتراضية لـ Tails.
- **فقدان الذاكرة (Amnesia).** كل ما يُثبَّت عبر apt — وكامل `.venv` — **يضيع عند إعادة التشغيل** ما لم
  يكن على التخزين الدائم: أضِف حزمة venv عبر **التخزين الدائم ← البرمجيات
  الإضافية (Persistent Storage → Additional Software)**، واحتفظ بنسخة المستودع + `OO_DATA_DIR` على وحدة التخزين الدائمة.

### ترقية قاعدة بيانات موجودة

التثبيتات الجديدة تبني المخطط تلقائيًا (`init_db()`)، وتُوسَم قاعدة البيانات
بخط الأساس الحالي للترحيلات. وعندما يغيّر إصدار مستقبلي
المخطط، رقِّ قاعدة البيانات الموجودة بالأمر:
```bash
alembic upgrade head
```
يُبلغ `alembic check` عمّا إذا كانت النماذج والترحيلات متوافقة (ويحرس التكامل المستمر CI ذلك).

---

## C. على Windows 11 (PowerShell)

**حالة الدعم بصراحة — اقرأ هذا أولًا.** كل تشغيل للتكامل المستمر (CI) يثبت ثلاثة أشياء على
`windows-latest`: تثبيت الاعتماديات، و**فحص الإقلاع** (يُستورد التطبيق بأكمله)،
و**تشفير SQLCipher أثناء التخزين** — وهذا الأخير على مسار *حاجب* (blocking)، فالتشفير
ليس تخمينًا. لا شيء يتجاوز ذلك مُثبَت. **مسار pytest على Windows
يتعطّل** (بقيت التشغيلات المكتملة الأخيرة في `pytest` مدة 3h21m وقرابة 6h، مقابل 18 دقيقة
على macOS)، و**لم يتصفّح أحدٌ الواجهة بالنقر على Windows**. لذا: توقّع أن يعمل التثبيت
والتشغيل، واعتبر كل ما بعد الإقلاع غير مُتحقَّق منه، ونرجو أن تبلغ عمّا
يتعطّل. يبقى Linux هو بوابة الإصدار.

### 1. التثبيت

افتح **PowerShell** (لا حاجة إلى صلاحيات المسؤول ما لم يلزم تثبيت Python نفسه).
نزّل المثبِّت، واقرأه إن شئت، ثم شغّله:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

يثبّت Git و Python 3.13 عبر `winget` فقط إن كانا مفقودين، ويستنسخ إلى
`%USERPROFILE%\Open-Omniscience`، ويبني `.venv`، ويتحقق من النتيجة عبر
استيراد التطبيق الفعلي. احذف الخيار `-Extras` للحصول على المجموعة الافتراضية الأوسع، أو انظر
[خيارات المثبِّت](#خيارات-المثبت).

استنسخته مسبقًا؟ شغّله في مكانه — فهو يكتشف نسخته المستنسخة ويتخطّى الاستنساخ:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **لماذا لا يكون سطرًا واحدًا `irm … | iex`؟** لأن جلب شيفرة بعيدة وتنفيذها
> مباشرة من الذاكرة هو أشيع طريقة لتوصيل برمجيات Windows الخبيثة، لذا
> يقيّم Defender هذا الشكل على أنه عدائي أيًّا كان محتوى السكربت. وكتابة الملف
> على القرص أولًا أقل عرضة للحجب وأكثر صدقًا معًا — إذ يمكنك قراءة الملف
> قبل أن يعمل.

### 2. إذا عزل Windows Defender المثبِّت

قد يحذف `install.ps1` فور رؤيته. هذا **إنذار كاذب**، ولا ينبغي أن
تكتفي بكلامنا — وإليك بدقة سبب حدوثه، لتحكم بنفسك:

- الملف **غير موقَّع وجديد**، لذا لم تره سمعة Defender السحابية قطّ.
  والجمع بين «مجهول» و«غير موقَّع» كافٍ وحده لإطلاق استدلالات التعلّم الآلي؛ وعادةً
  ينتهي اسم الاكتشاف بـ `!ml`.
- **شكله** شكل مثبِّت: يستدعي مدير حزم، ويعيد قراءة `PATH` من
  السجل (registry)، ويكتب اختصارات قائمة ابدأ، ومساره `-Uninstall` يحذف
  مجلدات. والبرمجيات الناقلة (droppers) تفعل الأشياء نفسها. والمصنِّف يقيّم الشكل لا النية.

ما *لا* يحتويه، وما يمكنك التحقق منه بنفسك في نحو 500 سطر مقروء: لا
`Invoke-Expression`، ولا حمولة مرمَّزة أو مموَّهة، ولا `WebClient`، ولا نوافذ
مخفية، ولا تنزيل من أي مكان سوى هذا المستودع.

ثلاث طرق للمضي قدمًا، الأفضل أولًا:

1. **استخدم المسار الخالي من السكربت** — [التثبيت اليدوي](#التثبيت-اليدوي-بلا-سكربت) أدناه.
   الأوامر نفسها التي يشغّلها المثبِّت، دون ملف يمكن عزله. هذا ينجح دائمًا.
2. **أبلغ عن الإنذار الكاذب** إلى Microsoft على
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (اختر *Software developer*).
   يُعالَج عادةً خلال يوم أو يومين ويصلح المشكلة لكل من يثبّت
   بعدك — لا لك وحدك.
3. **استثنِ المجلد** (أمان Windows ← الحماية من الفيروسات والتهديدات ← إدارة
   الإعدادات ← الاستثناءات). اعرف المقايضة قبل أن تفعل ذلك: الاستثناء يوقف
   فحص Defender لذلك المجلد *بالكامل*، لكل شيء، وإلى أجل غير مسمّى — لا
   لهذا الملف وحده. جهازك، وقرارك؛ ولن نتظاهر بأن ذلك بلا ثمن.

الإصلاح الصادق من جهتنا هو توقيع الشيفرة، وهو ما لا نملكه بعد.

### 3. التشغيل

ينشئ المثبِّت اختصارًا باسم **Open Omniscience** على **سطح المكتب** وفي
**قائمة ابدأ**. انقر عليه نقرًا مزدوجًا: تظهر نافذة طرفية، ويُفتح متصفحك على
**http://127.0.0.1:8000** بمجرد أن يستجيب التطبيق فعلًا. أغلق تلك النافذة (أو استخدم
زر الطاقة في التطبيق) لإيقافه.

أو من طرفية بدلًا من ذلك: `scripts\launch.cmd`.

### 4. التشغيل الأول

التدفق نفسه لمرة واحدة كما في كل المنصات: **اختر لغتك ← اقرأ الشروط
القانونية واقبلها ← أنشئ عبارة مرور مجموعتك النصية**. المجموعة النصية **مشفّرة أثناء التخزين
افتراضيًا** و**لا توجد أي وسيلة استرداد** لعبارة مرور مفقودة. ثم يبدأ التطبيق
**دون اتصال (وضع الطيران)**؛ والانتقال إلى الاتصال يمرّ عبر **نافذة موافقة واحدة**.

### خيارات المثبِّت

| الخيار | ما يفعله |
|------|--------------|
| *(لا شيء)* | النواة + `analysis,compression,columnar`، ثم التحقق وإنشاء المُشغِّلات |
| `-Path <dir>` | التثبيت في مكان آخر غير `%USERPROFILE%\Open-Omniscience` |
| `-Extras "analysis"` | اختيار الإضافات (extras) لـ pip (`""` للنواة فقط) |
| `-Ref <branch>` | استنساخ فرع أو وسم محدد |
| `-NoPython` | عدم تثبيت Git/Python تلقائيًا أبدًا؛ والفشل مع تعليمات بدلًا من ذلك |
| `-NoLauncher` | تخطّي اختصارات سطح المكتب / قائمة ابدأ |
| `-Check` | تقرير الحالة (مثل `open-omniscience doctor`) |
| `-Uninstall` | إزالة `.venv` + المُشغِّلات؛ وتُحفظ البيانات ما لم يُؤكَّد حذفها بشكل منفصل |
| `-Yes` | افتراض «نعم» عند الأسئلة (دون تدخّل) |

لا يُثبت التكامل المستمر (CI) على Windows إلا `analysis`. وإذا فشل تثبيت المجموعة
الافتراضية الأوسع، **يرجع السكربت إلى `analysis` ويقول ذلك** بدلًا من الفشل
بصمت أو التظاهر بأن الإضافات وصلت.

### التثبيت اليدوي (بلا سكربت)

```powershell
# 1. Prerequisites -- skip either line if you already have it
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.13 -e --source winget --scope user

# 2. Find the interpreter. winget frequently installs Python WITHOUT adding it to
#    PATH, so `python` and `py` can still resolve to nothing on a freshly restarted
#    machine. This reads the record the installer itself writes (PEP 514) -- the same
#    one py.exe uses -- so it answers whatever PATH says:
Get-ChildItem 'HKCU:\SOFTWARE\Python','HKLM:\SOFTWARE\Python' -Recurse -ErrorAction SilentlyContinue |
  Where-Object PSChildName -eq 'InstallPath' |
  ForEach-Object { (Get-ItemProperty $_.PSPath).'(default)' }

$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"   # or whatever that printed

# 3. Clone
git clone --depth 1 https://github.com/ideotion/Open-Omniscience.git $HOME\Open-Omniscience
cd $HOME\Open-Omniscience

# 4. Virtual environment. Everything is called by full path on purpose: activating a
#    venv needs Activate.ps1, which the default execution policy blocks.
& $py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[analysis]"

# 5. Verify -- the exact check CI's Windows lane runs
.\.venv\Scripts\python.exe -c "from src.api.main import app; print(sum(1 for _ in app.routes))"

# 6. Run
.\.venv\Scripts\open-omniscience.exe
```

### ملاحظات خاصة بـ Windows

- **سياسة التنفيذ.** تحجب السياسة الافتراضية `.\.venv\Scripts\Activate.ps1`.
  لا شيء هنا يحتاج إليه: استدعِ `.venv\Scripts\python.exe` بمساره وتختفي المشكلة
  كلها. ويغطّي `-ExecutionPolicy Bypass` في سطر الأوامر المثبِّتَ نفسه.
- **الأمر `python` الذي يفتح متجر Microsoft.** يأتي Windows 11 الجديد بملف
  اسم مستعار للتنفيذ (execution-alias) باسم `python.exe` يفتح المتجر بدلًا من تشغيل
  الشيفرة. يتجاهله المثبِّت (فهذا الملف البديل لا يطبع أي إصدار) ويستخدم المُشغِّل `py -3.13`.
  وإن ثبّتَّ يدويًا، ففضّل `py -3.13` على `python`.
- **أين تقيم بياناتك.** لأن هذه نسخة مستنسخة من الشيفرة المصدرية، فإن المجموعة النصية ومفاتيح
  التوقيع والإعدادات تُوضع في **`<repo>\data`** — لا في `%APPDATA%`. اضبط `OO_DATA_DIR` لوضعها
  على محرك أقراص آخر.
- **أذونات المجلد.** على Linux يُقفَل دليل البيانات على مستخدمك
  (`chmod 0700`)؛ وهذا الاستدعاء لا يفعل شيئًا على Windows، لذا يرث المجلد قوائم التحكم
  بالوصول (ACL) العادية في Windows. على حاسوب مشترك، قيّد الوصول إلى `<repo>\data` بنفسك. أما قاعدة
  بيانات المجموعة النصية نفسها فتبقى مشفّرة أثناء التخزين في الحالتين.
- **SmartScreen / Defender.** لا شيء هنا موقَّع رقميًا، لذا يعامل Windows كل ذلك
  على أنه مجهول: قد يحذّر SmartScreen من المُشغِّل، وقد يعزل Defender
  `install.ps1` مباشرةً — انظر
  [§2](#2-إذا-عزل-windows-defender-المثبت) لمعرفة ماهية ذلك وما
  ينبغي فعله حياله. كما يبطئ الفحص في الوقت الحقيقي أول `pip install` بشكل ملحوظ.
- **المنفذ.** اضبط `OO_PORT` قبل التشغيل للابتعاد عن 8000؛ ويحترمه `scripts\launch.cmd`.
- **البنية (x64 / ARM64 / 32-bit).** يكتشفها المثبِّت ويتعامل معها؛ وإليك
  ما يقرّره. ما يحكم نجاح `pip install` ليس الجهاز
  بل حزم العجلات (wheels) المتوفرة لمنصة *المفسِّر*. قِيس ذلك مقابل
  PyPI في 2026-08-23، لـ CPython 3.13، عبر كامل مجموعة اعتماديات هذا المشروع:

  | المفسِّر | حزم العجلات |
  |---|---|
  | `win-amd64` | **كل الاعتماديات.** البنية الوحيدة الكاملة. |
  | `win-arm64` | كلها ما عدا ثلاثًا — `cryptography` (النواة)، و`httptools` (النواة، عبر `uvicorn[standard]`) و`statsmodels` (`analysis`) |
  | `win32` | لا تنشر `cryptography` أي حزمة على الإطلاق |

  يشغّل Windows على ARM الملفات التنفيذية x64 بشفافية، لذا فإن **مفسِّر x64 هو الإجابة
  الصحيحة على ARM64 أيضًا** — ليس حلًا وسطًا، بل المجموعة الكاملة. لذلك يفضّل `install.ps1`
  `win-amd64` في كل مكان، وسيحصل على واحد إن لم يكن على الجهاز:
  عبر winget مع تسمية البنية، ثم winget في نطاق المستخدم، ثم نسخة CPython x64
  المستقلة من مؤسسة Python للبرمجيات (Python Software Foundation) من nuget.org — مع التحقق منها مقابل
  بصمة SHA-512 التي يشهد بها nuget، وفكّها في
  `%LOCALAPPDATA%\Open-Omniscience\python-x64`، دون حاجة إلى رفع الصلاحيات، ولا تغيير في PATH
  ولا إدخال في السجل. وهي تقع **خارج** النسخة المستنسخة عمدًا: فهي مورد
  للجهاز، لذا تبقى بعد حذف مجلد التطبيق (وإلا لتعطّلت `.venv` المبنية عليها)
  وتعيد نسخةٌ مستنسخة ثانية عبر `-Path` استخدامها. ويزيلها `-Uninstall`. وعند عدم تطابق
  البصمة، أو مع إصدار لا يشهد له nuget ببصمة، **يرفض**.

  إذا فشلت كل الدرجات، تحصل على توقّف مع حلّ يتطلب تنزيلًا واحدًا، لا على بناء
  Rust يستغرق عشرين دقيقة وينتهي بـ `linker link.exe not found`.

  أما `.venv` الموجودة **فتُفحَص، لا يُكتفى بالعثور عليها**: فهي تحتفظ بإصدار المفسِّر الذي بناها
  ومنصة عجلاته، لذا فإن واحدة خلّفها تشغيل سابق على
  Python مختلف تُستبدَل بدلًا من إعادة استخدامها — وإلا لأُبطِل كل ما سبق
  بصمت في الخطوة الأخيرة. أما المطابقة فيُعاد استخدامها دون مساس. لذا فإن إعادة تشغيل
  المثبِّت هي علاج التثبيت غير المكتمل؛ ولا حاجة إلى حذف أي شيء
  يدويًا.

  - **لماذا لا يُفعَّل التثبيت الأصلي لـ ARM64 تلقائيًا.** فهو يتطلب تثبيت `cryptography`
    على 46.0.0–46.0.3، السلسلة الوحيدة التي لها حزم ARM64. وهذا الإصدار يحمل
    **13 سجل تنبيه أمني مفتوحًا** (منها واحد يخص OpenSSL المربوطة ستاتيكيًا، أُصلح في
    48.0.1). هذا التطبيق يوقّع الأدلة؛ وتثبيت ذلك بصمت سيكون مسرحًا
    أمنيًا. إن كان جهازك يملك فعلًا Visual Studio Build Tools **و**سلسلة أدوات
    Rust، فإن `-AllowSourceBuilds` يترجم الحزم الثلاث أصليًا — خيار صريح،
    لا افتراضي أبدًا.
  - **Windows بنظام 32-bit غير مدعوم**، وهذا حدّ حقيقي لا بوابة مصطنعة:
    `cryptography` لا تشحن أي حزمة `win32`. يلزم Windows بنظام 64-bit.

---

## D. الحلقة الكاملة من البداية إلى النهاية (الواجهة أو واجهة البرمجة API)

> **المصادر مُعدّة مسبقًا.** عند التشغيل الأول (أو أثناء `install.sh --appvm`)
> تُزرع الفهارس المنتقاة (`configs/sources.yml` نحو 3,200 منفذ إعلامي ذي منفعة عامة، إضافةً إلى
> فهارس الأسواق والطيف السياسي والقانون/الملكية الفكرية — **نحو 3,395 نطاقًا فريدًا في
> المجموع**) تلقائيًا — فتستطيع البدء في الاستيعاب فورًا.
> (هذه الأعداد **تنجرف** مع نمو الفهارس؛ والرقم الحي هو ما تحويه
> `configs/*.yml` حاليًا.) إعادة الزرع آمنة التكرار. عطّل الزرع التلقائي بـ
> `OO_AUTOSEED=0`؛ وأعد الزرع يدويًا بـ `python scripts/seed_sources.py` أو
> `POST /api/sources/seed-defaults`. تتغيّر روابط الخلاصات وسياسات robots مع الوقت؛ ويرفض
> الجالب الأخلاقي أي شيء لا يستطيع تأكيده، لذا قلّص القائمة أو وسّعها بما يناسب
> تحقيقك.

**في الواجهة:** **اتصل بالإنترنت** مرة واحدة (مفتاح وضع الطيران ← نافذة موافقة واحدة) و
**يعمل الجمع من تلقاء نفسه** في الخلفية — موزَّعًا على طبقات عبر اللغات ووسوم
المصادر، محترمًا لـ robots ومحدود المعدّل. ثم **ابحث في استكشاف** (التبويب في الشريط الجانبي؛ والضغط على Enter في
الشريط الشامل، الشريط العلوي أو Ctrl/⌘-K، يفتح استكشاف في علامة تبويب جديدة في المتصفح) — يظهر تحليل المقالات المطابقة تحت
النتائج، حيث تصفّي وتقرأ وتشغّل استعلامات منطقية و**تصدّر** (CSV/JSON، وملحق
المنهجية، والأدلة الموقَّعة). وما زال بإمكانك إضافة مصدر و*استيعاب (Ingest)* خلاصة واحدة أو رابط واحد
يدويًا من **الإعدادات ← متقدم ← الجمع / المصادر**.

**عبر واجهة البرمجة (API):**
```bash
# add a source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# ingest its feed (ethical: robots.txt respected fail-closed, rate-limited)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# or ingest a single article URL under that source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# Boolean full-text search (AND / OR / NOT, "phrases", parentheses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# export the filtered set
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

مخطط واجهة البرمجة المقروء آليًا موجود على **http://127.0.0.1:8000/openapi.json**. وصفحة Swagger التفاعلية معطّلة افتراضيًا (لأنها تحمّل موارد من مضيفين خارجيين)؛ ويمكن للمطوّر تشغيل التطبيق مع `OO_API_DOCS=1` للحصول عليها على `/docs`.

---

## E. قدرات التحليل

كلها محلية أولًا وتتراجع بصوت عالٍ (لا تختلق شيئًا أبدًا). المخططات الكاملة على `/openapi.json`.

**النموذج اللغوي المحلي (Ollama).** أعدَّه من **الإعدادات ← ذكاء اصطناعي**: مثبِّت Ollama
داخل التطبيق **مُتحقَّق منه بالمجموع الاختباري (checksum)** (Linux) إضافةً إلى **طابور لتنزيل النماذج** (تقدّم
حقيقي بالبايت، مع الإلغاء)، ومنتقٍ للنموذج النشط، ولوحة لتعديل الموجِّهات (prompts). أو ثبّت
Ollama بنفسك من **ollama.com** ثم `ollama pull llama3.2:3b`. تخرج عمليات سحب النماذج
عبر **الإنترنت المكشوف (clearnet) من خلال عملية Ollama** (لا عبر مسار Tor الخاص بالتطبيق) — ويُفصَح عن ذلك عند
الموافقة. تعرض شارة النموذج اللغوي في الشريط العلوي الحالة الحية (انقرها لفتح الإعدادات ← ذكاء اصطناعي)؛ ولكل
نتيجة بحث زرّا **تلخيص** و**ترجمة**. واجهة البرمجة:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
إذا لم يكن Ollama قيد التشغيل، تُعيد هذه الطلبات HTTP 503 مع رسالة واضحة — لا ملخصًا مزيّفًا.

**أسعار السلع + ارتباط صادق.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
يُعيد الارتباط معاملًا حقيقيًا + قيمة p + n من scipy (Pearson/Spearman)،
مع تحذير «الارتباط ≠ السببية»؛ وإن كان التداخل قليلًا جدًا ← `insufficient_data`.

**المراقبة.** يُجري `POST /api/monitoring/health` فحوص وصول حقيقية
(عبر الجالب الأخلاقي)؛ ويُعلِّم `GET /api/monitoring/anomalies`
القفزات في حجم المقالات وفق درجة z (z-score). **البريد الإلكتروني:** يدمج `POST /api/sources/{id}/ingest-email`
(IMAP) الرسائل في المجموعة النصية نفسها القابلة للبحث.

**التحقق من بيانات الصور الوصفية.** يُعيد `POST /api/verify/image-metadata`
(ارفع صورة) صيغتها وأبعادها وبيانات EXIF و GPS مع ملاحظات واقعية
بسيطة (مثل وجود وسم لبرنامج تحرير، أو غياب طابع زمني للالتقاط). نطاقه محدّد
بصدق على أنه *فحوص للبيانات الوصفية* — **وليس** كشفًا للتزييف العميق أو التلاعب (فذاك كان
مختلَقًا وعُزل خارج شجرة العمل؛ انظر
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**حزم الأدلة الموقَّعة.** زر **تصدير أدلة موقَّعة** في نافذة التحليل
(أو `POST /api/reports/evidence`) يُنتج حزمة ذات جذر Merkle وموقَّعة بـ
Ed25519. ويستطيع أي شخص التحقق منها دون اتصال، ودون هذا التطبيق:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**سلسلة الحيازة.** تتتبّع لوحة **سلسلة الحيازة** في الواجهة بيانات منشأ موقَّعة
تكشف أي عبث، وتتيح لك تبديل سلوكها أثناء التشغيل:
التوقيعات ما بعد الكمّية، ونمط الترسيخ (`local` دون اتصال مقابل **OpenTimestamps**
المرسَّخ في Bitcoin)، والتسجيل التلقائي عند الاستيعاب. المفاتيح هي *تفضيلات* —
تعرض اللوحة الحالة **الفعلية**، فلا يدّعي شيء أنه مفعّل حين لا تكون
إضافته مثبَّتة. واجهة البرمجة:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
النموذج الكامل ونموذج التهديد وتحذيرات الخصوصية: [USER_MANUAL.md](USER_MANUAL.md).

---

## ما الذي يضمنه «الاستيعاب الأخلاقي»

- يُجلب robots.txt ويُخزَّن مؤقتًا لكل مضيف، و**يُغلق عند الفشل (fail-closed)**: إن تعذّر
  تأكيده (خطأ في الشبكة، أو انتهاء المهلة، أو 5xx، أو 401/403 مقيّد)، **لا** يُجلب
  الرابط.
- يُفرض حدّ أدنى للفاصل الزمني لكل مضيف (مع احترام `Crawl-delay`).
- مسار جلب واحد، ووكيل مستخدم (User-Agent) يعرّف بنفسه، و HTML فقط للمقالات — لا تجاوز خام.
- يستخدم الاستخراج trafilatura؛ وإن لم يُعثر على متن مقال حقيقي، لا يُخزَّن شيء
  (لا صفوف مختلَقة من نوع "No Title / No Content").
- كل مقال مخزَّن يحمل بيانات منشئه: المصدر، والرابط الأصلي، والرابط المعياري (canonical)،
  وبصمة المحتوى (المستخدمة لإزالة التكرار)، ووقت الجلب.
