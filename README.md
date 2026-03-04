# Subnet Calculator Mac

A standalone, browser-based subnet calculator for macOS network professionals.

Launches a local web server, opens your default browser, and shuts itself down cleanly when you close the tab. No internet connection required. No Python packages to install — pure stdlib only.

Port **8766** (different from SuperPutty Mac on 8765).

---

## Features

| Tab                | What it does                                                                                                                                                                        |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **IPv4 Subnet**    | Full breakdown of any IP/prefix — network, broadcast, host range, binary representation, class, type, supernet and next-split info                                                  |
| **Split Subnet**   | Divide a network into equal-sized subnets — by count _or_ by minimum hosts per subnet                                                                                               |
| **VLSM**           | Variable-Length Subnet Masking — allocate subnets of different sizes from a parent network; shows remaining unallocated space                                                       |
| **Supernet**       | Collapse/summarise a list of networks into the minimum covering set of prefixes                                                                                                     |
| **Range → CIDR**   | Convert a start/end IP range to the minimum set of CIDR blocks                                                                                                                      |
| **Wildcard / ACL** | Generate wildcard masks plus ready-to-paste Cisco IOS ACL statements, OSPF/EIGRP/BGP network statements, prefix lists, and JunOS route-filters                                      |
| **IPv6**           | Analyse any IPv6 address or prefix — compressed/expanded forms, network address, type flags (link-local, ULA, GUA, multicast, loopback, 6to4, NAT64)                                |
| **Reference**      | Full /0–/32 subnet mask table, RFC 1918 private ranges, special-purpose ranges (loopback, APIPA, documentation, CG-NAT, benchmark), IPv6 address types, and common well-known ports |

---

## Prerequisites

| Requirement              | Notes                                                          |
| ------------------------ | -------------------------------------------------------------- |
| macOS                    | Tested on macOS 15 (Apple Silicon) and macOS 14 (Intel)        |
| Xcode Command Line Tools | Provides `/usr/bin/python3`. Install: `xcode-select --install` |

That's it. No `pip`, no virtual environments, no dependencies.

---

## Quick Start

```bash
cd /path/to/subnetCalculator

# Run directly
/usr/bin/python3 subnet_calculator.py

# Or double-click the app bundle (build it first — see below)
open "Subnet Calculator.app"
```

The script starts a local web server on **port 8766**, then opens `http://127.0.0.1:8766/` in your default browser automatically.

The server shuts down cleanly when you:

- Close the browser tab
- Press **Ctrl-C** in the terminal
- Double-click the app again (it kills any stale process on the port first)

---

## Building the App Bundle

Run once to create a double-clickable `Subnet Calculator.app`:

```bash
bash make_app.sh
```

This:

1. Generates a 1024 × 1024 px rounded custom icon (`create_icon.py`, pure Python, no deps), plus a 512 × 512 derivative
2. Creates a macOS `.iconset` at all required sizes using `sips`
3. Compiles to `.icns` with `iconutil`
4. Assembles the `.app` bundle with `Info.plist` and a launcher stub

To place the app in your Applications folder:

```bash
cp -r "Subnet Calculator.app" /Applications/
```

---

## File Layout

```
subnetCalculator/
├── subnet_calculator.py     # Main Python app (server + embedded UI)
├── create_icon.py           # Icon generator (pure Python, no deps)
├── icon_1024.png            # Temporary build artifact (generated, then removed by make_app.sh)
├── make_app.sh              # Builds Subnet Calculator.app (run once)
├── README.md                # This file
├── CODE_OVERVIEW.md         # Technical walkthrough of the code
└── Subnet Calculator.app/   # Double-clickable bundle (after make_app.sh)
    └── Contents/
        ├── Info.plist
        ├── MacOS/
        │   └── Subnet Calculator   # bash launcher stub
        └── Resources/
            ├── subnet_calculator.py
            └── SubnetCalc.icns
```

---

## Tool Reference

### IPv4 Subnet Calculator

Accepts any of these input formats:

```
192.168.1.100/24
10.0.0.1/255.255.0.0
172.16.5.50 255.255.240.0
203.0.113.42               ← treated as /32 host route
```

Results include:

