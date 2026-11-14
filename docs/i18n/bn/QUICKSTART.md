<!-- bn: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# দ্রুত শুরু — অ্যাপটি চালানো

এটি হলো **নির্ভরযোগ্য মূল অংশ** (অ্যাপটি একটি সৎ **alpha** — `v0.5.0`,
`0.5` investigator's-desk চক্র, ট্যাগ করা হয়েছে 2026-10-26; চলমান অ্যাপটি তার সঠিক
সংস্করণ নিজেই জানায়): একটি উৎস যোগ করুন → নৈতিকভাবে সেটি সংগ্রহ (scrape) করুন → উৎস-তথ্যসহ (provenance) সংরক্ষণ করুন →
Boolean পূর্ণ-পাঠ্য অনুসন্ধান → রপ্তানি। স্থানীয়-প্রথম, শুধুমাত্র loopback, কোনো অ্যাকাউন্ট নেই।

---

## 0. সহজ উপায় — একটি কমান্ড, তারপর চালাতে ডাবল-ক্লিক

আপনি যদি শুধু অ্যাপটি ব্যবহার করতে চান (পরে কোনো কমান্ড-লাইন জ্ঞানের প্রয়োজন নেই):

**Linux / macOS** — একটি terminal-এ:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — PowerShell-এ। আগে এটি ডাউনলোড করুন, *তারপর* চালান:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

তবুও Windows Defender ফাইলটিকে quarantine করতে পারে — এটি স্বাক্ষরবিহীন (unsigned) এবং নতুন। এটি একটি
ভুল সতর্কসংকেত (false positive); [§C](#c-windows-11-এ-powershell) ঠিক কেন তা ব্যাখ্যা করে, এবং আপনাকে
স্ক্রিপ্ট-ছাড়া এমন একটি পথ দেয় যা কিছুই মুছে ফেলতে পারে না।

Windows-এর সমর্থন Linux-এর চেয়ে সীমিত, এবং পার্থক্যটি স্পষ্টভাবে বলা আছে
[§C](#c-windows-11-এ-powershell)-এ — এর ওপর নির্ভর করার আগে সেটি পড়ে নিন।

> **বিশ্বাস করার আগে যাচাই করুন।** একটি স্ক্রিপ্টকে আপনার shell-এ pipe করলে আপনার
> মেশিনে কোড চলে। দুটিই ইচ্ছাকৃতভাবে ছোট রাখা হয়েছে — চাইলে আগে পড়ে নিন
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1))।
> এগুলো git + Python 3.13 আছে কিনা পরীক্ষা করে, এই repo-টিকে `~/open-omniscience`-এ clone করে
> (Windows-এ `%USERPROFILE%\Open-Omniscience`), এবং repo-র ভেতরের
> installer-এর হাতে কাজ তুলে দেয়। আপনি নিজেও clone করে `./install.sh` / `install.ps1` চালাতে পারেন।

`install.sh` **প্রশ্নহীন (promptless)** — এতে **কোনো উপাদান-মেনু নেই**। একটি কমান্ডেই
যুক্তিসঙ্গত ডিফল্ট সেট ইনস্টল হয়:

| ডিফল্টভাবে ইনস্টল হয় | আপনি যা পান |
|----------------------|--------------|
| **মূল অংশ (Core)** *(সবসময়)* | সংগ্রহ (scrape) · উৎস-তথ্যসহ সংরক্ষণ · Boolean অনুসন্ধান · রপ্তানি |
| **বিশ্লেষণ** | কীওয়ার্ড · উপস্থাপনভঙ্গির (framing) তুলনা · অনুভূতি (sentiment) |
| **সংকোচন (Compression)** | corpus-এর দ্রুততর অন-ডিস্ক সংরক্ষণ |

স্থানীয় LLM / Ollama সেটআপ installer-এর অংশ **নয়** — এটি পুরোপুরি অ্যাপের
**সেটিংস → এআই** ট্যাবে থাকে (§E দেখুন)। ইনস্টল হওয়া সেটটি বদলাতে
`OO_COMPONENTS="…"` env var ব্যবহার করুন (যেমন `OO_COMPONENTS="analysis,nlp"`); `./install.sh`
আবার চালানো idempotent এবং শুধু যা অনুপস্থিত তা-ই ইনস্টল করে।

**এরপর এটি নিজে থেকেই চালু হয়।** installer একটি **Open Omniscience** launcher তৈরি করে (অ্যাপস
মেনু + ডেস্কটপ) এবং আপনার browser-এ অ্যাপটি খোলে। পরে আবার চালু করতে:

- আপনার অ্যাপ্লিকেশন মেনু খুলে **Open Omniscience** খুঁজুন, **অথবা**
- আপনার **ডেস্কটপে (Desktop)** থাকা **Open Omniscience** আইকনে ডাবল-ক্লিক করুন।

