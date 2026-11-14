<!-- hi: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# त्वरित शुरुआत — ऐप चलाना

यह **भरोसेमंद मूल हिस्सा** है (ऐप एक ईमानदार **alpha** है — `v0.5.0`, यानी
`0.5` का investigator's-desk चक्र, 2026-10-26 को टैग किया गया; चलता हुआ ऐप अपना सटीक
संस्करण स्वयं बताता है): एक स्रोत जोड़ें → उसे नैतिक तरीके से scrape करें → उत्पत्ति-विवरण (provenance) के साथ सहेजें →
Boolean पूर्ण-पाठ खोज → निर्यात। Local-first, केवल loopback, कोई खाता नहीं।

---

## 0. आसान तरीका — एक कमांड, फिर चलाने के लिए डबल-क्लिक

अगर आप बस ऐप का उपयोग करना चाहते हैं (बाद में command-line की किसी जानकारी की ज़रूरत नहीं):

**Linux / macOS** — एक terminal में:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — PowerShell में। पहले इसे डाउनलोड करें, *फिर* चलाएँ:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

Windows Defender फिर भी इस फ़ाइल को quarantine कर सकता है — यह unsigned और नई है। यह एक
false positive है; [§C](#c-windows-11-पर-powershell) ठीक-ठीक बताता है कि ऐसा क्यों होता है, और आपको
बिना script वाला एक रास्ता देता है जिसे कोई नहीं रोक सकता।

Windows का समर्थन Linux की तुलना में सीमित है, और यह अंतर
[§C](#c-windows-11-पर-powershell) में साफ़-साफ़ बताया गया है — इस पर भरोसा करने से पहले उसे पढ़ें।

> **भरोसा करने से पहले जाँचें।** किसी script को अपने shell में pipe करने से आपकी
> मशीन पर कोड चलता है। दोनों जानबूझकर छोटे रखे गए हैं — चाहें तो पहले उन्हें पढ़ लें
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1))।
> वे git + Python 3.13 की जाँच करते हैं, इस repo को `~/open-omniscience`
> (Windows पर `%USERPROFILE%\Open-Omniscience`) में clone करते हैं, और काम repo के भीतर वाले
> installer को सौंप देते हैं। आप चाहें तो स्वयं clone करके `./install.sh` / `install.ps1` भी चला सकते हैं।

`install.sh` **बिना कोई प्रश्न पूछे** चलता है — इसमें **कोई component मेनू नहीं** है। एक ही कमांड
उचित डिफ़ॉल्ट सेट इंस्टॉल करती है:

| डिफ़ॉल्ट रूप से इंस्टॉल | आपको क्या मिलता है |
|----------------------|--------------|
| **Core** *(हमेशा)* | scrape · उत्पत्ति-विवरण के साथ सहेजना · Boolean खोज · निर्यात |
| **Analysis** | कीवर्ड · framing की तुलना · भावना-विश्लेषण (sentiment) |
| **Compression** | corpus का disk पर तेज़ भंडारण |

Local-LLM / Ollama का सेटअप installer का हिस्सा **नहीं** है — यह पूरी तरह ऐप के
**सेटिंग्स → एआई** टैब में है (देखें §E)। इंस्टॉल होने वाले सेट को
`OO_COMPONENTS="…"` env var से बदलें (जैसे `OO_COMPONENTS="analysis,nlp"`); `./install.sh` को
दोबारा चलाना idempotent है और केवल वही इंस्टॉल करता है जो मौजूद नहीं है।

**इसके बाद यह अपने-आप शुरू हो जाता है।** Installer एक **Open Omniscience** launcher बनाता है (apps
मेनू + Desktop) और ऐप को आपके browser में खोलता है। बाद में इसे फिर से शुरू करने के लिए:

- अपना applications मेनू खोलें और **Open Omniscience** खोजें, **या**
- अपने **Desktop** पर **Open Omniscience** आइकन पर डबल-क्लिक करें।