| Field            | Description                                                                                   |
| ---------------- | --------------------------------------------------------------------------------------------- |
| Network Address  | First address in the subnet                                                                   |
| Broadcast        | Last address (N/A for /31 and /32)                                                            |
| First/Last Host  | Usable host range                                                                             |
| Usable Hosts     | Addresses minus network and broadcast                                                         |
| Subnet Mask      | Dotted-decimal mask                                                                           |
| Wildcard Mask    | Inverse mask (`255.255.255.255 − mask`)                                                       |
| CIDR Notation    | Compact prefix form                                                                           |
| IP Class         | A / B / C / D (multicast) / E (reserved)                                                      |
| IP Type          | Private / Public / Loopback / Link-local / etc.                                               |
| Supernet         | The /N−1 parent prefix                                                                        |
| Next Split       | How many /N+1 subnets this network divides into                                               |
| **Binary table** | All four addresses shown in binary with network bits (blue) and host bits (green) highlighted |

All values have a **Copy** button.

---

### Split Subnet

Two modes:

- **By number of subnets** — enter how many equal subnets you want; the tool finds the smallest prefix that provides at least that many.
- **By hosts per subnet** — enter the minimum hosts required per subnet; the tool finds the smallest prefix that satisfies that.

Output is capped at 512 rows for display; a note shows the total if more exist. A **Copy CSV** button exports the full table.

---

### VLSM

1. Enter the parent network (e.g. `192.168.10.0/24`)
2. Add rows with a label and the number of hosts needed
3. Click **Calculate VLSM**

Subnets are allocated largest-first from the parent, following VLSM best practice. Any remaining unallocated space is shown as chips at the bottom. The **Load example** button pre-fills a typical office layout.

---

### Supernet / Summarise

Enter one CIDR per line. The result is the minimum set of prefixes that covers all inputs without adding extra addresses (uses Python's `ipaddress.collapse_addresses`).

Example:

```
Input:   192.168.0.0/24
         192.168.1.0/24
         192.168.2.0/24
         192.168.3.0/24

Result:  192.168.0.0/22
```

---

### Range → CIDR

Enter a start IP and end IP. The tool returns the minimum list of CIDR blocks that exactly covers that range (uses `ipaddress.summarize_address_range`).

---

### Wildcard / ACL

Generates:

| Output             | Example                                               |
| ------------------ | ----------------------------------------------------- |
| Wildcard Mask      | `0.0.0.255`                                           |
| Cisco Standard ACL | `access-list 10 permit 192.168.1.0 0.0.0.255`         |
| Cisco Extended ACL | `access-list 100 permit ip 192.168.1.0 0.0.0.255 any` |
| Named Standard ACL | `ip access-list standard MY_ACL` …                    |
| Named Extended ACL | `ip access-list extended MY_ACL` …                    |
| OSPF network       | `network 192.168.1.0 0.0.0.255 area 0`                |
| EIGRP network      | `network 192.168.1.0 0.0.0.255`                       |
| BGP network        | `network 192.168.1.0 mask 255.255.255.0`              |
| Cisco prefix-list  | `ip prefix-list PL_NAME permit 192.168.1.0/24`        |
| JunOS route-filter | `route-filter 192.168.1.0/24 exact;`                  |
| NAT object-network | `object network OBJ_…` …                              |

---

### IPv6

Accepts compressed or expanded IPv6 addresses, with or without a prefix:

```
2001:db8::1/32
fe80::1/64
::1
fc00::/7
```

Output includes the compressed form, fully expanded (exploded) form, network address, total address count, and all applicable type flags.

Special types recognised:

- **GUA** — Global Unicast (`2000::/3`)
- **Link-local** (`fe80::/10`)
- **ULA / Private** (`fc00::/7`)
- **Loopback** (`::1`)
- **Multicast** (`ff00::/8`)
- **6to4** — shows the embedded IPv4 address
- **IPv4-mapped** — shows the mapped IPv4

---

## Keyboard Shortcuts

| Key            | Action                                                           |
| -------------- | ---------------------------------------------------------------- |
| **Enter**      | Submit the active input                                          |
| Auto-calculate | IPv4 and Wildcard tabs recalculate ~600 ms after you stop typing |
| **Ctrl-C**     | Stop the server (in terminal)                                    |

---

## Troubleshooting

### "Address already in use" at startup

The app kills any stale process on port 8766 automatically. If it still fails:

```bash
lsof -ti :8766 -sTCP:LISTEN | xargs kill
```

### App bundle shows "damaged" warning

Unsigned apps may be blocked by Gatekeeper. Right-click → **Open** → **Open**, or:

```bash
xattr -dr com.apple.quarantine "Subnet Calculator.app"
```

### Results not updating after editing the script

The script is loaded once at startup. Restart:

```bash
/usr/bin/python3 subnet_calculator.py
```

If using the `.app` bundle, rebuild it after any change:

```bash
bash make_app.sh
```

---

## Port Reference

| App                   | Port     |
| --------------------- | -------- |
| SuperPutty Mac        | 8765     |
| **Subnet Calculator** | **8766** |