একটি ছোট terminal উইন্ডো দেখা দেয়, অ্যাপটি চালু হয়, এবং আপনার browser
**http://127.0.0.1:8000** ঠিকানায় খোলে। **অ্যাপটি বন্ধ করতে সেই উইন্ডোটি বন্ধ করুন (অথবা টপ-বারের পাওয়ার / শাটডাউন
বোতাম ব্যবহার করুন)।** (macOS-এ launcher হলো আপনার ডেস্কটপে থাকা `Open Omniscience.command`;
Windows-এ এটি `install.ps1`-এর তৈরি একটি ডেস্কটপ + Start-মেনু shortcut।)

**প্রথমবার চালু করা।** নতুন ইনস্টলেশনে অ্যাপটি মূল UI-এর *আগে* আপনাকে একটি ছোট, একবারের
সেটআপের মধ্য দিয়ে নিয়ে যায়: **আপনার ভাষা বেছে নিন → আইনি শর্তাবলি পড়ে গ্রহণ করুন**
(প্রত্যাখ্যান করলে টাইপ করা নিশ্চিতকরণের মাধ্যমে অ্যাপটি **আনইনস্টল** হয়ে যায়) **→ আপনার corpus-এর
পাসফ্রেজ তৈরি করুন**। corpus **ডিফল্টভাবে সংরক্ষিত অবস্থায় এনক্রিপ্ট করা থাকে (encrypted at rest)** (SQLCipher 4) এবং হারানো পাসফ্রেজের
**কোনো পুনরুদ্ধার নেই** (পাসফ্রেজ হারালে আবার সংগ্রহের সময় খরচ হয় —
corpus ওয়েব থেকে পুনর্গঠিত হয়)। এরপর অ্যাপটি **অফলাইনে (airplane mode)** চালু হয়;
অনলাইনে যেতে হলে **একটি সম্মতি-পপআপ** পার হতে হয়, যা কাজটির নাম বলে এবং কোনো অনুরোধ বাইরে যাওয়ার আগে আপনার স্থানীয়
interface IP-গুলো দেখায়।

terminal পছন্দ করেন? `cd ~/open-omniscience && ./scripts/launch.sh` একই কাজ করে।

**পরে পরীক্ষা বা অপসারণ করতে:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. একটি Qubes OS Debian AppVM-এ (লক্ষ্য-প্ল্যাটফর্ম)

Qubes প্রতিবার boot-এ একটি AppVM-এর root filesystem পুনরায় সেট করে; শুধু `/home` (এবং
`/usr/local`, `/rw`) টিকে থাকে। তাই সিস্টেম প্যাকেজগুলো **TemplateVM**-এ যায়, আর
অ্যাপ + virtualenv + ডেটাবেস **AppVM**-এর `/home`-এর নিচে থাকে।

**1. TemplateVM-এ (একবার):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
TemplateVM বন্ধ করুন, তারপর **AppVM রিবুট করুন** যাতে প্যাকেজগুলো দৃশ্যমান হয়।

**2. AppVM-এ (আপনার ব্যবহারকারী হিসেবে, sudo ছাড়া):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. এটি চালান (শুধু 127.0.0.1-এ bind করে):**
**Open Omniscience** launcher-এ (অ্যাপস মেনু / ডেস্কটপ) ডাবল-ক্লিক করুন, অথবা:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
AppVM-এর browser-এ **http://127.0.0.1:8000** খুলুন।

server কখনো loopback-এর বাইরে শোনে না। একবার চালানোর পর পুরোপুরি অফলাইনে যেতে
AppVM-এর NetVM বিচ্ছিন্ন করুন — UI-এর কোনো বাহ্যিক নির্ভরতা নেই এবং সংরক্ষিত ডেটা নিয়ে কাজ চালিয়ে যায়।

---

## B. স্থানীয় ডেভেলপমেন্ট রান (Python 3.13 সহ যেকোনো Linux)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

কাজের env var: `OO_DATA_DIR` (যেখানে SQLite DB + ডেটা থাকে), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (প্রতি-host ভদ্রতা-বিরতি, সেকেন্ডে)।

### Tails-এ

Debian/Ubuntu/Tails stdlib-এর `venv`/`ensurepip` একটি **আলাদা apt প্যাকেজে** দেয়, তাই
সেটি ইনস্টল না হওয়া পর্যন্ত `python3 -m venv` ব্যর্থ হয়। `install.sh` এখন এটি
**স্বয়ংক্রিয়ভাবে** ইনস্টল করে — Tails-এ এর জন্য একটি **অ্যাডমিনিস্ট্রেশন পাসওয়ার্ড** লাগে (এটি
Welcome Screen-এ সেট করুন; ডিফল্টভাবে এটি বন্ধ থাকে) এবং একটি সচল **Tor সংযোগ** লাগে (apt Tor-এর মাধ্যমে
ডাউনলোড করে)। আপনি যদি নিজে apt চালাতে চান, তবে `OO_NO_APT=1` দিয়ে এটি বাদ দিন।