एक छोटी terminal विंडो दिखाई देती है, ऐप शुरू होता है, और आपका browser
**http://127.0.0.1:8000** पर खुलता है। **ऐप बंद करने के लिए वह विंडो बंद करें (या top-bar के power / shutdown
बटन का उपयोग करें)।** (macOS पर launcher आपके Desktop पर `Open Omniscience.command` है;
Windows पर यह `install.ps1` द्वारा बनाया गया एक Desktop + Start-menu shortcut है।)

**पहली बार शुरू करना।** नए इंस्टॉल पर ऐप मुख्य UI से *पहले* आपको एक छोटे, एक-बार के सेटअप से
गुज़ारता है: **अपनी भाषा चुनें → कानूनी शर्तें पढ़ें और स्वीकार करें**
(अस्वीकार करने पर, टाइप करके पुष्टि के बाद, ऐप **अनइंस्टॉल** हो जाता है) **→ अपना corpus
passphrase बनाएँ**। Corpus **डिफ़ॉल्ट रूप से at rest एन्क्रिप्टेड** रहता है (SQLCipher 4) और खोए हुए passphrase की
**कोई recovery नहीं** है (passphrase खोने की कीमत दोबारा संग्रह करने में लगने वाला समय है —
corpus वेब से फिर से बनाया जाता है)। इसके बाद ऐप **offline (airplane mode)** में शुरू होता है;
online होने पर **एक सहमति popup** आता है जो कार्रवाई का नाम बताता है और कोई भी अनुरोध बाहर जाने से पहले
आपके स्थानीय interface IP दिखाता है।

Terminal पसंद है? `cd ~/open-omniscience && ./scripts/launch.sh` यही काम करता है।

**बाद में जाँचना या हटाना:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. Qubes OS Debian AppVM पर (लक्ष्य प्लेटफ़ॉर्म)

Qubes हर boot पर AppVM का root filesystem रीसेट कर देता है; केवल `/home` (और
`/usr/local`, `/rw`) बने रहते हैं। इसलिए system packages **TemplateVM** में जाते हैं, और
ऐप + virtualenv + database **AppVM** में `/home` के अंतर्गत रहते हैं।

**1. TemplateVM में (एक बार):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
TemplateVM को बंद करें, फिर **AppVM को reboot करें** ताकि packages दिखाई दें।

**2. AppVM में (अपने user के रूप में, sudo के बिना):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. इसे चलाएँ (केवल 127.0.0.1 से bind होता है):**
**Open Omniscience** launcher (apps मेनू / Desktop) पर डबल-क्लिक करें, या:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
AppVM के browser में **http://127.0.0.1:8000** खोलें।

Server कभी भी loopback के बाहर listen नहीं करता। एक run के बाद पूरी तरह offline होने के लिए
AppVM का NetVM अलग (detach) कर दें — UI की कोई बाहरी निर्भरता नहीं है और यह सहेजे गए डेटा पर काम करता रहता है।

---

## B. स्थानीय dev run (Python 3.13 वाला कोई भी Linux)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

उपयोगी env vars: `OO_DATA_DIR` (जहाँ SQLite DB + डेटा रहते हैं), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (प्रति-host शिष्टता विलंब, सेकंड में)।

### Tails पर

Debian/Ubuntu/Tails stdlib के `venv`/`ensurepip` को एक **अलग apt package** में देते हैं, इसलिए
जब तक वह इंस्टॉल न हो, `python3 -m venv` विफल होता है। `install.sh` अब इसे
**अपने-आप** इंस्टॉल करता है — Tails पर इसके लिए एक **administration password** चाहिए (इसे
Welcome Screen पर सेट करें; यह डिफ़ॉल्ट रूप से बंद होता है) और एक काम करता हुआ **Tor connection** (apt, Tor के ज़रिए
डाउनलोड करता है)। अगर आप apt स्वयं चलाना पसंद करते हैं तो `OO_NO_APT=1` से इससे बाहर निकलें।

Tails से जुड़ी दो ईमानदार चेतावनियाँ:

