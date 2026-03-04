# Code Overview – Subnet Calculator Mac

A technical walkthrough of every component in the project.

---

## Architecture

```
Browser (localhost:8766)
    │
    │  HTTP GET/POST (JSON API + HTML page)
    ▼
subnet_calculator.py
    ├── Python ipaddress module  ← all subnet maths
    ├── Embedded HTML/CSS/JS     ← the UI served as one page
    └── http.server (stdlib)     ← local-only HTTP server
```

The application is a single-process Python program. It:

1. Binds to `127.0.0.1:8766` (loopback only — never accessible from the network)
2. Serves the complete UI as a single HTML response at `/`
3. Answers JSON API requests as the user interacts with the page
4. Shuts itself down when the browser tab is closed or the user presses Ctrl-C

There are no third-party packages, no build tools, and no persistent state.

---

## `subnet_calculator.py`

### Imports and constants

```python
import http.server, urllib.parse, webbrowser, threading
import subprocess, json, ipaddress, math, os, sys, signal, time

PORT = 8766
```

`ipaddress` (stdlib since Python 3.3) does all the heavy lifting — parsing, arithmetic, and enumeration of IPv4 and IPv6 addresses and networks.

---

### Calculation helpers

#### `_classify(addr)` → `str`

Returns a comma-separated string of address-type labels by testing the standard boolean properties on `IPv4Address` / `IPv6Address` objects:

```python
addr.is_private, addr.is_loopback, addr.is_link_local,
addr.is_multicast, addr.is_reserved, addr.is_unspecified
```

#### `_ipv4_class(addr)` → `str`

Determines the historical class (A/B/C/D/E) from the first octet:

| First octet | Class |
|---|---|
| 0 – 127 | A |
| 128 – 191 | B |
| 192 – 223 | C |
| 224 – 239 | D (Multicast) |
| 240 – 255 | E (Reserved) |

#### `_to_binary(ip_str)` → `str`

Converts a dotted-decimal string to dotted-binary:

```python
"192.168.1.0" → "11000000.10101000.00000001.00000000"
```

Each octet is formatted with `f"{int(p):08b}"`.

#### `_parse_ipv4_input(raw)` → `(IPv4Address, IPv4Network)`

Normalises several common input formats before handing off to `ipaddress`:

| Input format | Normalised to |
|---|---|
| `192.168.1.0/24` | unchanged |
| `192.168.1.0/255.255.255.0` | `IPv4Network` handles natively |
| `192.168.1.0 255.255.255.0` | joined with `/` |
| `192.168.1.1` (bare IP) | appends `/32` |

---

### API functions

Each function accepts plain Python values and returns a `dict` with either the results or `{"error": "message"}`.

#### `api_subnet(raw)` → `dict`

1. Calls `_parse_ipv4_input(raw)` to get `(ip, network)`
2. Handles the edge cases for `/31` (point-to-point, RFC 3021) and `/32` (host route)
3. Builds the supernet via `network.supernet(prefixes=1)`
4. Returns a comprehensive dict including all four binary strings

#### `api_split(net_cidr, mode, val)` → `dict`

Two modes:

- **`count`**: `bits = ceil(log2(val))`, then `new_prefix = parent.prefixlen + bits`
- **`hosts`**: `host_bits = ceil(log2(val + 2))`, then `new_prefix = 32 - host_bits`

Calls `network.subnets(new_prefix=new_prefix)` and caps display at 512 rows.

#### `api_vlsm(net_cidr, requirements)` → `dict`

Classic VLSM greedy algorithm:

1. Sort requirements largest → smallest (maximises packing efficiency)
2. Maintain a list of `available` free blocks, initially `[parent]`
3. For each requirement:
   - Compute the needed prefix length: `needed_pf = 32 - ceil(log2(hosts + 2))`
   - Find the first available block with `prefixlen ≤ needed_pf`
   - Split it to `needed_pf` with `block.subnets(new_prefix=needed_pf)`
   - Add all leftover sub-blocks back to `available` using `block.address_exclude(sub)`
   - Sort `available` by `(prefixlen, network_address)` to prefer smaller blocks first

The leftover list (remaining unallocated space) is returned alongside the allocations.

#### `api_supernet(networks)` → `dict`

Delegates entirely to `ipaddress.collapse_addresses(parsed)`, which implements RFC 4632 supernet summarisation.

#### `api_range(start, end)` → `dict`

Delegates to `ipaddress.summarize_address_range(start, end)`, which returns the minimum list of CIDR blocks covering the range.

