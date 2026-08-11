# Installing on an air-gapped machine

This guide installs Open Omniscience on a computer that has **no internet
connection and never will** — the machine is offline before, during and after the
install, and it does not need a single one of the project's dependencies
beforehand.

It does not change how anyone else installs the app. The ordinary one-command
install is untouched and needs nothing from this page:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

---

## The idea: two downloads, one folder

The application is small. Its dependencies — NumPy, SciPy, pandas, lxml,
SQLCipher and around eighty more — are not: roughly **230 MB**. Shipping those
inside the main repository would make every ordinary download several times
larger for no benefit, so they travel separately:

| Download | What it is | Size |
|---|---|---|
| **The application** | this repository | ~65 MB |
| **The dependency bundle** | every Python package, prepared ahead of time | ~230 MB |

You extract both **side by side** in the same folder, and double-click the
offline installer. It finds the bundle on its own.

```
somewhere-on-the-usb-stick/
├── Open-Omniscience-main/                          <- the application
│   ├── Install Open Omniscience (offline).desktop  <- double-click this
│   └── install-offline.sh
└── open-omniscience-offline-linux-x86_64-cp313/    <- the dependency bundle
    ├── offline-manifest.json
    ├── wheels/
    └── bootstrap/
```

---

## Step 1 — on a connected machine: build the bundle

Run this **once**, on a computer that has internet. It downloads every package
the app needs and writes a self-describing folder.

```bash
git clone https://github.com/ideotion/Open-Omniscience.git
cd Open-Omniscience
./scripts/build_offline_bundle.sh --zip
```

You get `dist/open-omniscience-offline-linux-<arch>-cp313/` and a matching
`.zip`. Copy that, plus this repository, onto the USB stick.

### The one rule you cannot bend

Python packages contain **compiled code**. A bundle is only valid for:

* the same **CPU architecture** (`x86_64` and `aarch64` are not interchangeable),
* the same **Python minor version** (3.13),
* a **glibc no newer** than the target machine's.

Build the bundle on a machine that matches the target, or on an older one. The
bundle records all three facts, and the installer refuses loudly rather than
failing halfway through with an unreadable pip error.

### Options

```bash
# Only the core application — smallest bundle, no analytics extras
./scripts/build_offline_bundle.sh --extras ""

# The default set (what the online installer installs)
./scripts/build_offline_bundle.sh --extras "analysis,compression,columnar"

# Also carry a Python interpreter (see "No Python 3.13?" below)
./scripts/build_offline_bundle.sh --with-python <url-of-a-cpython-3.13-tarball>
```

---

## Step 2 — on the air-gapped machine: install

1. Copy **both** folders off the stick, side by side, somewhere you can write —
   your home folder is ideal. (Installing directly from the stick does not work:
   the app installs into its own folder, and sticks are often read-only or
   too slow.)
2. Open the application folder.
3. Double-click **“Install Open Omniscience (offline)”**.

The first time you double-click a launcher, some Debian desktops ask whether you
trust it — choose *Trust and Launch*, or right-click → *Allow Launching*. If your
file manager will not run it at all, use a terminal:

```bash
cd Open-Omniscience-main
./install-offline.sh
```

The installer will:

1. find the dependency bundle beside the application folder,
2. check **every file against its SHA-256 checksum** — USB sticks corrupt files
   quietly, and a truncated package otherwise surfaces much later as a baffling
   error,
3. find Python 3.13 (or unpack the one in the bundle),
4. build the virtual environment and install everything from the bundle,
5. create the desktop launcher and start the app.

From there the app opens in your browser and walks you through its own
first-launch setup — language, terms, and the passphrase for the encrypted
database. **The app boots offline by default**, so nothing is attempted over a
network at any point.

---

## No Python 3.13 on the target?

Open Omniscience needs **Python 3.13 or newer**.

* **Debian 13 (trixie)** ships Python 3.13 — nothing to do.
* **Debian 12 (bookworm)** ships Python 3.11 — too old.

You do **not** need Debian's `python3-venv` package, which is where offline
installs usually get stuck: the bundle carries pip's own wheels and the installer
bootstraps the virtual environment without it.

If the machine has no Python 3.13, put one in the bundle. On the connected
machine, download a self-contained CPython 3.13 build for Linux
(`x86_64-unknown-linux-gnu`, the `install_only` variant) from a source you
trust — the [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
project publishes them with checksums — and pass its URL:

```bash
./scripts/build_offline_bundle.sh --with-python "<url>"
```

The builder prints the SHA-256 of exactly what it downloaded. **Compare it
against the publisher's own published checksum before trusting the stick** — this
project will not carry a checksum it has not verified itself, so that comparison
is yours to make. The offline installer then uses this interpreter only when the
machine has none of its own; it is unpacked inside the application folder and
nothing is installed system-wide.

---

## Keeping it up to date

The application and its dependencies update independently, which is the point of
splitting them:

* **App changed, dependencies did not** (the common case) — replace only the
  application folder and re-run the offline installer. It reuses the existing
  bundle.
* **Dependencies changed** (`pyproject.toml` touched) — rebuild the bundle on the
  connected machine and copy both across.

Re-running the installer is safe at any time; it is idempotent, and your database
is never touched by it.

---

## Troubleshooting

**“No dependency bundle found.”**
The two folders are not side by side, or the bundle folder was renamed and no
longer contains `offline-manifest.json`. Point at it directly:
```bash
OO_OFFLINE_BUNDLE=/media/usb/open-omniscience-offline-linux-x86_64-cp313 ./install-offline.sh
```

**“This bundle was built for 'x86_64', but this machine is 'aarch64'.”**
Compiled packages cannot cross architectures. Rebuild the bundle on a machine
matching the target.

**“The dependency bundle is damaged.”**
A file does not match its checksum — almost always an incomplete copy or a
failing stick. Copy the bundle again. Nothing was installed.

**“This folder is not writable.”**
You are running from the USB stick. Copy both folders to your home folder first.

**A package fails to install with `GLIBC_2.xx not found`.**
The bundle was built on a machine with a newer glibc than the target. Rebuild it
on an older machine (or one running the same Debian release as the target).

---

## What the bundle deliberately does not contain

None of these are needed to install or run the app:

* **Ollama and local AI models** — large, optional, and installed from the app's
  Settings → AI tab. On an air-gapped machine, use the app's own offline model
  import instead.
* **Wikipedia dumps and OpenStreetMap regions** — downloaded on demand, in the app.

The application is fully functional without them.