Tails-এর জন্য নির্দিষ্ট দুটি সৎ সতর্কতা:

- **Python সংস্করণ।** Tails হলো Debian 12 → **Python 3.11**, কিন্তু অ্যাপটির লক্ষ্য **3.13**।
  আপনার কাছে একটি 3.13 interpreter থাকতে হবে এবং installer-কে সেটির দিকে নির্দেশ করতে হবে
  (`OO_PYTHON=python3.13 ./install.sh`); 3.13 এবং এর `python3.13-venv` প্যাকেজ Tails-এর ডিফল্ট
  repository-তে **নেই**।
- **স্মৃতিহীনতা (Amnesia)।** apt দিয়ে ইনস্টল করা সবকিছু — এবং পুরো `.venv` — **রিবুটে হারিয়ে যায়**, যদি না
  সেগুলো Persistent Storage-এ থাকে: venv প্যাকেজটি **Persistent Storage → Additional
  Software**-এর মাধ্যমে যোগ করুন, এবং checkout + `OO_DATA_DIR` persistent volume-এ রাখুন।

### বিদ্যমান ডেটাবেস আপগ্রেড করা

নতুন ইনস্টলেশন স্বয়ংক্রিয়ভাবে schema তৈরি করে (`init_db()`), এবং ডেটাবেসে
বর্তমান migration baseline-এর ছাপ দেওয়া হয়। ভবিষ্যতের কোনো রিলিজ যখন
schema বদলায়, তখন একটি বিদ্যমান ডেটাবেস এভাবে আপগ্রেড করুন:
```bash
alembic upgrade head
```
`alembic check` জানায় model ও migration-গুলো সামঞ্জস্যপূর্ণ কিনা (CI এটি পাহারা দেয়)।

---

## C. Windows 11-এ (PowerShell)

**সমর্থনের সৎ অবস্থা — আগে এটি পড়ুন।** প্রতিটি CI রান `windows-latest`-এ তিনটি জিনিস প্রমাণ করে:
নির্ভরতা (dependency) ইনস্টল, **boot পরীক্ষা** (পুরো অ্যাপ import হয়),
এবং **SQLCipher at-rest এনক্রিপশন** — শেষটি একটি *blocking* lane-এ, তাই
এনক্রিপশনটি অনুমান নয়। এর বাইরে কিছুই প্রমাণিত নয়। Windows-এর **pytest lane
আটকে যায়** (সাম্প্রতিক সম্পূর্ণ রানগুলো `pytest`-এ 3h21m এবং ~6h ধরে বসে ছিল, যেখানে
macOS-এ লাগে 18 মিনিট), এবং **কেউ Windows-এ UI ক্লিক করে পরীক্ষা করেনি**। তাই: ইনস্টল
ও চালু হওয়া কাজ করবে বলে আশা করুন, boot-এর পরের সবকিছুকে অযাচাইকৃত ধরুন, এবং যা
ভাঙে তা দয়া করে জানান। Linux-ই রিলিজের মানদণ্ড (release gate) থাকছে।

### 1. ইনস্টল

**PowerShell** খুলুন (administrator অধিকার লাগে না, যদি না Python নিজেই
ইনস্টল করতে হয়)। installer ডাউনলোড করুন, চাইলে পড়ে নিন, তারপর চালান:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