- **Python संस्करण।** Tails, Debian 12 है → **Python 3.11**, लेकिन ऐप **3.13** को लक्ष्य करता है।
  आपके पास एक 3.13 interpreter उपलब्ध होना चाहिए और installer को उसकी ओर इंगित करना होगा
  (`OO_PYTHON=python3.13 ./install.sh`); 3.13 और उसका `python3.13-venv` package Tails की डिफ़ॉल्ट
  repositories में **नहीं** हैं।
- **स्मृतिलोप (Amnesia)।** apt से इंस्टॉल की गई हर चीज़ — और पूरा `.venv` — **reboot पर खो जाता है**, जब तक कि
  वह Persistent Storage पर न हो: venv package को **Persistent Storage → Additional
  Software** के ज़रिए जोड़ें, और checkout + `OO_DATA_DIR` को persistent volume पर रखें।

### मौजूदा database को अपग्रेड करना

नए इंस्टॉल schema अपने-आप बनाते हैं (`init_db()`), और database पर
मौजूदा migration baseline की मुहर लगाई जाती है। जब कोई भावी release
schema बदलती है, तो मौजूदा database को इससे अपग्रेड करें:
```bash
alembic upgrade head
```
`alembic check` बताता है कि models और migrations आपस में मेल खाते हैं या नहीं (CI इसकी निगरानी करता है)।

---

## C. Windows 11 पर (PowerShell)

**समर्थन की ईमानदार स्थिति — पहले यह पढ़ें।** हर CI run `windows-latest` पर तीन बातें
सिद्ध करता है: dependency install, **boot check** (पूरा ऐप import हो जाता है),
और **SQLCipher at-rest एन्क्रिप्शन** — आख़िरी वाली एक *blocking* lane पर, इसलिए
एन्क्रिप्शन अनुमान नहीं है। इसके आगे कुछ भी सिद्ध नहीं है। Windows की **pytest lane
अटक जाती है** (हाल के पूरे हुए runs `pytest` में 3h21m और ~6h तक रुके रहे, जबकि macOS पर
18 मिनट), और **किसी ने भी Windows पर UI में क्लिक करके नहीं देखा है**। इसलिए: install
और launch के काम करने की उम्मीद करें, boot के बाद की हर चीज़ को असत्यापित मानें, और जो
टूटे उसकी कृपया रिपोर्ट करें। Release gate अब भी Linux ही है।

### 1. इंस्टॉल करें

**PowerShell** खोलें (administrator अधिकारों की ज़रूरत नहीं, जब तक Python को ही
इंस्टॉल न करना पड़े)। Installer डाउनलोड करें, चाहें तो उसे पढ़ें, फिर चलाएँ:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