#### `api_ipv6(raw)` → `dict`

Parses with `IPv6Network` / `IPv6Address`. Notable properties:

- `ip.compressed` — shortest valid form (e.g. `2001:db8::1`)
- `ip.exploded` — fully padded 8-group form
- `ip.ipv4_mapped` — not-None for `::ffff:x.x.x.x` addresses
- `ip.sixtofour` — not-None for `2002::/16` addresses

#### `api_wildcard(raw)` → `dict`

Computes `network.hostmask` (Python's name for the wildcard mask), then builds a set of common network-device configuration strings using f-strings.

---

### Embedded HTML (`HTML = r"""..."""`)

The entire front-end is a single multi-line raw string embedded in the Python source. When the server handles a `GET /` request it encodes this string as UTF-8 and sends it directly — no template engine, no files on disk.

The string contains three sections:

#### CSS

Follows the **Catppuccin Mocha** colour palette (matching SuperPutty Mac):

| Variable | Hex | Use |
|---|---|---|
| `#1e1e2e` | Dark navy | Page background |
| `#181825` | Darker navy | Toolbar, cards |
| `#313244` | Surface | Inputs, table headers |
| `#45475a` | Surface2 | Borders |
| `#89b4fa` | Blue | Primary accent, network bits, CIDR values |
| `#a6e3a1` | Green | Host bits, host counts |
| `#fab387` | Peach | Wildcard masks |
| `#cba6f7` | Purple | Prefix lengths, IPv6 |
| `#f38ba8` | Red | Error messages |
| `#cdd6f4` | Text | Body text |

Key layout patterns:
- `display: flex; flex-direction: column; height: 100vh; overflow: hidden` — the whole page fills the viewport with no scrollbar on the outer body
- `#content { flex: 1; overflow-y: auto }` — only the content area scrolls
- `.tab-panel { display: none }` / `.tab-panel.active { display: block }` — tab visibility controlled by JS class toggle

#### Binary representation

The IPv4 binary display is rendered in JavaScript using DOM manipulation rather than innerHTML, so individual bits can be styled independently:

```javascript
for (const ch of bin) {
  if (ch === '.') {
    span.className = 'sep';    // grey dot
  } else {
    span.className = bitPos < prefixLen ? 'nb' : 'hb';
    // nb = blue (network bits), hb = green (host bits)
    bitPos++;
  }
}
```

#### JavaScript architecture

All UI state lives in the browser — the server is stateless. The JS is divided into sections per tab:

| Section | Key functions |
|---|---|
| Tab switching | `document.querySelectorAll('.tab-btn')` event listeners |
| IPv4 | `calcIPv4()`, `renderIPv4(d)`, debounced input listener |
| Split | `calcSplit()`, `renderSplitTable(d)`, `copySplitTable()` |
| VLSM | `addVLSMRow()`, `removeVLSMRow()`, `calcVLSM()`, `renderVLSMTable(d)` |
| Supernet | `calcSupernet()` |
| Range | `calcRange()` — calls `/api/range` then `/api/subnet` for each CIDR |
| Wildcard | `calcWildcard()`, debounced input listener |
| IPv6 | `calcIPv6()` |
| Reference | `buildRefTable()` — generates the /0–/32 mask table at startup |

Auto-calculate: the IPv4 and Wildcard tabs fire `setTimeout(..., 600)` on every keystroke and cancel the previous timer, so the calculation fires 600 ms after the user stops typing.

---

### HTTP server

#### `free_port(port)`

Runs `lsof -ti :{port} -sTCP:LISTEN` to get the PID of anything already listening, then sends `SIGTERM`. This means double-clicking the `.app` always works even if a previous instance is still running.

#### `_Server` (subclass of `HTTPServer`)

Sets `allow_reuse_address = True` so the OS immediately frees the port on restart.

#### `make_handler(server_ref)` → `Handler` class

A closure that captures `server_ref` and `html_bytes`. Returns a `Handler` class (subclass of `BaseHTTPRequestHandler`) with all routes implemented.

**Heartbeat / watchdog pattern** (same as SuperPutty Mac):

```
Browser JS: setInterval(() => fetch('/ping'), 5000)
Server:     last_ping[0] = time.time()   on each /ping

Watchdog thread: every 5 s, checks if time.time() - last_ping[0] > 15 s
                 → if so, calls server.shutdown() in a daemon thread
```

This ensures the server dies when the browser tab is closed (which fires `navigator.sendBeacon('/quit')` → sets `last_ping[0] = 0` → watchdog triggers within 5 s).

**Route table:**

| Method | Path | Handler |
|---|---|---|
| GET | `/` | Serve HTML |
| GET | `/ping` | Heartbeat — update `last_ping` |
| GET | `/quit` | Immediate shutdown |
| POST | `/quit` | Shutdown (from `sendBeacon`) |
| GET | `/api/subnet` | `api_subnet(q)` |
| GET | `/api/split` | `api_split(net, mode, val)` |
| GET | `/api/range` | `api_range(start, end)` |
| GET | `/api/ipv6` | `api_ipv6(q)` |
| GET | `/api/wildcard` | `api_wildcard(q)` |
| POST | `/api/vlsm` | `api_vlsm(net, reqs)` — JSON body |
| POST | `/api/supernet` | `api_supernet(nets)` — JSON body |

---

## `create_icon.py`

A pure-Python 512 × 512 PNG generator. No Pillow or other image libraries.

### PNG encoding

PNG is built from three chunks:

```
IHDR – width, height, bit depth, colour type (2=RGB), compression, filter, interlace
IDAT – zlib-compressed scanlines, each prefixed with a filter byte (0x00 = None)
IEND – empty, marks end of file
```

Each chunk is: `[4-byte length][4-byte name][data][4-byte CRC32 of name+data]`

```python
def _png_chunk(name, data):
    crc = zlib.crc32(name + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)
```

### Drawing primitives

#### `draw_circle(canvas, cx, cy, radius, color, W, H, inner_r=0)`

Iterates over the bounding box, computes the Euclidean distance from each pixel to the centre, and applies:

- `d < radius − 1`: fully opaque fill
- `radius − 1 ≤ d < radius + 1`: anti-aliased edge (alpha = `(radius + 1 − d) / 2`)
- Optional hollow: pixels inside `inner_r` are cleared similarly

#### `draw_line(canvas, x1, y1, x2, y2, color, thickness, W, H)`

Sweeps a series of small discs (radius = `thickness/2`) along the line path at integer step intervals. Anti-aliased at each disc edge.

#### `_blend(canvas, x, y, color, alpha, W, H)`

Standard alpha-composite over the existing pixel:

```python
result = bg * (1 − alpha) + color * alpha
```

### Icon design

- **Background**: dark vertical gradient from `#181825` to `#11111b`
- **Connection lines**: `SURF2` (#45475a), thickness 9 px, hub → each node
- **Subnet nodes**: positioned at 29.5%/70.5% of the image on each axis
  - Outer glow (22% opacity, radius × 1.25)
  - Outer filled circle (full colour, radius × 1.0)
  - Inner darker fill (deeper shade, radius × 0.64)
- **Hub**: `SURF` outer ring, `SKY` (#89dceb) inner fill
- **CIDR slash**: a thick diagonal `DARK` line through the hub at 55°

---

## `make_app.sh`

A Bash script that builds the `.app` bundle.

### Steps

1. **Run `create_icon.py`** — produces `icon_512.png`
2. **Create `.iconset`** with `sips` — resizes the 512-px PNG to all 10 required sizes (`16`, `32`, `64`, `128`, `256`, `512` px and their `@2x` equivalents)
3. **Compile `.icns`** with `iconutil -c icns`
4. **Build bundle structure**: `Contents/MacOS/` and `Contents/Resources/`
5. **Copy sources** into `Resources/`
6. **Write `Info.plist`** with:
   - `CFBundleIconFile` → `SubnetCalc` (points to the `.icns`)
   - `LSUIElement` → `true` (no Dock icon — browser is the UI)
7. **Write launcher stub** (`Contents/MacOS/Subnet Calculator`):
   ```bash
   #!/bin/bash
   RESOURCES="$(dirname "$0")/../Resources"
   exec /usr/bin/python3 "$RESOURCES/subnet_calculator.py"
   ```
8. **Clean up** temporary `.iconset` and intermediate PNG

### `LSUIElement`

Setting this to `true` in `Info.plist` means the app does not appear in the Dock or the Cmd-Tab switcher. Since the entire UI is in a browser window, this gives a cleaner experience — the browser is front and centre, not a hidden background process.

---

## Security notes

- The server binds to `127.0.0.1` only — it is never reachable from other hosts on the network.
- No user data is written to disk.
- No external network requests are made by either the Python server or the JavaScript.
- The `ipaddress` module is used for all address arithmetic; no string parsing with `eval` or similar.