এটি Git এবং Python 3.13 `winget` দিয়ে ইনস্টল করে, শুধু যদি সেগুলো অনুপস্থিত থাকে,
`%USERPROFILE%\Open-Omniscience`-এ clone করে, একটি `.venv` তৈরি করে, এবং আসল অ্যাপটি
import করে ফলাফল যাচাই করে। আরও পূর্ণ ডিফল্ট সেটের জন্য `-Extras` flag বাদ দিন, অথবা দেখুন
[installer-এর বিকল্পসমূহ](#installer-এর-বকলপসমহ)।

আগেই clone করেছেন? যেখানে আছে সেখানেই চালান — এটি নিজের checkout শনাক্ত করে clone করা বাদ দেয়:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **কেন একটিমাত্র `irm … | iex` লাইন নয়?** কারণ দূরবর্তী কোড এনে সরাসরি
> মেমরি থেকে চালানোই Windows malware ছড়ানোর সবচেয়ে প্রচলিত উপায়, তাই
> স্ক্রিপ্টে যা-ই থাকুক, Defender ওই ধরনটিকে শত্রুভাবাপন্ন হিসেবে গণ্য করে। আগে ফাইলটি
> লিখে রাখা আটকে যাওয়ার সম্ভাবনাও কমায় এবং বেশি সৎও — চালানোর আগে আপনি জিনিসটি
> পড়ে নিতে পারেন।

### 2. Windows Defender যদি installer-কে quarantine করে

এটি `install.ps1` দেখামাত্র মুছে ফেলতে পারে। এটি একটি **ভুল সতর্কসংকেত (false positive)**, এবং আপনার
আমাদের কথায় বিশ্বাস করা উচিত নয় — এটি ঠিক কেন ঘটে তা এখানে দেওয়া হলো, যাতে আপনি নিজেই বিচার করতে পারেন:

- ফাইলটি **স্বাক্ষরবিহীন এবং নতুন**, তাই Defender-এর cloud reputation এটি আগে কখনো দেখেনি।
  অজানা + স্বাক্ষরবিহীন হওয়াই machine-learning heuristic-কে সক্রিয় করার জন্য যথেষ্ট;
  detection-এর নাম সাধারণত `!ml` দিয়ে শেষ হয়।
- এর **ধরন** installer-এর মতো: এটি একটি package manager ডাকে, registry থেকে `PATH`
  আবার পড়ে, Start-মেনু shortcut লেখে, এবং এর `-Uninstall` পথ
  ডিরেক্টরি মুছে ফেলে। Dropper-রাও ঠিক এই কাজগুলোই করে। classifier উদ্দেশ্য নয়, ধরন দেখে নম্বর দেয়।

এতে যা *নেই*, এবং যা আপনি নিজেই ~500 পাঠযোগ্য লাইনে যাচাই করতে পারেন: কোনো
`Invoke-Expression` নেই, কোনো encoded বা obfuscated payload নেই, কোনো `WebClient` নেই, কোনো লুকানো
উইন্ডো নেই, এবং এই repository ছাড়া অন্য কোনো ডাউনলোড নেই।

এগোনোর তিনটি উপায়, সবচেয়ে ভালোটি আগে:

1. **স্ক্রিপ্ট-ছাড়া পথটি ব্যবহার করুন** — নিচের [ম্যানুয়াল ইনস্টল](#মযনযল-ইনসটল-সকরপট-ছড)।
   installer যে কমান্ডগুলো চালায় সেগুলোই, quarantine করার মতো কোনো ফাইল নেই। এটি সবসময় কাজ করে।
2. **ভুল সতর্কসংকেতটি Microsoft-কে জানান**:
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (*Software developer* বেছে নিন)।
   সাধারণত এক-দুই দিনের মধ্যে এর সমাধান হয় এবং আপনার পরে যারা ইনস্টল করবে তাদের সবার জন্য
   ঠিক হয়ে যায় — শুধু আপনার জন্য নয়।
3. **ফোল্ডারটিকে বাদ দিন (exclude)** (Windows Security → Virus & threat protection → Manage
   settings → Exclusions)। এটি করার আগে এর মূল্যটি জেনে নিন: একটি exclusion
   Defender-কে ওই ফোল্ডার *পুরোপুরি* স্ক্যান করা থেকে বিরত রাখে, সবকিছুর জন্য, অনির্দিষ্টকালের জন্য — শুধু
   এই একটি ফাইলের জন্য নয়। আপনার মেশিন, আপনার সিদ্ধান্ত; আমরা ভান করব না যে এর কোনো মূল্য নেই।

আমাদের দিক থেকে সৎ সমাধান হলো code-signing, যা আমাদের এখনো নেই।

### 3. এটি চালান

installer আপনার **ডেস্কটপে** এবং
**Start মেনুতে** একটি **Open Omniscience** shortcut তৈরি করে। এতে ডাবল-ক্লিক করুন: একটি terminal উইন্ডো দেখা দেয়, এবং অ্যাপটি সত্যিই সাড়া দেওয়ার পর
আপনার browser **http://127.0.0.1:8000** ঠিকানায় খোলে। এটি বন্ধ করতে সেই উইন্ডোটি বন্ধ করুন (অথবা
অ্যাপের পাওয়ার বোতাম ব্যবহার করুন)।

এর বদলে terminal থেকে: `scripts\launch.cmd`।

### 4. প্রথমবার চালু করা

প্রতিটি প্ল্যাটফর্মের মতো একই একবারের প্রক্রিয়া: **আপনার ভাষা বেছে নিন → আইনি
শর্তাবলি পড়ে গ্রহণ করুন → আপনার corpus-এর পাসফ্রেজ তৈরি করুন**। corpus **ডিফল্টভাবে
সংরক্ষিত অবস্থায় এনক্রিপ্ট করা থাকে** এবং হারানো পাসফ্রেজের **কোনো পুনরুদ্ধার নেই**। এরপর অ্যাপটি
**অফলাইনে (airplane mode)** চালু হয়; অনলাইনে যেতে হলে **একটি সম্মতি-পপআপ** পার হতে হয়।

### installer-এর বিকল্পসমূহ

| Flag | এটি কী করে |
|------|--------------|
| *(কিছু নয়)* | মূল অংশ + `analysis,compression,columnar`, তারপর যাচাই করে launcher তৈরি করে |
| `-Path <dir>` | `%USERPROFILE%\Open-Omniscience` ছাড়া অন্য কোথাও ইনস্টল করে |
| `-Extras "analysis"` | pip extras বেছে নেয় (শুধু মূল অংশের জন্য `""`) |
| `-Ref <branch>` | একটি নির্দিষ্ট branch বা tag clone করে |
| `-NoPython` | কখনো Git/Python স্বয়ংক্রিয়ভাবে ইনস্টল করে না; এর বদলে নির্দেশনাসহ ব্যর্থ হয় |
| `-NoLauncher` | ডেস্কটপ / Start-মেনু shortcut বাদ দেয় |
| `-Check` | স্বাস্থ্য-প্রতিবেদন (`open-omniscience doctor`-এর মতোই) |
| `-Uninstall` | `.venv` + launcher সরায়; আলাদাভাবে নিশ্চিত না করলে ডেটা রেখে দেয় |
| `-Yes` | প্রশ্নে "হ্যাঁ" ধরে নেয় (তত্ত্বাবধানহীন) |

CI দিয়ে Windows-এ শুধু `analysis` প্রমাণিত। আরও পূর্ণ ডিফল্ট সেট ইনস্টল
না হলে, স্ক্রিপ্টটি নিঃশব্দে ব্যর্থ হওয়া বা extras এসে গেছে বলে ভান করার বদলে **`analysis`-এ ফিরে যায় এবং তা জানিয়ে দেয়**।

### ম্যানুয়াল ইনস্টল (স্ক্রিপ্ট ছাড়া)

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

### Windows-নির্দিষ্ট টীকা

- **Execution policy।** ডিফল্ট policy `.\.venv\Scripts\Activate.ps1` আটকে দেয়।
  এখানে কোনো কিছুর এটি দরকার নেই: `.venv\Scripts\python.exe`-কে পথ ধরে ডাকুন, তাহলে পুরো সমস্যাটিই
  চলে যায়। installer-এর জন্য কমান্ড লাইনে `-ExecutionPolicy Bypass`-ই যথেষ্ট।
- **যে `python` Microsoft Store খোলে।** নতুন Windows 11-এ `python.exe` নামে একটি
  execution-alias stub থাকে, যা কোড চালানোর বদলে Store খোলে। installer এটিকে উপেক্ষা করে (stub কোনো
  সংস্করণ দেখায় না) এবং `py -3.13` launcher ব্যবহার করে। ম্যানুয়ালি ইনস্টল করলে `python`-এর বদলে `py -3.13` ব্যবহার করাই ভালো।
- **আপনার ডেটা কোথায় থাকে।** যেহেতু এটি একটি source checkout, তাই corpus, signing
  key এবং সেটিংস **`<repo>\data`**-তে যায় — `%APPDATA%`-তে নয়। এগুলো অন্য ড্রাইভে রাখতে
  `OO_DATA_DIR` সেট করুন।
- **ফোল্ডারের অনুমতি।** Linux-এ ডেটা ডিরেক্টরি শুধু আপনার ব্যবহারকারীর জন্য লক করা থাকে
  (`chmod 0700`); Windows-এ সেই call কোনো কাজ করে না, তাই ফোল্ডারটি সাধারণ
  Windows ACL উত্তরাধিকারসূত্রে পায়। একটি শেয়ার করা PC-তে `<repo>\data` নিজে সীমিত করুন। corpus ডেটাবেস
  নিজে তবুও যেকোনো ক্ষেত্রেই সংরক্ষিত অবস্থায় এনক্রিপ্ট করা থাকে।
- **SmartScreen / Defender।** এখানে কিছুই code-signed নয়, তাই Windows এর সবকিছুকে
  অজানা হিসেবে গণ্য করে: SmartScreen launcher নিয়ে সতর্ক করতে পারে, এবং Defender
  `install.ps1` সরাসরি quarantine করতে পারে — এটি কী এবং এ বিষয়ে কী
  করবেন তা জানতে দেখুন [§2](#2-windows-defender-যদ-installer-ক-quarantine-কর)। real-time scanning প্রথম `pip install`-কেও উল্লেখযোগ্যভাবে ধীর করে।
- **Port।** 8000 থেকে সরাতে চালু করার আগে `OO_PORT` সেট করুন; `scripts\launch.cmd`
  এটি মেনে চলে।
- **Architecture (x64 / ARM64 / 32-bit)।** installer এটি শনাক্ত করে সামলায়; এখানে
  বলা হলো এটি কী সিদ্ধান্ত নিচ্ছে। `pip install` সফল হবে কিনা তা নির্ধারণ করে মেশিন নয়,
  বরং *interpreter*-এর প্ল্যাটফর্মের জন্য কোন wheel আছে। 2026-08-23 তারিখে PyPI-র বিপরীতে,
  CPython 3.13-এর জন্য, এই প্রকল্পের পুরো নির্ভরতা-সেট জুড়ে মাপা হয়েছে:

  | interpreter | wheel |
  |---|---|
  | `win-amd64` | **প্রতিটি নির্ভরতা।** একমাত্র সম্পূর্ণ architecture। |
  | `win-arm64` | তিনটি ছাড়া সব — `cryptography` (মূল অংশ), `httptools` (মূল অংশ, `uvicorn[standard]`-এর মাধ্যমে) এবং `statsmodels` (`analysis`) |
  | `win32` | `cryptography` কোনো wheel-ই প্রকাশ করে না |

  ARM-এ Windows স্বচ্ছভাবে x64 binary চালায়, তাই **ARM64-এও x64 interpreter-ই সঠিক
  উত্তর** — আপস নয়, সম্পূর্ণ সেট। তাই `install.ps1` সব জায়গায়
  `win-amd64` পছন্দ করে এবং মেশিনে না থাকলে একটি সংগ্রহ করে নেয়:
  architecture উল্লেখ করে winget, তারপর user scope-এ winget, তারপর nuget.org থেকে Python
  Software Foundation-এর স্বয়ংসম্পূর্ণ x64 CPython — nuget এর জন্য যে SHA-512 প্রত্যয়ন করে
  তার বিপরীতে যাচাই করে, `%LOCALAPPDATA%\Open-Omniscience\python-x64`-এ
  খুলে রাখা হয়, কোনো elevation, PATH পরিবর্তন
  বা registry entry লাগে না। এটি ইচ্ছাকৃতভাবে checkout-এর **বাইরে** থাকে: এটি একটি মেশিন
  রিসোর্স, তাই অ্যাপ ফোল্ডার মুছে ফেললেও এটি টিকে থাকে (নইলে এর ওপর তৈরি `.venv`
  ভেঙে যেত) এবং দ্বিতীয় একটি `-Path` checkout এটি আবার ব্যবহার করে। `-Uninstall` এটি সরিয়ে দেয়। hash না মিললে, অথবা
  এমন কোনো সংস্করণ হলে যার hash nuget প্রত্যয়ন করে না, এটি **প্রত্যাখ্যান করে**।

  প্রতিটি ধাপ ব্যর্থ হলে আপনি এক-ডাউনলোডের সমাধানসহ একটি থামার বার্তা পান, `linker link.exe not found`-এ শেষ হওয়া
  বিশ মিনিটের Rust build নয়।

  একটি বিদ্যমান `.venv` **শুধু খুঁজে পাওয়া নয়, যাচাই (probe) করা হয়**: যে interpreter এটি তৈরি করেছিল তার সংস্করণ ও wheel
  প্ল্যাটফর্ম এটি ধরে রাখে, তাই ভিন্ন Python-এ আগের কোনো রানের রেখে যাওয়া venv
  আবার ব্যবহার না করে প্রতিস্থাপন করা হয় — নইলে ওপরের সবকিছু শেষ ধাপে
  নিঃশব্দে বাতিল হয়ে যেত। মিলে যাওয়া একটি venv অপরিবর্তিত অবস্থায় আবার ব্যবহৃত হয়। তাই installer আবার
  চালানোই অর্ধসমাপ্ত ইনস্টলের সমাধান; হাতে কিছু মুছতে হয় না।

  - **কেন নেটিভ ARM64 ইনস্টল স্বয়ংক্রিয়ভাবে চালু নয়।** এর জন্য `cryptography`-কে
    46.0.0–46.0.3-এ আটকে (pin) রাখতে হতো, যা ARM64 wheel থাকা একমাত্র সিরিজ। সেই রিলিজে
    **13টি খোলা advisory রেকর্ড** রয়েছে (একটি statically-linked OpenSSL-সংক্রান্তটি সহ, যা
    48.0.1-এ ঠিক হয়েছে)। এই অ্যাপ প্রমাণে স্বাক্ষর করে; সেটি চুপচাপ ইনস্টল করা হতো নিরাপত্তার
    নাটক (security theatre)। আপনার মেশিনে সত্যিই Visual Studio Build Tools **এবং** একটি Rust
    toolchain থাকলে, `-AllowSourceBuilds` তিনটিকে নেটিভভাবে compile করে — একটি সুস্পষ্ট পছন্দ,
    কখনো ডিফল্ট নয়।
  - **32-bit Windows সমর্থিত নয়**, এবং এটি কোনো কৃত্রিম বাধা নয়, একটি বাস্তব সীমাবদ্ধতা:
    `cryptography` কোনো `win32` wheel দেয় না। 64-bit Windows আবশ্যক।

---

## D. শুরু থেকে শেষ পর্যন্ত চক্র (UI বা API)

> **উৎসগুলো আগে থেকেই কনফিগার করা।** প্রথমবার চালু করার সময় (অথবা `install.sh --appvm` চলাকালীন)
> বাছাই করা catalog-গুলো (`configs/sources.yml` ~3,200 জনস্বার্থমূলক সংবাদমাধ্যম, সঙ্গে
> markets, রাজনৈতিক-বর্ণালি এবং আইন/IP catalog — **সব মিলিয়ে ~3,395টি অনন্য ডোমেইন**)
> স্বয়ংক্রিয়ভাবে যোগ (seed) হয় — তাই আপনি সঙ্গে সঙ্গে সংগ্রহ (ingest) শুরু করতে পারেন।
> (catalog বাড়ার সঙ্গে সঙ্গে এই সংখ্যাগুলো **বদলায়**; প্রকৃত সংখ্যা হলো
> `configs/*.yml`-এ বর্তমানে যা আছে।) পুনরায় seed করা idempotent। স্বয়ংক্রিয় seed বন্ধ করতে
> `OO_AUTOSEED=0` ব্যবহার করুন; ম্যানুয়ালি আবার seed করতে `python scripts/seed_sources.py` অথবা
> `POST /api/sources/seed-defaults` ব্যবহার করুন। ফিড URL/robots নীতি সময়ের সঙ্গে বদলায়;
> নৈতিক fetcher যা নিশ্চিত করতে পারে না তা প্রত্যাখ্যান করে, তাই আপনার অনুসন্ধানের প্রয়োজন অনুযায়ী
> তালিকাটি ছাঁটাই/প্রসারিত করুন।

**UI-তে:** একবার **অনলাইনে যান** (airplane-mode toggle → একটি সম্মতি-পপআপ), এবং
**সংগ্রহ নিজে থেকেই** পটভূমিতে **চলে** — ভাষা ও উৎস-ট্যাগ জুড়ে স্তরভিত্তিকভাবে (stratified),
robots মেনে এবং হার-সীমিতভাবে (rate-limited)। তারপর **অন্বেষণ করুন-এ অনুসন্ধান করুন** (sidebar ট্যাব; omnibar-এ, টপ বার বা Ctrl/⌘-K, Enter চাপলে
অন্বেষণ করুন একটি নতুন ব্রাউজার ট্যাবে খোলে) — মিলে যাওয়া নিবন্ধগুলোর বিশ্লেষণ
ফলাফলের নিচে দেখা যায়, যেখানে আপনি ফিল্টার করেন, পড়েন, Boolean query চালান এবং **রপ্তানি** করেন (CSV/JSON, পদ্ধতির
পরিশিষ্ট, স্বাক্ষরিত প্রমাণ)। আপনি এখনো **সেটিংস → উন্নত → সংগ্রহ / উৎস** থেকে একটি উৎস যোগ করে
ম্যানুয়ালি একটি একক ফিড বা URL *আনতে (Ingest)* পারেন।

**API-এর মাধ্যমে:**
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

যন্ত্র-পাঠযোগ্য API schema আছে **http://127.0.0.1:8000/openapi.json**-এ। ইন্টারঅ্যাকটিভ Swagger পৃষ্ঠাটি ডিফল্টভাবে বন্ধ থাকে (এটি তৃতীয়-পক্ষের host থেকে asset লোড করে); একজন ডেভেলপার `/docs`-এ এটি পেতে `OO_API_DOCS=1` দিয়ে অ্যাপটি চালু করতে পারেন।

---

## E. বিশ্লেষণের সক্ষমতা

সবকিছুই স্থানীয়-প্রথম এবং ব্যর্থ হলে উচ্চস্বরে জানায় (কখনো কিছু বানিয়ে দেয় না)। পূর্ণ schema `/openapi.json`-এ।

**স্থানীয় LLM (Ollama)।** এটি **সেটিংস → এআই** থেকে সেট আপ করুন: অ্যাপের ভেতরের,
**checksum-যাচাইকৃত** Ollama installer (Linux) এবং একটি **মডেল ডাউনলোড সারি** (প্রকৃত
বাইট-অগ্রগতি, বাতিল), একটি সক্রিয়-মডেল বাছাইকারী এবং একটি সম্পাদনযোগ্য-prompt প্যানেল। অথবা
**ollama.com** থেকে নিজে Ollama ইনস্টল করে `ollama pull llama3.2:3b` চালান। মডেল ডাউনলোড
**Ollama process-এর মাধ্যমে clearnet দিয়ে** বাইরে যায় (অ্যাপের Tor পথ দিয়ে নয়) — সম্মতির সময়
তা জানানো হয়। টপ-বারের LLM pill সরাসরি অবস্থা দেখায় (সেটিংস → এআই খুলতে এতে ক্লিক করুন); প্রতিটি
অনুসন্ধান-ফলাফলে **সারসংক্ষেপ** এবং **অনুবাদ** বোতাম আছে। API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Ollama না চললে, এগুলো একটি স্পষ্ট বার্তাসহ HTTP 503 ফেরত দেয় — নকল সারসংক্ষেপ নয়।

**পণ্যের দাম + সৎ সহসম্পর্ক (correlation)।**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
Correlation scipy (Pearson/Spearman) থেকে একটি প্রকৃত coefficient + p-value + n ফেরত দেয়,
একটি "সহসম্পর্ক ≠ কার্যকারণ" সতর্কতাসহ; যথেষ্ট overlap না থাকলে → `insufficient_data`।

**পর্যবেক্ষণ (Monitoring)।** `POST /api/monitoring/health` প্রকৃত পৌঁছানো-যোগ্যতা
পরীক্ষা করে (নৈতিক fetcher-এর মাধ্যমে); `GET /api/monitoring/anomalies`
z-score অনুযায়ী নিবন্ধ-সংখ্যার আকস্মিক বৃদ্ধি চিহ্নিত করে। **ইমেইল:** `POST /api/sources/{id}/ingest-email`
(IMAP) বার্তাগুলোকে একই অনুসন্ধানযোগ্য corpus-এ যোগ করে।

**ছবির metadata যাচাই।** `POST /api/verify/image-metadata`
(একটি ছবি আপলোড করুন) এর format, মাত্রা, EXIF এবং GPS ফেরত দেয়, সাদামাটা তথ্যভিত্তিক
পর্যবেক্ষণসহ (যেমন editing-software ট্যাগ আছে, কোনো ধারণ-সময়চিহ্ন নেই)। এর পরিধি সৎভাবে
*metadata পরীক্ষা* হিসেবে নির্ধারিত — deepfake/কারসাজি শনাক্তকরণ **নয়** (সেটি
বানোয়াট ছিল এবং working tree থেকে সরিয়ে quarantine করা হয়েছে; দেখুন
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md))।

**স্বাক্ষরিত প্রমাণ-বান্ডেল।** বিশ্লেষণ উইন্ডোর **স্বাক্ষরিত প্রমাণ রপ্তানি করুন**
বোতাম (অথবা `POST /api/reports/evidence`) একটি Merkle-rooted,
Ed25519-স্বাক্ষরিত বান্ডেল তৈরি করে। যে কেউ এই অ্যাপ ছাড়াই অফলাইনে এটি যাচাই করতে পারেন:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**তত্ত্বাবধানের শৃঙ্খল।** **তত্ত্বাবধানের শৃঙ্খল** UI প্যানেল স্বাক্ষরিত,
কারসাজি-ধরা-পড়ে (tamper-evident) এমন উৎস-তথ্য অনুসরণ করে এবং চলমান অবস্থায় এর আচরণ বদলাতে দেয়:
post-quantum স্বাক্ষর, anchoring mode (অফলাইন `local` বনাম Bitcoin-anchored
**OpenTimestamps**), এবং ingest-এর সময় স্বয়ংক্রিয় লগিং। toggle-গুলো *পছন্দ* মাত্র — প্যানেলটি
**কার্যকর** অবস্থা দেখায়, তাই যার অতিরিক্ত অংশ (extra) ইনস্টল করা নেই, সেটি চালু আছে বলে
কিছুই দাবি করে না। API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
পূর্ণ মডেল, হুমকি-মডেল (threat model) এবং গোপনীয়তা-সংক্রান্ত সতর্কতা: [USER_MANUAL.md](USER_MANUAL.md)।

---

## "নৈতিক সংগ্রহ (ethical ingest)" যা নিশ্চিত করে

- robots.txt আনা হয়, প্রতি host-এ cache করা হয়, এবং এটি **fail-closed**: এটি নিশ্চিত করা না
  গেলে (নেটওয়ার্ক ত্রুটি, timeout, 5xx, অথবা একটি সীমাবদ্ধ 401/403), URL-টি
  **আনা হয় না**।
- প্রতি host-এ একটি ন্যূনতম বিরতি প্রয়োগ করা হয় (`Crawl-delay` মেনে)।
- একটিমাত্র fetch পথ, একটি পরিচয়-প্রকাশক User-Agent (সুরক্ষিত মোডে একটি সাধারণ User-Agent, কেবল Wikimedia-র সার্ভারে API ও ডাম্প অনুরোধ ছাড়া), নিবন্ধের জন্য শুধু HTML — কোনো কাঁচা bypass নেই।
- নিষ্কাশনে (extraction) trafilatura ব্যবহৃত হয়; কোনো প্রকৃত নিবন্ধ-অংশ পাওয়া না গেলে কিছুই সংরক্ষণ করা হয় না
  (কোনো বানোয়াট "No Title / No Content" সারি নয়)।
- প্রতিটি সংরক্ষিত নিবন্ধ উৎস-তথ্য বহন করে: উৎস, মূল URL, canonical URL,
  content hash (ডুপ্লিকেট বাদ দিতে ব্যবহৃত), আনার সময়।