यह Git और Python 3.13 को `winget` के ज़रिए केवल तभी इंस्टॉल करता है जब वे मौजूद न हों,
`%USERPROFILE%\Open-Omniscience` में clone करता है, एक `.venv` बनाता है, और असली ऐप को
import करके परिणाम की पुष्टि करता है। अधिक पूर्ण डिफ़ॉल्ट सेट के लिए `-Extras` flag हटा दें, या देखें
[Installer के विकल्प](#installer-क-वकलप)।

पहले से clone कर चुके हैं? इसे वहीं चलाएँ — यह अपना checkout पहचान लेता है और clone करना छोड़ देता है:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **एक ही `irm … | iex` पंक्ति क्यों नहीं?** क्योंकि remote कोड को लाकर उसे सीधे memory से
> चला देना ही Windows malware पहुँचाने का सबसे आम तरीका है, इसलिए
> Defender उस ढाँचे को शत्रुतापूर्ण मानता है, चाहे script में कुछ भी हो। पहले फ़ाइल को
> disk पर लिखना, block होने की कम संभावना वाला भी है और अधिक ईमानदार भी — आप चीज़ को
> चलने से पहले पढ़ सकते हैं।

### 2. अगर Windows Defender installer को quarantine कर दे

यह `install.ps1` को देखते ही हटा सकता है। यह एक **false positive** है, और आपको इसके लिए
हमारी बात नहीं माननी चाहिए — ऐसा ठीक-ठीक क्यों होता है, यह यहाँ है, ताकि आप स्वयं परख सकें:

- फ़ाइल **unsigned और नई** है, इसलिए Defender की cloud reputation ने इसे कभी नहीं देखा।
  अज्ञात + unsigned होना अपने-आप में machine-learning heuristics को सक्रिय करने के लिए काफ़ी है;
  detection का नाम आम तौर पर `!ml` पर ख़त्म होता है।
- इसका **ढाँचा** installer जैसा है: यह एक package manager को बुलाता है, registry से `PATH` दोबारा
  पढ़ता है, Start-menu shortcuts लिखता है, और इसका `-Uninstall` रास्ता directories
  हटाता है। Droppers भी यही काम करते हैं। Classifier ढाँचे को आँकता है, इरादे को नहीं।

इसमें क्या *नहीं* है, और जिसे आप लगभग 500 पठनीय पंक्तियों में स्वयं जाँच सकते हैं: कोई
`Invoke-Expression` नहीं, कोई encoded या obfuscated payload नहीं, कोई `WebClient` नहीं, कोई छिपी
विंडो नहीं, और इस repository के अलावा कोई download नहीं।

आगे बढ़ने के तीन रास्ते, सबसे अच्छे से शुरू करके:

1. **बिना script वाला रास्ता अपनाएँ** — नीचे [मैनुअल इंस्टॉल](#मनअल-इसटल-बन-script)।
   वही कमांड जो installer चलाता है, quarantine होने के लिए कोई फ़ाइल नहीं। यह हमेशा काम करता है।
2. **False positive की रिपोर्ट** Microsoft को
   <https://www.microsoft.com/en-us/wdsi/filesubmission> पर करें (*Software developer* चुनें)।
   आम तौर पर इसमें एक-दो दिन लगते हैं और यह आपके बाद इंस्टॉल करने वाले हर व्यक्ति के लिए इसे ठीक कर देता है
   — केवल आपके लिए नहीं।
3. **Folder को बाहर रखें (exclude करें)** (Windows Security → Virus & threat protection → Manage
   settings → Exclusions)। ऐसा करने से पहले इसकी कीमत जान लें: exclusion, Defender को उस folder की
   स्कैनिंग *पूरी तरह* रोक देता है, हर चीज़ के लिए, अनिश्चित काल तक — केवल
   इस एक फ़ाइल के लिए नहीं। आपकी मशीन, आपका फ़ैसला; हम यह दिखावा नहीं करेंगे कि इसकी कोई कीमत नहीं है।

हमारी ओर से ईमानदार समाधान code-signing है, जो अभी हमारे पास नहीं है।

### 3. इसे चलाएँ

Installer आपके **Desktop** पर और **Start menu** में एक **Open Omniscience** shortcut बनाता है।
उस पर डबल-क्लिक करें: एक terminal विंडो दिखाई देती है, और ऐप के वास्तव में जवाब देने पर आपका browser
**http://127.0.0.1:8000** पर खुलता है। इसे बंद करने के लिए वह विंडो बंद करें (या ऐप के
power बटन का उपयोग करें)।

इसके बजाय terminal से: `scripts\launch.cmd`।

### 4. पहली बार शुरू करना

हर प्लेटफ़ॉर्म जैसा ही एक-बार का क्रम: **अपनी भाषा चुनें → कानूनी शर्तें पढ़ें और
स्वीकार करें → अपना corpus passphrase बनाएँ**। Corpus **डिफ़ॉल्ट रूप से at rest
एन्क्रिप्टेड** रहता है और खोए हुए passphrase की **कोई recovery नहीं** है। इसके बाद ऐप
**offline (airplane mode)** में शुरू होता है; online होने पर **एक सहमति popup** आता है।

### Installer के विकल्प

| Flag | यह क्या करता है |
|------|--------------|
| *(कोई नहीं)* | Core + `analysis,compression,columnar`, फिर पुष्टि करता है और launchers बनाता है |
| `-Path <dir>` | `%USERPROFILE%\Open-Omniscience` के अलावा कहीं और इंस्टॉल करें |
| `-Extras "analysis"` | pip extras चुनें (केवल core के लिए `""`) |
| `-Ref <branch>` | किसी विशेष branch या tag को clone करें |
| `-NoPython` | Git/Python को कभी अपने-आप इंस्टॉल न करें; इसके बजाय निर्देशों के साथ विफल हों |
| `-NoLauncher` | Desktop / Start-menu shortcuts छोड़ दें |
| `-Check` | Health report (`open-omniscience doctor` जैसा ही) |
| `-Uninstall` | `.venv` + launchers हटाएँ; डेटा तब तक रखा जाता है जब तक अलग से पुष्टि न की जाए |
| `-Yes` | Prompts पर हाँ मान लें (बिना निगरानी के) |

Windows पर CI द्वारा केवल `analysis` सिद्ध है। अगर अधिक पूर्ण डिफ़ॉल्ट सेट इंस्टॉल होने में
विफल होता है, तो script चुपचाप विफल होने या extras के आ जाने का दिखावा करने के बजाय **`analysis` पर लौट आता है
और यह बताता है**।

### मैनुअल इंस्टॉल (बिना script)

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

### Windows से जुड़ी टिप्पणियाँ

- **Execution policy।** डिफ़ॉल्ट policy `.\.venv\Scripts\Activate.ps1` को block करती है।
  यहाँ किसी चीज़ को इसकी ज़रूरत नहीं: `.venv\Scripts\python.exe` को उसके path से बुलाएँ और पूरी समस्या
  ग़ायब हो जाती है। Command line पर `-ExecutionPolicy Bypass` स्वयं installer को कवर करता है।
- **वह `python` जो Microsoft Store खोलता है।** नए Windows 11 में `python.exe` नाम का एक
  execution-alias stub आता है जो कोड चलाने के बजाय Store खोल देता है। Installer इसे अनदेखा
  करता है (stub कोई संस्करण नहीं छापता) और `py -3.13` launcher का उपयोग करता है। अगर आप
  मैनुअल रूप से इंस्टॉल करते हैं, तो `python` के बजाय `py -3.13` को प्राथमिकता दें।
- **आपका डेटा कहाँ रहता है।** चूँकि यह एक source checkout है, corpus, signing
  keys और settings **`<repo>\data`** में जाते हैं — `%APPDATA%` में नहीं। उन्हें किसी दूसरी drive पर
  रखने के लिए `OO_DATA_DIR` सेट करें।
- **Folder permissions।** Linux पर data directory आपके user तक सीमित (lock) रहती है
  (`chmod 0700`); Windows पर वह call कुछ नहीं करती, इसलिए folder को सामान्य
  Windows ACLs विरासत में मिलते हैं। साझा PC पर `<repo>\data` को स्वयं प्रतिबंधित करें। Corpus database
  स्वयं दोनों ही स्थितियों में at rest एन्क्रिप्टेड रहता है।
- **SmartScreen / Defender।** यहाँ कुछ भी code-signed नहीं है, इसलिए Windows इन सबको
  अज्ञात मानता है: SmartScreen launcher पर चेतावनी दे सकता है, और Defender
  `install.ps1` को सीधे quarantine कर सकता है — यह क्या है और इसके बारे में क्या करें, इसके लिए
  [§2](#2-अगर-windows-defender-installer-क-quarantine-कर-द) देखें। Real-time scanning पहले `pip install` को भी
  काफ़ी धीमा कर देती है।
- **Port।** 8000 से हटने के लिए launch करने से पहले `OO_PORT` सेट करें; `scripts\launch.cmd`
  इसका पालन करता है।
- **Architecture (x64 / ARM64 / 32-bit)।** Installer इसे पहचानता और सँभालता है; यहाँ
  बताया गया है कि वह क्या तय कर रहा है। `pip install` सफल होगा या नहीं, यह
  मशीन से नहीं, बल्कि इससे तय होता है कि *interpreter* के platform के लिए कौन-से wheels मौजूद हैं। 2026-08-23 को
  PyPI से मापा गया, CPython 3.13 के लिए, इस project के पूरे dependency सेट पर:

  | interpreter | wheels |
  |---|---|
  | `win-amd64` | **हर dependency।** एकमात्र पूर्ण architecture। |
  | `win-arm64` | तीन को छोड़कर सभी — `cryptography` (core), `httptools` (core, `uvicorn[standard]` के ज़रिए) और `statsmodels` (`analysis`) |
  | `win32` | `cryptography` कोई भी प्रकाशित नहीं करता |

  ARM पर Windows x64 binaries को पारदर्शी रूप से चलाता है, इसलिए **ARM64 पर भी x64 interpreter ही सही
  उत्तर है** — कोई समझौता नहीं, बल्कि पूरा सेट। इसलिए `install.ps1` हर जगह
  `win-amd64` को प्राथमिकता देता है और अगर मशीन पर नहीं है तो उसे प्राप्त कर लेता है:
  पहले architecture का नाम देकर winget, फिर user scope में winget, फिर nuget.org से Python
  Software Foundation का self-contained x64 CPython — nuget द्वारा उसके लिए प्रमाणित SHA-512 से
  सत्यापित, `%LOCALAPPDATA%\Open-Omniscience\python-x64` में खोला गया, जिसे न elevation चाहिए, न PATH में बदलाव
  और न कोई registry entry। यह जानबूझकर checkout के **बाहर** रहता है: यह एक मशीन
  संसाधन है, इसलिए ऐप folder हटाने पर भी बचा रहता है (वरना उस पर बना `.venv`
  टूट जाता) और दूसरा `-Path` checkout इसका दोबारा उपयोग करता है। `-Uninstall` इसे हटा देता है। Hash का मेल न खाना, या
  ऐसा संस्करण जिसके लिए nuget कोई hash प्रमाणित नहीं करता, **अस्वीकार** कर दिया जाता है।

  अगर हर सीढ़ी विफल हो जाए, तो आपको एक-download वाले समाधान के साथ रुकने का संदेश मिलता है, न कि बीस मिनट का
  Rust build जो `linker link.exe not found` पर ख़त्म हो।

  एक मौजूदा `.venv` को **केवल ढूँढा नहीं, बल्कि परखा जाता है**: वह उसी interpreter का संस्करण और wheel
  platform रखता है जिसने उसे बनाया था, इसलिए किसी पहले के run द्वारा किसी
  दूसरे Python पर छोड़ा गया `.venv` दोबारा उपयोग करने के बजाय बदल दिया जाता है — वरना ऊपर की हर चीज़
  आख़िरी कदम पर चुपचाप बेकार हो जाती। मेल खाने वाले `.venv` का बिना छेड़े दोबारा उपयोग होता है। इसलिए
  अधूरे install का समाधान installer को दोबारा चलाना है; हाथ से कुछ भी हटाने की ज़रूरत
  नहीं।

  - **Native ARM64 install अपने-आप सक्षम क्यों नहीं है।** इसके लिए `cryptography` को
    46.0.0–46.0.3 पर pin करना पड़ता, जो ARM64 wheels वाली एकमात्र श्रृंखला है। उस release में
    **13 खुले advisory records** हैं (जिनमें statically-linked OpenSSL वाला एक भी है, जो
    48.0.1 में ठीक हुआ)। यह ऐप साक्ष्यों पर हस्ताक्षर करता है; उसे चुपचाप इंस्टॉल करना सुरक्षा का
    दिखावा होता। अगर आपकी मशीन में सचमुच Visual Studio Build Tools **और** एक Rust
    toolchain है, तो `-AllowSourceBuilds` इन तीनों को native रूप से compile करता है — एक स्पष्ट चुनाव,
    कभी डिफ़ॉल्ट नहीं।
  - **32-bit Windows समर्थित नहीं है**, और यह कोई gate नहीं बल्कि एक वास्तविक सीमा है:
    `cryptography` कोई `win32` wheel नहीं देता। 64-bit Windows आवश्यक है।

---

## D. शुरू से अंत तक का चक्र (UI या API)

> **स्रोत पहले से कॉन्फ़िगर किए गए हैं।** पहली बार शुरू करने पर (या `install.sh --appvm` के दौरान)
> चुने हुए catalogs (`configs/sources.yml` में ~3,200 जनहित वाले समाचार माध्यम, साथ में
> markets, राजनीतिक-स्पेक्ट्रम और law/IP catalogs — **कुल मिलाकर ~3,395 अद्वितीय domains**)
> अपने-आप भर दिए जाते हैं (seed) — ताकि आप तुरंत ingest करना शुरू कर सकें।
> (Catalogs बढ़ने के साथ ये संख्याएँ **बदलती रहती हैं**; वास्तविक आँकड़ा वही है जो
> `configs/*.yml` में इस समय है।) दोबारा seed करना idempotent है। Auto-seed को
> `OO_AUTOSEED=0` से बंद करें; `python scripts/seed_sources.py` या
> `POST /api/sources/seed-defaults` से मैनुअल रूप से दोबारा seed करें। Feed URLs/robots नीतियाँ समय के साथ बदलती हैं;
> ethical fetcher ऐसी किसी भी चीज़ को मना कर देता है जिसकी वह पुष्टि नहीं कर सकता, इसलिए अपनी
> जाँच के अनुसार सूची को छाँटें/बढ़ाएँ।

**UI में:** एक बार **online जाएँ** (airplane-mode toggle → एक सहमति popup) और
**संग्रह पृष्ठभूमि में अपने-आप चलता है** — भाषाओं और स्रोत
tags में संतुलित रूप से बँटा हुआ, robots का सम्मान करते हुए और दर-सीमित। फिर **अन्वेषण करें में खोजें** (sidebar का टैब; top bar या Ctrl/⌘-K वाले omnibar में Enter दबाने पर
अन्वेषण करें एक नए browser टैब में खुलता है) — मिलते-जुलते लेखों का विश्लेषण परिणामों के नीचे दिखाई देता है,
जहाँ आप फ़िल्टर करते हैं, पढ़ते हैं, Boolean queries चलाते हैं और **निर्यात** करते हैं (CSV/JSON, methods
appendix, हस्ताक्षरित साक्ष्य)। आप अब भी **सेटिंग्स → उन्नत → संग्रह / स्रोत** से मैनुअल रूप से कोई स्रोत जोड़ सकते हैं और
किसी एक feed या URL को *इनजेस्ट (Ingest)* कर सकते हैं।

**API के ज़रिए:**
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

Machine-readable API schema **http://127.0.0.1:8000/openapi.json** पर है। Interactive Swagger पेज डिफ़ॉल्ट रूप से बंद रहता है (यह तृतीय-पक्ष hosts से assets लोड करता है); कोई developer इसे `/docs` पर पाने के लिए ऐप को `OO_API_DOCS=1` के साथ शुरू कर सकता है।

---

## E. विश्लेषण क्षमताएँ

सभी local-first हैं और विफल होने पर साफ़-साफ़ बताती हैं (कभी कुछ गढ़ती नहीं)। पूरे schemas `/openapi.json` पर।

**Local LLM (Ollama)।** इसे **सेटिंग्स → एआई** से सेट करें: ऐप के भीतर एक
**checksum-verified** Ollama installer (Linux) और साथ में एक **model download queue** (वास्तविक
byte प्रगति, रद्द करने की सुविधा), एक सक्रिय-model चुनने वाला और संपादन-योग्य prompts का panel। या
Ollama को स्वयं **ollama.com** से इंस्टॉल करें और `ollama pull llama3.2:3b` चलाएँ। Model downloads
**clearnet पर Ollama process के ज़रिए** बाहर जाते हैं (ऐप के Tor रास्ते से नहीं) — यह सहमति के समय
बताया जाता है। Top-bar का LLM pill जीवंत स्थिति दिखाता है (सेटिंग्स → एआई खोलने के लिए उस पर क्लिक करें); हर
खोज परिणाम में **सारांश** और **अनुवाद** बटन होते हैं। API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
अगर Ollama नहीं चल रहा है, तो ये एक स्पष्ट संदेश के साथ HTTP 503 लौटाते हैं — नकली सारांश नहीं।

**Commodity कीमतें + ईमानदार सहसंबंध (correlation)।**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
Correlation, scipy (Pearson/Spearman) से एक वास्तविक coefficient + p-value + n लौटाता है,
"सहसंबंध ≠ कार्य-कारण" (correlation ≠ causation) चेतावनी के साथ; बहुत कम overlap → `insufficient_data`।

**निगरानी (Monitoring)।** `GET /api/monitoring/health` वास्तविक पहुँच-योग्यता
जाँच करता है (ethical fetcher के ज़रिए); `GET /api/monitoring/anomalies`
z-score से लेखों की संख्या में अचानक उछाल को चिह्नित करता है। **Email:** `POST /api/sources/{id}/ingest-email`
(IMAP) संदेशों को उसी खोजने-योग्य corpus में जोड़ देता है।

**Image metadata सत्यापन।** `POST /api/verify/image-metadata`
(एक image अपलोड करें) उसका format, आयाम, EXIF और GPS, सीधे तथ्यात्मक
अवलोकनों के साथ लौटाता है (जैसे editing-software tag मौजूद है, capture timestamp नहीं है)। इसका दायरा
ईमानदारी से *metadata जाँच* तक सीमित है — यह deepfake/हेरफेर पहचान **नहीं** है (वह
गढ़ी हुई थी और उसे working tree से हटाकर quarantine कर दिया गया; देखें
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md))।

**हस्ताक्षरित साक्ष्य bundles।** विश्लेषण विंडो का **हस्ताक्षरित साक्ष्य निर्यात करें**
बटन (या `POST /api/reports/evidence`) एक Merkle-rooted,
Ed25519-signed bundle बनाता है। कोई भी इसे offline, इस ऐप के बिना, सत्यापित कर सकता है:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**अभिरक्षा शृंखला (Chain of custody)।** **अभिरक्षा शृंखला** UI panel हस्ताक्षरित,
छेड़छाड़-स्पष्ट (tamper-evident) उत्पत्ति-विवरण पर नज़र रखता है और आपको runtime पर इसके व्यवहार को toggle करने देता है:
post-quantum हस्ताक्षर, anchoring mode (offline `local` बनाम Bitcoin-anchored
**OpenTimestamps**), और ingest पर auto-logging। Toggles *प्राथमिकताएँ* हैं —
panel **प्रभावी** स्थिति दिखाता है, इसलिए कोई भी चीज़ चालू होने का दावा नहीं करती जब उसका extra
इंस्टॉल न हो। API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
पूरा model, threat model और गोपनीयता संबंधी चेतावनियाँ: [USER_MANUAL.md](USER_MANUAL.md)।

---

## "नैतिक ingest" क्या गारंटी देता है

- robots.txt लाया जाता है, प्रति host cache किया जाता है, और **fail-closed** होता है: अगर उसकी
  पुष्टि न हो सके (network त्रुटि, timeout, 5xx, या प्रतिबंधित 401/403), तो URL
  **नहीं** लाया जाता।
- प्रति-host न्यूनतम अंतराल लागू किया जाता है (`Crawl-delay` का पालन करते हुए)।
- एक ही fetch रास्ता, पहचान बताने वाला User-Agent (संरक्षित मोड में एक सामान्य User-Agent, सिवाय Wikimedia के servers को API और dump अनुरोधों के), लेखों के लिए केवल HTML — कोई सीधा bypass नहीं।
- Extraction के लिए trafilatura का उपयोग होता है; अगर लेख का कोई वास्तविक मुख्य भाग नहीं मिलता, तो कुछ भी सहेजा नहीं जाता
  (कोई गढ़ी हुई "No Title / No Content" पंक्तियाँ नहीं)।
- हर सहेजा गया लेख उत्पत्ति-विवरण रखता है: स्रोत, मूल URL, canonical URL,
  content hash (dedup के लिए उपयोग होता है), fetch का समय।
