#!/usr/bin/python3
"""
Subnet Calculator Mac  –  Web UI edition

Serves a local browser-based subnet calculator with seven tools:
  • IPv4 Subnet    – full breakdown of any IP/prefix
  • Split Subnet   – divide a network into equal-size subnets
  • VLSM           – variable-length subnet mask allocation
  • Supernet       – collapse/summarise multiple prefixes
  • Range → CIDR   – convert an IP range to covering CIDRs
  • IPv6           – IPv6 address and prefix information
  • Reference      – subnet-mask cheat-sheet and special ranges

No third-party packages – pure Python 3 stdlib.
Port 8766 (different from SuperPutty Mac on 8765).
"""

import http.server
import urllib.parse
import threading
import subprocess
import json
import ipaddress
import math
import os
import sys
import signal
import time

PORT = 8766

# ── Calculation helpers ─────────────────────────────────────────────────────

def _classify(addr):
    """Return a comma-separated string of address type labels."""
    tags = []
    if addr.is_loopback:      tags.append("Loopback")
    if addr.is_link_local:    tags.append("Link-local")
    if addr.is_multicast:     tags.append("Multicast")
    if addr.is_reserved:      tags.append("Reserved")
    if addr.is_unspecified:   tags.append("Unspecified")
    if not tags:
        tags.append("Private" if addr.is_private else "Public / Global")
    return ", ".join(tags)


def _ipv4_class(addr):
    first = int(str(addr).split(".")[0])
    if first < 128:   return "A"
    if first < 192:   return "B"
    if first < 224:   return "C"
    if first < 240:   return "D – Multicast"
    return "E – Reserved"


def _to_binary(ip_str):
    """Dotted-decimal → dotted-binary, e.g. '11000000.10101000.00000001.00000000'"""
    return ".".join(f"{int(p):08b}" for p in ip_str.split("."))


def _parse_ipv4_input(raw):
    """
    Accept several common notations:
      192.168.1.1/24
      192.168.1.1/255.255.255.0
      192.168.1.1 255.255.255.0
      192.168.1.1          (treated as /32)
    Returns (IPv4Address, IPv4Network) or raises ValueError.
    """
    s = raw.strip()
    parts = s.split()
    if len(parts) == 2:
        # "IP MASK" → "IP/MASK"
        s = f"{parts[0]}/{parts[1]}"
    if "/" not in s:
        s += "/32"

    ip_str, prefix = s.split("/", 1)
    ip_obj = ipaddress.IPv4Address(ip_str)
    network = ipaddress.IPv4Network(s, strict=False)
    return ip_obj, network


# ── API functions ───────────────────────────────────────────────────────────

def api_subnet(raw):
    try:
        ip, net = _parse_ipv4_input(raw)
    except Exception as e:
        return {"error": str(e)}

    hosts = list(net.hosts())
    plen  = net.prefixlen

    if plen == 32:
        first_host = last_host = str(ip)
        num_hosts  = 1
        broadcast  = str(ip)
    elif plen == 31:
        addrs      = list(net)
        first_host = str(addrs[0])
        last_host  = str(addrs[1])
        num_hosts  = 2
        broadcast  = "N/A (point-to-point /31)"
    else:
        first_host = str(hosts[0])  if hosts else str(net.network_address)
        last_host  = str(hosts[-1]) if hosts else str(net.broadcast_address)
        num_hosts  = net.num_addresses - 2
        broadcast  = str(net.broadcast_address)

    # Supernet (one bit wider) and next-split info
    try:
        supernet_cidr = str(net.supernet(prefixes=1))
    except Exception:
        supernet_cidr = "N/A"
    try:
        sub_count = 2
        sub_plen  = plen + 1
        sub_example = list(net.subnets(prefixlen_diff=1))
        split_info = f"2 × /{sub_plen}  ({net.num_addresses // 2} addresses each)"
    except Exception:
        split_info = "N/A"

    return {
        "ip":             str(ip),
        "network":        str(net.network_address),
        "broadcast":      broadcast,
        "first_host":     first_host,
        "last_host":      last_host,
        "num_hosts":      f"{num_hosts:,}",
        "num_addresses":  f"{net.num_addresses:,}",
        "prefix_length":  plen,
        "subnet_mask":    str(net.netmask),
        "wildcard_mask":  str(net.hostmask),
        "cidr":           str(net),
        "ip_class":       _ipv4_class(ip),
        "ip_type":        _classify(ip),
        "is_private":     ip.is_private,
        "supernet":       supernet_cidr,
        "split_info":     split_info,
        # Binary strings
        "ip_bin":         _to_binary(str(ip)),
        "mask_bin":       _to_binary(str(net.netmask)),
        "net_bin":        _to_binary(str(net.network_address)),
        "bcast_bin":      _to_binary(str(net.broadcast_address)),
    }


def api_split(net_cidr, mode, val):
    """
    Split net_cidr into equal subnets.
    mode='count'  → val = number of subnets wanted
    mode='hosts'  → val = minimum usable hosts per subnet
    """
    try:
        parent = ipaddress.IPv4Network(net_cidr, strict=False)
        val    = int(val)
        if val < 1:
            return {"error": "Value must be at least 1"}
    except Exception as e:
        return {"error": str(e)}

    try:
        if mode == "count":
            bits   = math.ceil(math.log2(max(val, 1)))
            new_pf = parent.prefixlen + bits
        else:  # hosts
            host_bits = math.ceil(math.log2(val + 2))
            new_pf    = 32 - host_bits

        if new_pf > 30:
            return {"error": f"/{new_pf} subnets are too small (minimum usable is /30)"}
        if new_pf <= parent.prefixlen:
            return {"error": "Requested subnet size is larger than the parent network"}

        all_subs  = list(parent.subnets(new_prefix=new_pf))
        total     = len(all_subs)
        show_subs = all_subs[:512]

        rows = []
        for s in show_subs:
            h = list(s.hosts())
            rows.append({
                "cidr":      str(s),
                "network":   str(s.network_address),
                "broadcast": str(s.broadcast_address),
                "first":     str(h[0])  if h else str(s.network_address),
                "last":      str(h[-1]) if h else str(s.broadcast_address),
                "hosts":     f"{s.num_addresses - 2:,}" if s.prefixlen < 31 else str(s.num_addresses),
                "mask":      str(s.netmask),
            })
        return {"subnets": rows, "total": total, "shown": len(rows), "prefix": new_pf}
    except Exception as e:
        return {"error": str(e)}


def api_vlsm(net_cidr, requirements):
    """
    VLSM allocation.
    requirements: list of {"name": str, "hosts": int}
    Allocates from largest to smallest requirement.
    """
    try:
        parent = ipaddress.IPv4Network(net_cidr, strict=False)
    except Exception as e:
        return {"error": f"Invalid parent network: {e}"}

    reqs = []
    for r in requirements:
        try:
            reqs.append((str(r["name"]), int(r["hosts"])))
        except Exception:
            return {"error": f"Bad requirement entry: {r}"}

    if not reqs:
        return {"error": "No requirements provided"}

    # Sort largest → smallest
    reqs.sort(key=lambda x: x[1], reverse=True)

    available   = [parent]
    allocations = []

    for name, hosts_needed in reqs:
        if hosts_needed < 1:
            return {"error": f"'{name}': hosts must be ≥ 1"}
        host_bits = math.ceil(math.log2(hosts_needed + 2))
        need_pf   = 32 - host_bits
        if need_pf < 0:
            return {"error": f"'{name}': too many hosts requested ({hosts_needed})"}

        # Find the smallest available block that fits
        chosen = None
        for i, blk in enumerate(available):
            if blk.prefixlen <= need_pf:
                # Split blk down to need_pf
                sub = next(blk.subnets(new_prefix=need_pf))
                # Put leftover back
                leftovers = list(blk.address_exclude(sub))
                available.pop(i)
                available.extend(leftovers)
                available.sort(key=lambda x: (x.prefixlen, x.network_address))
                chosen = sub
                break

        if chosen is None:
            return {"error": f"Not enough space for '{name}' (/{need_pf} = {hosts_needed} hosts)"}

        h = list(chosen.hosts())
        allocations.append({
            "name":        name,
            "hosts_needed": hosts_needed,
            "cidr":        str(chosen),
            "network":     str(chosen.network_address),
            "broadcast":   str(chosen.broadcast_address),
            "first":       str(h[0])  if h else str(chosen.network_address),
            "last":        str(h[-1]) if h else str(chosen.broadcast_address),
            "usable":      chosen.num_addresses - 2,
            "mask":        str(chosen.netmask),
        })

    remaining = [str(b) for b in available]
    return {"allocations": allocations, "remaining": remaining}


def api_supernet(networks):
    try:
        parsed    = [ipaddress.IPv4Network(n.strip(), strict=False) for n in networks if n.strip()]
        collapsed = list(ipaddress.collapse_addresses(parsed))
        return {"collapsed": [str(c) for c in collapsed]}
    except Exception as e:
        return {"error": str(e)}


def api_range(start, end):
    try:
        s = ipaddress.IPv4Address(start.strip())
        e = ipaddress.IPv4Address(end.strip())
        if int(e) < int(s):
            return {"error": "End address must be ≥ start address"}
        cidrs = list(ipaddress.summarize_address_range(s, e))
        return {"cidrs": [str(c) for c in cidrs]}
    except Exception as ex:
        return {"error": str(ex)}


def api_ipv6(raw):
    try:
        s = raw.strip()
        if "/" in s:
            net    = ipaddress.IPv6Network(s, strict=False)
            ip_obj = ipaddress.IPv6Address(s.split("/")[0])
        else:
            ip_obj = ipaddress.IPv6Address(s)
            net    = ipaddress.IPv6Network(s + "/128", strict=False)

        ipv4m = ip_obj.ipv4_mapped
        s6t4  = ip_obj.sixtofour

        return {
            "address":      str(ip_obj),
            "compressed":   ip_obj.compressed,
            "expanded":     ip_obj.exploded,
            "network":      str(net.network_address),
            "prefix_length": net.prefixlen,
            "num_addresses": str(net.num_addresses),
            "type":         _classify(ip_obj),
            "is_private":   ip_obj.is_private,
            "is_global":    ip_obj.is_global,
            "is_link_local": ip_obj.is_link_local,
            "is_loopback":  ip_obj.is_loopback,
            "is_multicast": ip_obj.is_multicast,
            "ipv4_mapped":  str(ipv4m) if ipv4m else None,
            "sixtofour":    str(s6t4)  if s6t4  else None,
        }
    except Exception as e:
        return {"error": str(e)}


def api_wildcard(raw):
    try:
        _, net = _parse_ipv4_input(raw)
    except Exception as e:
        return {"error": str(e)}

    n    = str(net.network_address)
    wild = str(net.hostmask)
    mask = str(net.netmask)
    cidr = str(net)
    pf   = net.prefixlen

    return {
        "network":      n,
        "mask":         mask,
        "wildcard":     wild,
        "cidr":         cidr,
        "prefix":       pf,
        # Cisco IOS
        "cisco_std":    f"access-list 10 permit {n} {wild}",
        "cisco_ext":    f"access-list 100 permit ip {n} {wild} any",
        "named_std":    f"ip access-list standard MY_ACL\n permit {n} {wild}",
        "named_ext":    f"ip access-list extended MY_ACL\n permit ip {n} {wild} any",
        # Routing protocols
        "ospf":         f"network {n} {wild} area 0",
        "eigrp":        f"network {n} {wild}",
        "bgp_net":      f"network {n} mask {mask}",
        # Prefix lists
        "prefix_list":  f"ip prefix-list PL_NAME permit {cidr}",
        # Juniper (JunOS style)
        "juniper":      f"route-filter {cidr} exact;",
        # Object-group
        "obj_network":  f"object network OBJ_{n.replace('.','_')}\n subnet {n} {mask}",
    }


# ── Embedded HTML ────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Subnet Calculator</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
  font-size: 14px;
  background: #1e1e2e;
  color: #cdd6f4;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Toolbar ── */
#toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 16px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
}
#toolbar .logo { font-size: 20px; line-height: 1; }
#toolbar h1 { font-size: 15px; font-weight: 700; color: #89b4fa; }
#toolbar .subtitle { font-size: 12px; color: #6c7086; margin-left: 4px; }

/* ── Tabs ── */
#tab-nav {
  display: flex;
  gap: 3px;
  padding: 6px 12px;
  background: #181825;
  border-bottom: 1px solid #313244;
  flex-shrink: 0;
  overflow-x: auto;
}
#tab-nav::-webkit-scrollbar { height: 0; }
.tab-btn {
  padding: 5px 16px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: #6c7086;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.12s, color 0.12s;
}
.tab-btn:hover { background: #313244; color: #cdd6f4; }
.tab-btn.active { background: #313244; color: #89b4fa; border-color: #45475a; font-weight: 600; }

/* ── Content ── */
#content { flex: 1; overflow-y: auto; padding: 18px 22px 24px; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }

/* ── Panel titles ── */
.panel-title { font-size: 15px; font-weight: 700; color: #cdd6f4; margin-bottom: 3px; }
.panel-sub { font-size: 12px; color: #6c7086; margin-bottom: 14px; }

/* ── Inputs ── */
.input-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.main-input {
  flex: 1; min-width: 260px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid #45475a;
  background: #313244;
  color: #cdd6f4;
  font-family: "Menlo", "SF Mono", "Courier New", monospace;
  font-size: 14px;
}
.main-input:focus { border-color: #89b4fa; outline: none; }
.main-input::placeholder { color: #6c7086; }
.main-textarea {
  width: 100%; min-height: 90px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid #45475a;
  background: #313244;
  color: #cdd6f4;
  font-family: "Menlo", "SF Mono", "Courier New", monospace;
  font-size: 13px;
  resize: vertical;
  margin-bottom: 8px;
}
.main-textarea:focus { border-color: #89b4fa; outline: none; }
select.main-input { cursor: pointer; }

/* ── Buttons ── */
.btn-primary {
  padding: 8px 20px; border-radius: 8px; border: none;
  background: #89b4fa; color: #1e1e2e;
  font-size: 13px; font-weight: 700; cursor: pointer;
}
.btn-primary:hover { background: #74a8f8; }
.btn-secondary {
  padding: 8px 14px; border-radius: 8px;
  border: 1px solid #45475a; background: #313244;
  color: #cdd6f4; font-size: 13px; cursor: pointer;
}
.btn-secondary:hover { background: #45475a; }
.btn-danger {
  padding: 5px 10px; border-radius: 6px;
  border: 1px solid #f38ba840; background: transparent;
  color: #f38ba8; font-size: 12px; cursor: pointer;
}
.btn-danger:hover { background: #f38ba820; }

/* ── Example chips ── */
.chips { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 14px; }
.chips-label { font-size: 11px; color: #6c7086; }
.chip {
  padding: 3px 10px; border-radius: 20px;
  border: 1px solid #45475a; background: #181825;
  color: #6c7086; font-size: 12px;
  font-family: "Menlo", "SF Mono", monospace; cursor: pointer;
}
.chip:hover { border-color: #89b4fa; color: #89b4fa; }

/* ── Result cards ── */
.card {
  background: #181825; border: 1px solid #313244;
  border-radius: 10px; padding: 14px 18px; margin-bottom: 12px;
}
.card-title {
  font-size: 11px; text-transform: uppercase;
  letter-spacing: 0.08em; color: #6c7086; margin-bottom: 12px; font-weight: 600;
}
.result-grid {
  display: grid;
  grid-template-columns: 170px 1fr auto;
  gap: 9px 12px;
  align-items: center;
}
.rl { color: #6c7086; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }
.rv {
  font-family: "Menlo", "SF Mono", "Courier New", monospace;
  font-size: 13px; color: #cdd6f4;
}
.rv.hi { color: #89b4fa; font-weight: 600; }
.rv.green { color: #a6e3a1; }
.rv.peach { color: #fab387; }
.rv.purple { color: #cba6f7; }
.copy-btn {
  padding: 2px 7px; border-radius: 4px;
  border: 1px solid #313244; background: transparent;
  color: #6c7086; font-size: 11px; cursor: pointer;
}
.copy-btn:hover { border-color: #45475a; color: #cdd6f4; }

/* ── Badge ── */
.badge {
  display: inline-block; padding: 2px 8px;
  border-radius: 4px; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.04em; margin-left: 6px;
}
.badge-priv { background: #fab38722; color: #fab387; border: 1px solid #fab38740; }
.badge-pub  { background: #a6e3a122; color: #a6e3a1; border: 1px solid #a6e3a140; }
.badge-a    { background: #89b4fa22; color: #89b4fa; border: 1px solid #89b4fa40; }
.badge-b    { background: #cba6f722; color: #cba6f7; border: 1px solid #cba6f740; }
.badge-c    { background: #a6e3a122; color: #a6e3a1; border: 1px solid #a6e3a140; }
.badge-d    { background: #f9e2af22; color: #f9e2af; border: 1px solid #f9e2af40; }
.badge-e    { background: #f38ba822; color: #f38ba8; border: 1px solid #f38ba840; }

/* ── Binary display ── */
.bin-row {
  display: grid;
  grid-template-columns: 140px 1fr 150px;
  gap: 4px 10px; align-items: center;
  padding: 5px 0;
  border-bottom: 1px solid #11111b;
}
.bin-row:last-child { border-bottom: none; }
.bin-lbl { font-size: 12px; color: #6c7086; }
.bin-val { font-family: "Menlo", "SF Mono", monospace; font-size: 12px; letter-spacing: 0.5px; }
.nb { color: #89b4fa; }   /* network bits */
.hb { color: #a6e3a1; }   /* host bits */
.sep { color: #45475a; }  /* dots */
.bin-dec { font-family: "Menlo", "SF Mono", monospace; font-size: 12px; color: #6c7086; text-align: right; }

/* ── Tables ── */
.tbl-wrap { background: #181825; border: 1px solid #313244; border-radius: 10px; overflow: hidden; margin-top: 10px; }
.tbl-hdr { display: flex; justify-content: space-between; align-items: center; padding: 10px 16px; border-bottom: 1px solid #313244; }
.tbl-hdr-title { font-size: 13px; font-weight: 600; color: #cdd6f4; }
.tbl-hdr-info { font-size: 12px; color: #6c7086; }
.rtable { width: 100%; border-collapse: collapse; }
.rtable th {
  text-align: left; padding: 8px 12px;
  background: #313244; color: #6c7086;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em;
  font-family: -apple-system, sans-serif; font-weight: 600;
  border-bottom: 1px solid #45475a;
}
.rtable td {
  padding: 7px 12px; border-bottom: 1px solid #11111b;
  font-family: "Menlo", "SF Mono", monospace; font-size: 12px;
}
.rtable tbody tr:hover td { background: #2a2a3d; }
.rtable .tc { color: #89b4fa; }  /* cidr */
.rtable .th { color: #a6e3a1; }  /* hosts */
.rtable .tn { color: #cba6f7; }  /* name */

/* ── VLSM req builder ── */
.vlsm-table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
.vlsm-table td { padding: 4px 6px; }
.vlsm-table .num-cell { width: 40px; font-size: 12px; color: #6c7086; text-align: center; }
.vlsm-input {
  width: 100%; padding: 6px 8px;
  border-radius: 6px; border: 1px solid #45475a;
  background: #313244; color: #cdd6f4;
  font-size: 13px; font-family: -apple-system, sans-serif;
}
.vlsm-input:focus { border-color: #89b4fa; outline: none; }

/* ── Remaining chips ── */
.remaining-list { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.rem-chip {
  display: inline-block; padding: 4px 12px;
  border-radius: 6px; background: #313244;
  border: 1px solid #45475a;
  font-family: "Menlo", "SF Mono", monospace; font-size: 12px; color: #fab387;
}

/* ── ACL block ── */
.acl-block {
  background: #11111b; border: 1px solid #313244; border-radius: 8px;
  padding: 12px 16px;
  font-family: "Menlo", "SF Mono", monospace; font-size: 13px;
  color: #a6e3a1; white-space: pre; line-height: 1.7;
  overflow-x: auto;
}

/* ── Error / Info notices ── */
.err-box {
  background: #f38ba822; border: 1px solid #f38ba8;
  border-radius: 8px; padding: 10px 14px;
  color: #f38ba8; font-size: 13px; margin-top: 8px;
}
.info-box {
  background: #89b4fa12; border: 1px solid #89b4fa30;
  border-radius: 8px; padding: 10px 14px;
  color: #89b4fa; font-size: 12px; margin-bottom: 12px;
}

/* ── Reference tab ── */
.ref-section { margin-bottom: 22px; }
.ref-section h3 { font-size: 13px; font-weight: 700; color: #cba6f7; margin-bottom: 8px; }
.ref-notice {
  background: #cba6f712; border: 1px solid #cba6f730;
  border-radius: 6px; padding: 8px 12px; margin-bottom: 6px;
  font-size: 12px; color: #cba6f7;
}

/* ── IPv6 expanded ── */
.addr-expanded {
  font-family: "Menlo", "SF Mono", monospace;
  font-size: 14px; color: #cba6f7; word-break: break-all;
}

/* ── Status bar ── */
#status-bar {
  padding: 4px 16px; background: #181825;
  border-top: 1px solid #313244;
  font-size: 12px; color: #6c7086; flex-shrink: 0;
}

/* ── Divider ── */
.divider { height: 1px; background: #313244; margin: 12px 0; }

/* ── Two-col layout for Reference ── */
.ref-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 700px) { .ref-cols { grid-template-columns: 1fr; } }

/* ── Mode toggle ── */
.mode-toggle { display: flex; gap: 0; border-radius: 8px; overflow: hidden; border: 1px solid #45475a; margin-bottom: 14px; }
.mode-btn { flex: 1; padding: 6px 14px; border: none; background: #313244; color: #6c7086; font-size: 13px; cursor: pointer; }
.mode-btn.active { background: #45475a; color: #89b4fa; font-weight: 600; }

/* ── Range result list ── */
.cidr-pill {
  display: inline-block; padding: 4px 14px; margin: 4px;
  border-radius: 6px; background: #313244; border: 1px solid #45475a;
  font-family: "Menlo", "SF Mono", monospace; font-size: 13px; color: #89b4fa;
}
</style>
</head>
<body>

<div id="toolbar">
  <span class="logo">🌐</span>
  <h1>Subnet Calculator</h1>
  <span class="subtitle">Network Professional Tools</span>
</div>

<div id="tab-nav">
  <button class="tab-btn active" data-tab="ipv4">IPv4 Subnet</button>
  <button class="tab-btn" data-tab="split">Split Subnet</button>
  <button class="tab-btn" data-tab="vlsm">VLSM</button>
  <button class="tab-btn" data-tab="supernet">Supernet</button>
  <button class="tab-btn" data-tab="range">Range → CIDR</button>
  <button class="tab-btn" data-tab="wildcard">Wildcard / ACL</button>
  <button class="tab-btn" data-tab="ipv6">IPv6</button>
  <button class="tab-btn" data-tab="reference">Reference</button>
</div>

<div id="content">

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 1 – IPv4 Subnet
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel active" id="tab-ipv4">
  <div class="panel-title">IPv4 Subnet Calculator</div>
  <div class="panel-sub">Enter an IP with CIDR, dotted mask, or just an IP address</div>

  <div class="input-row">
    <input class="main-input" id="ipv4-in" type="text"
           placeholder="192.168.1.100/24   or   10.0.0.1 255.255.0.0   or   172.16.5.20/255.255.240.0"
           autofocus autocomplete="off" spellcheck="false">
    <button class="btn-primary" onclick="calcIPv4()">Calculate</button>
    <button class="btn-secondary" onclick="clearIPv4()">Clear</button>
  </div>

  <div class="chips">
    <span class="chips-label">Examples:</span>
    <span class="chip" onclick="quickIPv4('192.168.1.100/24')">192.168.1.100/24</span>
    <span class="chip" onclick="quickIPv4('10.0.0.1/8')">10.0.0.1/8</span>
    <span class="chip" onclick="quickIPv4('172.16.5.50/20')">172.16.5.50/20</span>
    <span class="chip" onclick="quickIPv4('192.168.10.1/30')">192.168.10.1/30</span>
    <span class="chip" onclick="quickIPv4('203.0.113.42/27')">203.0.113.42/27</span>
    <span class="chip" onclick="quickIPv4('10.10.0.0/12')">10.10.0.0/12</span>
  </div>

  <div id="ipv4-err" class="err-box" style="display:none"></div>
  <div id="ipv4-results" style="display:none">

    <!-- Network Info -->
    <div class="card">
      <div class="card-title">Network Information</div>
      <div class="result-grid" id="ipv4-grid"></div>
    </div>

    <!-- Binary Representation -->
    <div class="card">
      <div class="card-title">Binary Representation
        <span style="font-size:11px;color:#6c7086;margin-left:8px;text-transform:none;letter-spacing:0">
          <span class="nb">■</span> Network bits &nbsp;
          <span class="hb">■</span> Host bits
        </span>
      </div>
      <div id="ipv4-binary"></div>
    </div>

    <!-- Network Planning -->
    <div class="card">
      <div class="card-title">Network Planning</div>
      <div class="result-grid" id="ipv4-planning"></div>
    </div>

  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 2 – Split Subnet
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-split">
  <div class="panel-title">Split Subnet</div>
  <div class="panel-sub">Divide a network into equal-sized subnets</div>

  <div class="input-row">
    <input class="main-input" id="split-net" type="text"
           placeholder="Parent network, e.g. 192.168.0.0/16" autocomplete="off" spellcheck="false">
  </div>

  <div class="mode-toggle">
    <button class="mode-btn active" id="split-mode-count" onclick="setSplitMode('count')">By number of subnets</button>
    <button class="mode-btn" id="split-mode-hosts" onclick="setSplitMode('hosts')">By hosts per subnet</button>
  </div>

  <div class="input-row">
    <label id="split-val-label" style="font-size:13px;color:#6c7086;white-space:nowrap">Number of subnets:</label>
    <input class="main-input" id="split-val" type="number" min="1" placeholder="e.g. 4" style="max-width:180px">
    <button class="btn-primary" onclick="calcSplit()">Calculate</button>
    <button class="btn-secondary" onclick="clearSplit()">Clear</button>
  </div>

  <div class="chips">
    <span class="chips-label">Examples:</span>
    <span class="chip" onclick="quickSplit('192.168.0.0/24','count','4')">192.168.0.0/24 → 4 subnets</span>
    <span class="chip" onclick="quickSplit('10.0.0.0/16','hosts','50')">10.0.0.0/16 → 50 hosts each</span>
    <span class="chip" onclick="quickSplit('172.16.0.0/20','count','8')">172.16.0.0/20 → 8 subnets</span>
  </div>

  <div id="split-err" class="err-box" style="display:none"></div>
  <div id="split-results" style="display:none">
    <div class="tbl-wrap">
      <div class="tbl-hdr">
        <span class="tbl-hdr-title" id="split-tbl-title">Subnets</span>
        <div style="display:flex;gap:8px;align-items:center">
          <span class="tbl-hdr-info" id="split-count"></span>
          <button class="btn-secondary" style="font-size:12px;padding:4px 10px" onclick="copySplitTable()">Copy CSV</button>
        </div>
      </div>
      <div style="overflow-x:auto;max-height:420px;overflow-y:auto">
        <table class="rtable" id="split-table">
          <thead>
            <tr>
              <th>#</th><th>CIDR</th><th>Network</th><th>Broadcast</th>
              <th>First Host</th><th>Last Host</th><th>Usable Hosts</th><th>Mask</th>
            </tr>
          </thead>
          <tbody id="split-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 3 – VLSM
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-vlsm">
  <div class="panel-title">VLSM – Variable-Length Subnet Masking</div>
  <div class="panel-sub">Efficiently allocate subnets of different sizes from a parent network</div>

  <div class="input-row">
    <input class="main-input" id="vlsm-net" type="text"
           placeholder="Parent network, e.g. 192.168.10.0/24" autocomplete="off" spellcheck="false">
  </div>

  <div class="card" style="margin-bottom:10px">
    <div class="card-title">Subnet Requirements <span style="font-size:11px;text-transform:none;letter-spacing:0;color:#6c7086">(sorted largest → smallest automatically)</span></div>
    <table class="vlsm-table" id="vlsm-req-table">
      <thead>
        <tr>
          <th style="width:40px;font-size:11px;color:#6c7086;text-align:center;padding:4px">#</th>
          <th style="font-size:11px;color:#6c7086;padding:4px">Subnet Name / Label</th>
          <th style="font-size:11px;color:#6c7086;padding:4px;width:160px">Hosts Needed</th>
          <th style="width:50px"></th>
        </tr>
      </thead>
      <tbody id="vlsm-rows"></tbody>
    </table>
    <button class="btn-secondary" style="font-size:12px;padding:5px 12px" onclick="addVLSMRow()">+ Add subnet</button>
  </div>

  <div class="input-row">
    <button class="btn-primary" onclick="calcVLSM()">Calculate VLSM</button>
    <button class="btn-secondary" onclick="clearVLSM()">Reset</button>
  </div>

  <div class="chips">
    <span class="chips-label">Load example:</span>
    <span class="chip" onclick="loadVLSMExample()">Office network (192.168.10.0/24)</span>
  </div>

  <div id="vlsm-err" class="err-box" style="display:none"></div>
  <div id="vlsm-results" style="display:none">
    <div class="tbl-wrap">
      <div class="tbl-hdr">
        <span class="tbl-hdr-title">VLSM Allocations</span>
        <button class="btn-secondary" style="font-size:12px;padding:4px 10px" onclick="copyVLSMTable()">Copy CSV</button>
      </div>
      <div style="overflow-x:auto">
        <table class="rtable" id="vlsm-table">
          <thead>
            <tr>
              <th>Name</th><th>Hosts Needed</th><th>CIDR</th><th>Network</th>
              <th>Broadcast</th><th>First Host</th><th>Last Host</th><th>Usable</th><th>Mask</th>
            </tr>
          </thead>
          <tbody id="vlsm-tbody"></tbody>
        </table>
      </div>
    </div>
    <div id="vlsm-remaining" style="margin-top:10px;display:none">
      <div style="font-size:12px;color:#6c7086;margin-bottom:4px">Remaining unallocated space:</div>
      <div class="remaining-list" id="vlsm-rem-list"></div>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 4 – Supernet
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-supernet">
  <div class="panel-title">Supernet / Summarise</div>
  <div class="panel-sub">Collapse multiple networks into the smallest set of covering prefixes</div>

  <div class="info-box">
    Enter one network per line (CIDR notation). The result is the minimum set of prefixes that covers all input networks without adding any extra addresses.
  </div>

  <textarea class="main-textarea" id="supernet-in" placeholder="192.168.0.0/24&#10;192.168.1.0/24&#10;192.168.2.0/24&#10;192.168.3.0/24" spellcheck="false"></textarea>

  <div class="input-row">
    <button class="btn-primary" onclick="calcSupernet()">Summarise</button>
    <button class="btn-secondary" onclick="clearSupernet()">Clear</button>
  </div>

  <div class="chips">
    <span class="chips-label">Examples:</span>
    <span class="chip" onclick="loadSupernetEx1()">4 × /24 → /22</span>
    <span class="chip" onclick="loadSupernetEx2()">Mixed subnets</span>
    <span class="chip" onclick="loadSupernetEx3()">RFC 1918 blocks</span>
  </div>

  <div id="supernet-err" class="err-box" style="display:none"></div>
  <div id="supernet-results" style="display:none">
    <div class="card">
      <div class="card-title">Input networks <span id="supernet-in-count"></span></div>
      <div id="supernet-in-list"></div>
    </div>
    <div class="card">
      <div class="card-title">Summarised result <span id="supernet-out-count"></span></div>
      <div id="supernet-out-list"></div>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 5 – Range → CIDR
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-range">
  <div class="panel-title">IP Range → CIDR</div>
  <div class="panel-sub">Convert a start/end IP address range to the minimum set of CIDR blocks</div>

  <div class="input-row">
    <span style="font-size:13px;color:#6c7086;white-space:nowrap">Start IP:</span>
    <input class="main-input" id="range-start" type="text" placeholder="192.168.1.0" autocomplete="off" spellcheck="false" style="max-width:200px">
    <span style="font-size:13px;color:#6c7086;white-space:nowrap">End IP:</span>
    <input class="main-input" id="range-end" type="text" placeholder="192.168.1.255" autocomplete="off" spellcheck="false" style="max-width:200px">
    <button class="btn-primary" onclick="calcRange()">Convert</button>
    <button class="btn-secondary" onclick="clearRange()">Clear</button>
  </div>

  <div class="chips">
    <span class="chips-label">Examples:</span>
    <span class="chip" onclick="quickRange('192.168.1.0','192.168.1.255')">192.168.1.0 – .255</span>
    <span class="chip" onclick="quickRange('10.0.0.1','10.0.0.30')">10.0.0.1 – .30</span>
    <span class="chip" onclick="quickRange('172.16.0.0','172.31.255.255')">172.16.0.0 – 172.31.255.255</span>
  </div>

  <div id="range-err" class="err-box" style="display:none"></div>
  <div id="range-results" style="display:none">
    <div class="card">
      <div class="card-title">Covering CIDR blocks</div>
      <div id="range-pills"></div>
    </div>
    <div id="range-table-wrap" class="tbl-wrap" style="margin-top:10px">
      <table class="rtable" id="range-table">
        <thead><tr><th>#</th><th>CIDR</th><th>Network</th><th>Broadcast</th><th>Addresses</th></tr></thead>
        <tbody id="range-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 6 – Wildcard / ACL
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-wildcard">
  <div class="panel-title">Wildcard Mask &amp; ACL Helper</div>
  <div class="panel-sub">Generate wildcard masks and ready-to-paste ACL / routing statements</div>

  <div class="input-row">
    <input class="main-input" id="wc-in" type="text"
           placeholder="e.g. 192.168.1.0/24   or   10.0.0.0/255.255.0.0" autocomplete="off" spellcheck="false">
    <button class="btn-primary" onclick="calcWildcard()">Generate</button>
    <button class="btn-secondary" onclick="clearWildcard()">Clear</button>
  </div>

  <div class="chips">
    <span class="chips-label">Examples:</span>
    <span class="chip" onclick="quickWC('192.168.1.0/24')">192.168.1.0/24</span>
    <span class="chip" onclick="quickWC('10.0.0.0/8')">10.0.0.0/8</span>
    <span class="chip" onclick="quickWC('172.16.0.0/12')">172.16.0.0/12</span>
  </div>

  <div id="wc-err" class="err-box" style="display:none"></div>
  <div id="wc-results" style="display:none">

    <div class="card">
      <div class="card-title">Mask Summary</div>
      <div class="result-grid" id="wc-grid"></div>
    </div>

    <div class="card">
      <div class="card-title">Cisco IOS ACL</div>
      <div class="acl-block" id="wc-cisco"></div>
    </div>

    <div class="card">
      <div class="card-title">Routing Protocols</div>
      <div class="acl-block" id="wc-routing"></div>
    </div>

    <div class="card">
      <div class="card-title">Prefix Lists &amp; JunOS</div>
      <div class="acl-block" id="wc-prefix"></div>
    </div>

    <div class="card">
      <div class="card-title">Object / NAT</div>
      <div class="acl-block" id="wc-obj"></div>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 7 – IPv6
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-ipv6">
  <div class="panel-title">IPv6 Calculator</div>
  <div class="panel-sub">Analyse an IPv6 address or prefix</div>

  <div class="input-row">
    <input class="main-input" id="ipv6-in" type="text"
           placeholder="e.g. 2001:db8::1/32  or  fe80::1  or  ::1" autocomplete="off" spellcheck="false">
    <button class="btn-primary" onclick="calcIPv6()">Calculate</button>
    <button class="btn-secondary" onclick="clearIPv6()">Clear</button>
  </div>

  <div class="chips">
    <span class="chips-label">Examples:</span>
    <span class="chip" onclick="quickIPv6('2001:db8::1/32')">2001:db8::1/32</span>
    <span class="chip" onclick="quickIPv6('fe80::1/64')">fe80::1/64 (link-local)</span>
    <span class="chip" onclick="quickIPv6('::1')">Loopback ::1</span>
    <span class="chip" onclick="quickIPv6('fc00::1/7')">fc00::1/7 (ULA)</span>
    <span class="chip" onclick="quickIPv6('2002:c0a8:101::1/48')">6to4</span>
  </div>

  <div id="ipv6-err" class="err-box" style="display:none"></div>
  <div id="ipv6-results" style="display:none">
    <div class="card">
      <div class="card-title">Address Forms</div>
      <div class="result-grid" id="ipv6-grid"></div>
    </div>
    <div class="card">
      <div class="card-title">Prefix Information</div>
      <div class="result-grid" id="ipv6-prefix-grid"></div>
    </div>
    <div class="card">
      <div class="card-title">Address Properties</div>
      <div id="ipv6-flags"></div>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════════════════════
     TAB 8 – Reference
══════════════════════════════════════════════════════════════════════════════ -->
<div class="tab-panel" id="tab-reference">
  <div class="panel-title">Subnet Reference</div>
  <div class="panel-sub">Quick-reference tables for network professionals</div>

  <div class="ref-cols">
    <div>
      <!-- IPv4 mask table generated by JS -->
      <div class="ref-section">
        <h3>IPv4 Subnet Mask Reference</h3>
        <div class="tbl-wrap">
          <div style="overflow-y:auto;max-height:500px">
            <table class="rtable" id="ref-mask-table">
              <thead>
                <tr>
                  <th>Prefix</th><th>Subnet Mask</th><th>Wildcard</th>
                  <th style="text-align:right">Addresses</th><th style="text-align:right">Usable Hosts</th>
                </tr>
              </thead>
              <tbody id="ref-mask-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

    <div>
      <!-- Special ranges -->
      <div class="ref-section">
        <h3>RFC 1918 Private Address Space</h3>
        <div class="tbl-wrap">
          <table class="rtable">
            <thead><tr><th>Range</th><th>Prefix</th><th>Addresses</th></tr></thead>
            <tbody>
              <tr><td class="tc">10.0.0.0/8</td><td class="tc">10.0.0.0 – 10.255.255.255</td><td>16,777,216</td></tr>
              <tr><td class="tc">172.16.0.0/12</td><td class="tc">172.16.0.0 – 172.31.255.255</td><td>1,048,576</td></tr>
              <tr><td class="tc">192.168.0.0/16</td><td class="tc">192.168.0.0 – 192.168.255.255</td><td>65,536</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="ref-section">
        <h3>Special-Purpose IPv4 Ranges</h3>
        <div class="tbl-wrap">
          <table class="rtable">
            <thead><tr><th>Range</th><th>Purpose</th></tr></thead>
            <tbody>
              <tr><td class="tc">0.0.0.0/8</td><td>This network (source only)</td></tr>
              <tr><td class="tc">100.64.0.0/10</td><td>Shared address (ISP CG-NAT)</td></tr>
              <tr><td class="tc">127.0.0.0/8</td><td>Loopback</td></tr>
              <tr><td class="tc">169.254.0.0/16</td><td>Link-local / APIPA</td></tr>
              <tr><td class="tc">192.0.0.0/24</td><td>IETF Protocol Assignments</td></tr>
              <tr><td class="tc">192.0.2.0/24</td><td>TEST-NET-1 (Documentation)</td></tr>
              <tr><td class="tc">192.88.99.0/24</td><td>6to4 Anycast (deprecated)</td></tr>
              <tr><td class="tc">198.18.0.0/15</td><td>Benchmarking (RFC 2544)</td></tr>
              <tr><td class="tc">198.51.100.0/24</td><td>TEST-NET-2 (Documentation)</td></tr>
              <tr><td class="tc">203.0.113.0/24</td><td>TEST-NET-3 (Documentation)</td></tr>
              <tr><td class="tc">224.0.0.0/4</td><td>Multicast (Class D)</td></tr>
              <tr><td class="tc">240.0.0.0/4</td><td>Reserved (Class E)</td></tr>
              <tr><td class="tc">255.255.255.255/32</td><td>Limited broadcast</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="ref-section">
        <h3>IPv6 Address Types</h3>
        <div class="tbl-wrap">
          <table class="rtable">
            <thead><tr><th>Prefix</th><th>Type</th></tr></thead>
            <tbody>
              <tr><td class="tc">::1/128</td><td>Loopback</td></tr>
              <tr><td class="tc">fe80::/10</td><td>Link-local</td></tr>
              <tr><td class="tc">fc00::/7</td><td>Unique Local (ULA)</td></tr>
              <tr><td class="tc">ff00::/8</td><td>Multicast</td></tr>
              <tr><td class="tc">2000::/3</td><td>Global Unicast (GUA)</td></tr>
              <tr><td class="tc">2001:db8::/32</td><td>Documentation</td></tr>
              <tr><td class="tc">2002::/16</td><td>6to4</td></tr>
              <tr><td class="tc">64:ff9b::/96</td><td>IPv4-mapped (NAT64)</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="ref-section">
        <h3>Well-Known Ports (Quick Reference)</h3>
        <div class="tbl-wrap">
          <table class="rtable">
            <thead><tr><th>Port</th><th>Protocol</th><th>Service</th></tr></thead>
            <tbody>
              <tr><td class="tc">22</td><td>TCP</td><td>SSH</td></tr>
              <tr><td class="tc">23</td><td>TCP</td><td>Telnet</td></tr>
              <tr><td class="tc">25</td><td>TCP</td><td>SMTP</td></tr>
              <tr><td class="tc">53</td><td>TCP/UDP</td><td>DNS</td></tr>
              <tr><td class="tc">67/68</td><td>UDP</td><td>DHCP</td></tr>
              <tr><td class="tc">80</td><td>TCP</td><td>HTTP</td></tr>
              <tr><td class="tc">161/162</td><td>UDP</td><td>SNMP</td></tr>
              <tr><td class="tc">179</td><td>TCP</td><td>BGP</td></tr>
              <tr><td class="tc">443</td><td>TCP</td><td>HTTPS</td></tr>
              <tr><td class="tc">514</td><td>UDP</td><td>Syslog</td></tr>
              <tr><td class="tc">520</td><td>UDP</td><td>RIP</td></tr>
              <tr><td class="tc">1812</td><td>UDP</td><td>RADIUS Auth</td></tr>
              <tr><td class="tc">3389</td><td>TCP</td><td>RDP</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>

</div><!-- #content -->

<div id="status-bar">Ready — enter an address above to begin</div>

<script>
// ─── Tab switching ───────────────────────────────────────────────────────────
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    setStatus('Ready');
  });
});

function setStatus(msg) { document.getElementById('status-bar').textContent = msg; }

function copyText(text, label) {
  navigator.clipboard.writeText(text).then(() => setStatus(`Copied: ${label || text}`));
}

function mkCopy(text, label) {
  const b = document.createElement('button');
  b.className = 'copy-btn'; b.textContent = 'Copy';
  b.onclick = () => copyText(text, label);
  return b;
}

// ─── Utility: escape HTML ────────────────────────────────────────────────────
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ─── Utility: formatted number ───────────────────────────────────────────────
function fmtN(n) { return Number(n).toLocaleString(); }

// ─── Utility: API fetch wrappers ─────────────────────────────────────────────
async function apiGet(path) {
  const r = await fetch(path);
  return r.json();
}
async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  return r.json();
}

// ─── Utility: show/hide error ────────────────────────────────────────────────
function showErr(id, msg) {
  const el = document.getElementById(id);
  el.textContent = '⚠ ' + msg;
  el.style.display = 'block';
}
function hideErr(id) { document.getElementById(id).style.display = 'none'; }

// ─── Utility: result-grid row helper ────────────────────────────────────────
function gridRow(label, value, cls, copyVal) {
  const lEl = document.createElement('span'); lEl.className = 'rl'; lEl.textContent = label;
  const vEl = document.createElement('span'); vEl.className = 'rv ' + (cls||''); vEl.textContent = value;
  const cEl = mkCopy(copyVal !== undefined ? copyVal : String(value), label);
  return [lEl, vEl, cEl];
}
function fillGrid(gridId, rows) {
  const g = document.getElementById(gridId);
  g.innerHTML = '';
  rows.forEach(([l, v, cls, cp]) => {
    gridRow(l, v, cls, cp).forEach(el => g.appendChild(el));
  });
}

// ════════════════════════════════════════════════════════════════════════════
// IPv4 Subnet Tab
// ════════════════════════════════════════════════════════════════════════════
const ipv4Input = document.getElementById('ipv4-in');
ipv4Input.addEventListener('keydown', e => { if (e.key === 'Enter') calcIPv4(); });

let ipv4Timer = null;
ipv4Input.addEventListener('input', () => {
  clearTimeout(ipv4Timer);
  ipv4Timer = setTimeout(() => { if (ipv4Input.value.trim()) calcIPv4(); }, 600);
});

function quickIPv4(v) { ipv4Input.value = v; calcIPv4(); }

async function calcIPv4() {
  const q = ipv4Input.value.trim();
  if (!q) return;
  setStatus('Calculating…');
  hideErr('ipv4-err');
  const d = await apiGet('/api/subnet?q=' + encodeURIComponent(q));
  if (d.error) {
    showErr('ipv4-err', d.error);
    document.getElementById('ipv4-results').style.display = 'none';
    setStatus('Error');
    return;
  }
  renderIPv4(d);
  document.getElementById('ipv4-results').style.display = 'block';
  setStatus(`${d.cidr}  •  ${d.num_hosts} usable hosts  •  ${d.ip_type}`);
}

function clearIPv4() {
  ipv4Input.value = '';
  document.getElementById('ipv4-results').style.display = 'none';
  hideErr('ipv4-err');
  setStatus('Ready');
}

function renderIPv4(d) {
  // Badges
  const privBadge = d.is_private
    ? `<span class="badge badge-priv">Private</span>`
    : `<span class="badge badge-pub">Public</span>`;
  const classBadge = {
    'A': 'badge-a', 'B': 'badge-b', 'C': 'badge-c',
    'D – Multicast': 'badge-d', 'E – Reserved': 'badge-e'
  }[d.ip_class] || '';

  // Main grid
  const grid = document.getElementById('ipv4-grid');
  grid.innerHTML = '';
  const rows = [
    ['IP Address',      d.ip,          'hi'],
    ['Network Address', d.network,     'hi'],
    ['Broadcast',       d.broadcast,   ''],
    ['First Host',      d.first_host,  'green'],
    ['Last Host',       d.last_host,   'green'],
    ['Usable Hosts',    d.num_hosts,   'green'],
    ['Total Addresses', d.num_addresses, ''],
    ['Prefix Length',   '/' + d.prefix_length, 'purple'],
    ['Subnet Mask',     d.subnet_mask, ''],
    ['Wildcard Mask',   d.wildcard_mask, 'peach'],
    ['CIDR Notation',   d.cidr,        'hi'],
    ['IP Class',        d.ip_class,    ''],
    ['IP Type',         d.ip_type,     ''],
  ];
  rows.forEach(([l, v, cls]) => gridRow(l, v, cls).forEach(el => grid.appendChild(el)));

  // Binary table
  const binEl = document.getElementById('ipv4-binary');
  const pf = d.prefix_length;
  function renderBinRow(label, bin, dec) {
    const row = document.createElement('div');
    row.className = 'bin-row';

    const lbl = document.createElement('span'); lbl.className = 'bin-lbl'; lbl.textContent = label;

    const val = document.createElement('span'); val.className = 'bin-val';
    let bitPos = 0;
    for (const ch of bin) {
      if (ch === '.') {
        const s = document.createElement('span'); s.className = 'sep'; s.textContent = '.';
        val.appendChild(s);
      } else {
        const s = document.createElement('span');
        s.className = bitPos < pf ? 'nb' : 'hb';
        s.textContent = ch;
        val.appendChild(s);
        bitPos++;
      }
    }

    const decEl = document.createElement('span'); decEl.className = 'bin-dec'; decEl.textContent = dec;
    row.appendChild(lbl); row.appendChild(val); row.appendChild(decEl);
    return row;
  }

  binEl.innerHTML = '';
  binEl.appendChild(renderBinRow('IP Address',  d.ip_bin,   d.ip));
  binEl.appendChild(renderBinRow('Subnet Mask', d.mask_bin, d.subnet_mask));
  binEl.appendChild(renderBinRow('Network',     d.net_bin,  d.network));
  binEl.appendChild(renderBinRow('Broadcast',   d.bcast_bin, d.broadcast === 'N/A (point-to-point /31)' ? d.broadcast : d.broadcast));

  // Planning grid
  const pg = document.getElementById('ipv4-planning');
  pg.innerHTML = '';
  const planRows = [
    ['Supernet (one up)',  d.supernet,    ''],
    ['Next split',        d.split_info,  ''],
  ];
  planRows.forEach(([l, v, cls]) => gridRow(l, v, cls).forEach(el => pg.appendChild(el)));
}

// ════════════════════════════════════════════════════════════════════════════
// Split Subnet Tab
// ════════════════════════════════════════════════════════════════════════════
let splitMode = 'count';

function setSplitMode(m) {
  splitMode = m;
  document.getElementById('split-mode-count').classList.toggle('active', m === 'count');
  document.getElementById('split-mode-hosts').classList.toggle('active', m === 'hosts');
  document.getElementById('split-val-label').textContent =
    m === 'count' ? 'Number of subnets:' : 'Min hosts per subnet:';
}

function quickSplit(net, mode, val) {
  document.getElementById('split-net').value = net;
  setSplitMode(mode);
  document.getElementById('split-val').value = val;
  calcSplit();
}

document.getElementById('split-net').addEventListener('keydown', e => { if (e.key === 'Enter') calcSplit(); });
document.getElementById('split-val').addEventListener('keydown', e => { if (e.key === 'Enter') calcSplit(); });

async function calcSplit() {
  const net = document.getElementById('split-net').value.trim();
  const val = document.getElementById('split-val').value.trim();
  if (!net || !val) { setStatus('Enter parent network and value'); return; }
  setStatus('Calculating…');
  hideErr('split-err');
  const d = await apiGet(`/api/split?net=${encodeURIComponent(net)}&mode=${splitMode}&val=${val}`);
  if (d.error) { showErr('split-err', d.error); document.getElementById('split-results').style.display='none'; setStatus('Error'); return; }
  renderSplitTable(d);
  document.getElementById('split-results').style.display = 'block';
  setStatus(`${d.shown} subnets shown (/${d.prefix} each)`);
}

function clearSplit() {
  document.getElementById('split-net').value = '';
  document.getElementById('split-val').value = '';
  document.getElementById('split-results').style.display = 'none';
  hideErr('split-err'); setStatus('Ready');
}

let lastSplitData = null;
function renderSplitTable(d) {
  lastSplitData = d;
  document.getElementById('split-tbl-title').textContent = `/${d.prefix} subnets`;
  document.getElementById('split-count').textContent =
    d.total > d.shown ? `Showing ${d.shown} of ${d.total}` : `${d.total} subnet${d.total===1?'':'s'}`;
  const tbody = document.getElementById('split-tbody');
  tbody.innerHTML = '';
  d.subnets.forEach((s, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${i+1}</td><td class="tc">${esc(s.cidr)}</td><td>${esc(s.network)}</td>
      <td>${esc(s.broadcast)}</td><td>${esc(s.first)}</td><td>${esc(s.last)}</td>
      <td class="th">${esc(s.hosts)}</td><td>${esc(s.mask)}</td>`;
    tbody.appendChild(tr);
  });
}

function copySplitTable() {
  if (!lastSplitData) return;
  const header = '#,CIDR,Network,Broadcast,First Host,Last Host,Usable Hosts,Mask';
  const rows = lastSplitData.subnets.map((s,i) =>
    `${i+1},${s.cidr},${s.network},${s.broadcast},${s.first},${s.last},${s.hosts},${s.mask}`);
  copyText([header,...rows].join('\n'), 'subnet table CSV');
}

// ════════════════════════════════════════════════════════════════════════════
// VLSM Tab
// ════════════════════════════════════════════════════════════════════════════
let vlsmRowCount = 0;

function addVLSMRow(name='', hosts='') {
  vlsmRowCount++;
  const tbody = document.getElementById('vlsm-rows');
  const tr = document.createElement('tr');
  tr.id = 'vlsm-row-' + vlsmRowCount;
  tr.innerHTML = `
    <td class="num-cell">${vlsmRowCount}</td>
    <td><input class="vlsm-input" type="text" placeholder="Subnet name" value="${esc(name)}"></td>
    <td><input class="vlsm-input" type="number" min="1" placeholder="Hosts needed" value="${esc(hosts)}" style="max-width:140px"></td>
    <td><button class="btn-danger" onclick="removeVLSMRow('vlsm-row-${vlsmRowCount}')">✕</button></td>`;
  tbody.appendChild(tr);
}

function removeVLSMRow(id) {
  const el = document.getElementById(id); if (el) el.remove();
}

function loadVLSMExample() {
  document.getElementById('vlsm-net').value = '192.168.10.0/24';
  document.getElementById('vlsm-rows').innerHTML = '';
  vlsmRowCount = 0;
  addVLSMRow('Engineering',  '50');
  addVLSMRow('Marketing',    '25');
  addVLSMRow('Management',   '10');
  addVLSMRow('Server Farm',  '100');
  addVLSMRow('Point-to-Point WAN', '2');
}

function clearVLSM() {
  document.getElementById('vlsm-net').value = '';
  document.getElementById('vlsm-rows').innerHTML = '';
  vlsmRowCount = 0;
  document.getElementById('vlsm-results').style.display = 'none';
  hideErr('vlsm-err'); setStatus('Ready');
}

document.getElementById('vlsm-net').addEventListener('keydown', e => { if (e.key === 'Enter') calcVLSM(); });

async function calcVLSM() {
  const net = document.getElementById('vlsm-net').value.trim();
  if (!net) { setStatus('Enter parent network'); return; }

  const rows = document.querySelectorAll('#vlsm-rows tr');
  const reqs = [];
  for (const r of rows) {
    const inputs = r.querySelectorAll('input');
    const name  = inputs[0].value.trim() || `Subnet`;
    const hosts = parseInt(inputs[1].value, 10);
    if (isNaN(hosts) || hosts < 1) { setStatus('All rows need a valid hosts value'); return; }
    reqs.push({name, hosts});
  }
  if (reqs.length === 0) { setStatus('Add at least one subnet requirement'); return; }

  setStatus('Calculating…');
  hideErr('vlsm-err');
  const d = await apiPost('/api/vlsm', {net, reqs});
  if (d.error) { showErr('vlsm-err', d.error); document.getElementById('vlsm-results').style.display='none'; setStatus('Error'); return; }
  renderVLSMTable(d);
  document.getElementById('vlsm-results').style.display = 'block';
  setStatus(`${d.allocations.length} subnets allocated from ${net}`);
}

let lastVLSMData = null;
function renderVLSMTable(d) {
  lastVLSMData = d;
  const tbody = document.getElementById('vlsm-tbody');
  tbody.innerHTML = '';
  d.allocations.forEach(a => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="tn">${esc(a.name)}</td><td>${esc(a.hosts_needed)}</td>
      <td class="tc">${esc(a.cidr)}</td><td>${esc(a.network)}</td>
      <td>${esc(a.broadcast)}</td><td>${esc(a.first)}</td><td>${esc(a.last)}</td>
      <td class="th">${esc(a.usable)}</td><td>${esc(a.mask)}</td>`;
    tbody.appendChild(tr);
  });

  const remDiv = document.getElementById('vlsm-remaining');
  const remList = document.getElementById('vlsm-rem-list');
  if (d.remaining && d.remaining.length > 0) {
    remList.innerHTML = '';
    d.remaining.forEach(r => {
      const c = document.createElement('span'); c.className = 'rem-chip'; c.textContent = r;
      remList.appendChild(c);
    });
    remDiv.style.display = 'block';
  } else { remDiv.style.display = 'none'; }
}

function copyVLSMTable() {
  if (!lastVLSMData) return;
  const hdr = 'Name,Hosts Needed,CIDR,Network,Broadcast,First Host,Last Host,Usable,Mask';
  const rows = lastVLSMData.allocations.map(a =>
    `${a.name},${a.hosts_needed},${a.cidr},${a.network},${a.broadcast},${a.first},${a.last},${a.usable},${a.mask}`);
  copyText([hdr,...rows].join('\n'), 'VLSM table CSV');
}

// ════════════════════════════════════════════════════════════════════════════
// Supernet Tab
// ════════════════════════════════════════════════════════════════════════════
function loadSupernetEx1() { document.getElementById('supernet-in').value = '192.168.0.0/24\n192.168.1.0/24\n192.168.2.0/24\n192.168.3.0/24'; }
function loadSupernetEx2() { document.getElementById('supernet-in').value = '10.1.0.0/24\n10.1.1.0/24\n10.1.4.0/22\n10.2.0.0/16'; }
function loadSupernetEx3() { document.getElementById('supernet-in').value = '10.0.0.0/8\n172.16.0.0/12\n192.168.0.0/16'; }
function clearSupernet()   { document.getElementById('supernet-in').value = ''; document.getElementById('supernet-results').style.display='none'; hideErr('supernet-err'); setStatus('Ready'); }

async function calcSupernet() {
  const raw = document.getElementById('supernet-in').value.trim();
  if (!raw) return;
  const nets = raw.split('\n').map(s => s.trim()).filter(Boolean);
  setStatus('Summarising…');
  hideErr('supernet-err');
  const d = await apiPost('/api/supernet', {nets});
  if (d.error) { showErr('supernet-err', d.error); document.getElementById('supernet-results').style.display='none'; setStatus('Error'); return; }

  document.getElementById('supernet-in-count').textContent = `(${nets.length})`;
  document.getElementById('supernet-out-count').textContent = `(${d.collapsed.length})`;

  const inList = document.getElementById('supernet-in-list');
  inList.innerHTML = '';
  nets.forEach(n => { const p = document.createElement('span'); p.className='cidr-pill'; p.textContent=n; inList.appendChild(p); });

  const outList = document.getElementById('supernet-out-list');
  outList.innerHTML = '';
  d.collapsed.forEach(n => { const p = document.createElement('span'); p.className='cidr-pill'; p.textContent=n; outList.appendChild(p); });

  document.getElementById('supernet-results').style.display='block';
  setStatus(`${nets.length} networks → ${d.collapsed.length} summarised prefix${d.collapsed.length===1?'':'es'}`);
}

// ════════════════════════════════════════════════════════════════════════════
// Range → CIDR Tab
// ════════════════════════════════════════════════════════════════════════════
function quickRange(s, e) { document.getElementById('range-start').value=s; document.getElementById('range-end').value=e; calcRange(); }
function clearRange()  { document.getElementById('range-start').value=''; document.getElementById('range-end').value=''; document.getElementById('range-results').style.display='none'; hideErr('range-err'); setStatus('Ready'); }

document.getElementById('range-start').addEventListener('keydown', e => { if (e.key==='Enter') calcRange(); });
document.getElementById('range-end').addEventListener('keydown',   e => { if (e.key==='Enter') calcRange(); });

async function calcRange() {
  const start = document.getElementById('range-start').value.trim();
  const end   = document.getElementById('range-end').value.trim();
  if (!start || !end) return;
  setStatus('Converting…');
  hideErr('range-err');
  const d = await apiGet(`/api/range?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
  if (d.error) { showErr('range-err', d.error); document.getElementById('range-results').style.display='none'; setStatus('Error'); return; }

  const pills = document.getElementById('range-pills');
  pills.innerHTML = '';
  d.cidrs.forEach(c => { const p = document.createElement('span'); p.className='cidr-pill'; p.textContent=c; pills.appendChild(p); });

  const tbody = document.getElementById('range-tbody');
  tbody.innerHTML = '';
  const ipv4 = await Promise.all(d.cidrs.map(c => apiGet('/api/subnet?q=' + encodeURIComponent(c))));
  ipv4.forEach((s, i) => {
    if (s.error) return;
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${i+1}</td><td class="tc">${esc(s.cidr)}</td><td>${esc(s.network)}</td>
      <td>${esc(s.broadcast)}</td><td class="th">${esc(s.num_addresses)}</td>`;
    tbody.appendChild(tr);
  });

  document.getElementById('range-results').style.display='block';
  setStatus(`${start} – ${end}  →  ${d.cidrs.length} CIDR block${d.cidrs.length===1?'':'s'}`);
}

// ════════════════════════════════════════════════════════════════════════════
// Wildcard / ACL Tab
// ════════════════════════════════════════════════════════════════════════════
function quickWC(v) { document.getElementById('wc-in').value=v; calcWildcard(); }
function clearWildcard() { document.getElementById('wc-in').value=''; document.getElementById('wc-results').style.display='none'; hideErr('wc-err'); setStatus('Ready'); }

document.getElementById('wc-in').addEventListener('keydown', e => { if (e.key==='Enter') calcWildcard(); });

let wcTimer = null;
document.getElementById('wc-in').addEventListener('input', () => {
  clearTimeout(wcTimer);
  wcTimer = setTimeout(() => { if (document.getElementById('wc-in').value.trim()) calcWildcard(); }, 600);
});

async function calcWildcard() {
  const q = document.getElementById('wc-in').value.trim();
  if (!q) return;
  setStatus('Generating…');
  hideErr('wc-err');
  const d = await apiGet('/api/wildcard?q=' + encodeURIComponent(q));
  if (d.error) { showErr('wc-err', d.error); document.getElementById('wc-results').style.display='none'; setStatus('Error'); return; }

  // Mask summary
  const grid = document.getElementById('wc-grid');
  grid.innerHTML = '';
  [
    ['Network / CIDR', d.cidr,    'hi'],
    ['Network',        d.network, ''],
    ['Subnet Mask',    d.mask,    ''],
    ['Wildcard Mask',  d.wildcard,'peach'],
    ['Prefix Length',  '/'+d.prefix, 'purple'],
  ].forEach(([l,v,cls]) => gridRow(l,v,cls).forEach(el => grid.appendChild(el)));

  // Cisco ACL
  document.getElementById('wc-cisco').textContent =
    `! Standard ACL\n${d.cisco_std}\n\n! Extended ACL\n${d.cisco_ext}\n\n! Named Standard ACL\n${d.named_std}\n\n! Named Extended ACL\n${d.named_ext}`;

  // Routing protocols
  document.getElementById('wc-routing').textContent =
    `! OSPF network statement\n${d.ospf}\n\n! EIGRP network statement\n${d.eigrp}\n\n! BGP network statement\n${d.bgp_net}`;

  // Prefix lists + JunOS
  document.getElementById('wc-prefix').textContent =
    `! Cisco IOS prefix-list\n${d.prefix_list}\n\n! JunOS route-filter\n${d.juniper}`;

  // Object / NAT
  document.getElementById('wc-obj').textContent = d.obj_network;

  document.getElementById('wc-results').style.display='block';
  setStatus(`${d.cidr}  •  wildcard: ${d.wildcard}`);
}

// ════════════════════════════════════════════════════════════════════════════
// IPv6 Tab
// ════════════════════════════════════════════════════════════════════════════
function quickIPv6(v) { document.getElementById('ipv6-in').value=v; calcIPv6(); }
function clearIPv6() { document.getElementById('ipv6-in').value=''; document.getElementById('ipv6-results').style.display='none'; hideErr('ipv6-err'); setStatus('Ready'); }

document.getElementById('ipv6-in').addEventListener('keydown', e => { if (e.key==='Enter') calcIPv6(); });

async function calcIPv6() {
  const q = document.getElementById('ipv6-in').value.trim();
  if (!q) return;
  setStatus('Calculating…');
  hideErr('ipv6-err');
  const d = await apiGet('/api/ipv6?q=' + encodeURIComponent(q));
  if (d.error) { showErr('ipv6-err', d.error); document.getElementById('ipv6-results').style.display='none'; setStatus('Error'); return; }

  // Address forms
  const ag = document.getElementById('ipv6-grid');
  ag.innerHTML = '';
  [
    ['Compressed',  d.compressed, 'hi'],
    ['Full (Expanded)', d.expanded, 'purple'],
  ].forEach(([l,v,cls]) => gridRow(l,v,cls).forEach(el => ag.appendChild(el)));

  // Prefix info
  const pg = document.getElementById('ipv6-prefix-grid');
  pg.innerHTML = '';
  [
    ['Network Address', d.network,       'hi'],
    ['Prefix Length',   '/'+d.prefix_length, 'purple'],
    ['Addresses',       d.num_addresses, ''],
    d.ipv4_mapped ? ['IPv4-mapped', d.ipv4_mapped, 'peach'] : null,
    d.sixtofour   ? ['6to4 IPv4',   d.sixtofour,   'peach'] : null,
  ].filter(Boolean).forEach(([l,v,cls]) => gridRow(l,v,cls).forEach(el => pg.appendChild(el)));

  // Flags
  const flags = [
    ['Global', d.is_global],
    ['Private / ULA', d.is_private],
    ['Link-local', d.is_link_local],
    ['Loopback', d.is_loopback],
    ['Multicast', d.is_multicast],
  ];
  const flagEl = document.getElementById('ipv6-flags');
  flagEl.innerHTML = flags.filter(([,v])=>v).map(([l]) =>
    `<span class="badge badge-a" style="margin:3px">${esc(l)}</span>`
  ).join('') || '<span style="color:#6c7086;font-size:13px">No special flags</span>';

  document.getElementById('ipv6-results').style.display='block';
  setStatus(`${d.compressed}  •  ${d.type}`);
}

// ════════════════════════════════════════════════════════════════════════════
// Reference Tab – generate mask table
// ════════════════════════════════════════════════════════════════════════════
function buildRefTable() {
  const tbody = document.getElementById('ref-mask-tbody');
  const masks = {
    '/0':  '0.0.0.0',         '/1':  '128.0.0.0',       '/2':  '192.0.0.0',
    '/3':  '224.0.0.0',       '/4':  '240.0.0.0',       '/5':  '248.0.0.0',
    '/6':  '252.0.0.0',       '/7':  '254.0.0.0',       '/8':  '255.0.0.0',
    '/9':  '255.128.0.0',     '/10': '255.192.0.0',     '/11': '255.224.0.0',
    '/12': '255.240.0.0',     '/13': '255.248.0.0',     '/14': '255.252.0.0',
    '/15': '255.254.0.0',     '/16': '255.255.0.0',     '/17': '255.255.128.0',
    '/18': '255.255.192.0',   '/19': '255.255.224.0',   '/20': '255.255.240.0',
    '/21': '255.255.248.0',   '/22': '255.255.252.0',   '/23': '255.255.254.0',
    '/24': '255.255.255.0',   '/25': '255.255.255.128', '/26': '255.255.255.192',
    '/27': '255.255.255.224', '/28': '255.255.255.240', '/29': '255.255.255.248',
    '/30': '255.255.255.252', '/31': '255.255.255.254', '/32': '255.255.255.255',
  };
  const wildcards = {
    '/0':  '255.255.255.255', '/1':  '127.255.255.255', '/2':  '63.255.255.255',
    '/3':  '31.255.255.255',  '/4':  '15.255.255.255',  '/5':  '7.255.255.255',
    '/6':  '3.255.255.255',   '/7':  '1.255.255.255',   '/8':  '0.255.255.255',
    '/9':  '0.127.255.255',   '/10': '0.63.255.255',    '/11': '0.31.255.255',
    '/12': '0.15.255.255',    '/13': '0.7.255.255',     '/14': '0.3.255.255',
    '/15': '0.1.255.255',     '/16': '0.0.255.255',     '/17': '0.0.127.255',
    '/18': '0.0.63.255',      '/19': '0.0.31.255',      '/20': '0.0.15.255',
    '/21': '0.0.7.255',       '/22': '0.0.3.255',       '/23': '0.0.1.255',
    '/24': '0.0.0.255',       '/25': '0.0.0.127',       '/26': '0.0.0.63',
    '/27': '0.0.0.31',        '/28': '0.0.0.15',        '/29': '0.0.0.7',
    '/30': '0.0.0.3',         '/31': '0.0.0.1',         '/32': '0.0.0.0',
  };

  for (let p = 0; p <= 32; p++) {
    const key  = '/' + p;
    const addrs = Math.pow(2, 32 - p);
    const hosts = p < 31 ? addrs - 2 : (p === 31 ? 2 : 1);
    const tr = document.createElement('tr');
    const highlight = [8,12,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30].includes(p) ? 'class="tc"' : '';
    tr.innerHTML = `<td ${highlight}>/${p}</td>
      <td style="font-family:monospace">${masks[key]||''}</td>
      <td style="font-family:monospace;color:#fab387">${wildcards[key]||''}</td>
      <td style="text-align:right;color:#a6e3a1">${addrs.toLocaleString()}</td>
      <td style="text-align:right;color:#a6e3a1">${hosts.toLocaleString()}</td>`;
    tbody.appendChild(tr);
  }
}
buildRefTable();

// ════════════════════════════════════════════════════════════════════════════
// Heartbeat – keep server alive; shut down when tab closes
// ════════════════════════════════════════════════════════════════════════════
setInterval(() => fetch('/ping').catch(() => {}), 5000);
window.addEventListener('beforeunload', () => navigator.sendBeacon('/quit'));

// Pre-populate VLSM with default rows
addVLSMRow(); addVLSMRow(); addVLSMRow();
</script>
</body>
</html>
"""

# ── HTTP server ──────────────────────────────────────────────────────────────

def free_port(port):
    """Kill any stale process listening on the port."""
    result = subprocess.run(
        ["lsof", "-ti", f":{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split()
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGTERM)
            print(f"  Freed port {port} (killed PID {pid})")
        except (ValueError, ProcessLookupError):
            pass
    if pids:
        time.sleep(0.3)


class _Server(http.server.HTTPServer):
    allow_reuse_address = True


def make_handler(server_ref):
    html_bytes       = HTML.encode("utf-8")
    last_ping        = [time.time()]
    HEARTBEAT_TIMEOUT = 15  # seconds

    def _watchdog():
        while True:
            time.sleep(5)
            if time.time() - last_ping[0] > HEARTBEAT_TIMEOUT:
                print("Browser closed — shutting down.")
                threading.Thread(target=server_ref.shutdown, daemon=True).start()
                return

    threading.Thread(target=_watchdog, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # silence request logs

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs     = urllib.parse.parse_qs(parsed.query)

            if parsed.path == "/":
                last_ping[0] = time.time()
                self._send(200, "text/html; charset=utf-8", html_bytes)

            elif parsed.path == "/ping":
                last_ping[0] = time.time()
                self._send(200, "text/plain", b"ok")

            elif parsed.path == "/quit":
                last_ping[0] = 0
                self._send(200, "text/plain", b"bye")
                threading.Thread(target=server_ref.shutdown, daemon=True).start()

            elif parsed.path == "/api/subnet":
                q = qs.get("q", [""])[0]
                self._json(api_subnet(q))

            elif parsed.path == "/api/split":
                net  = qs.get("net",  [""])[0]
                mode = qs.get("mode", ["count"])[0]
                val  = qs.get("val",  ["1"])[0]
                self._json(api_split(net, mode, val))

            elif parsed.path == "/api/range":
                start = qs.get("start", [""])[0]
                end   = qs.get("end",   [""])[0]
                self._json(api_range(start, end))

            elif parsed.path == "/api/ipv6":
                q = qs.get("q", [""])[0]
                self._json(api_ipv6(q))

            elif parsed.path == "/api/wildcard":
                q = qs.get("q", [""])[0]
                self._json(api_wildcard(q))

            else:
                self._send(404, "text/plain", b"Not found")

        def do_POST(self):
            if self.path == "/quit":
                last_ping[0] = 0
                self._send(200, "text/plain", b"bye")
                threading.Thread(target=server_ref.shutdown, daemon=True).start()
                return

            length = int(self.headers.get("Content-Length", 0))
            body   = self.rfile.read(length)

            if self.path == "/api/vlsm":
                try:
                    data = json.loads(body)
                    self._json(api_vlsm(data.get("net",""), data.get("reqs",[])))
                except Exception as e:
                    self._json({"error": str(e)})

            elif self.path == "/api/supernet":
                try:
                    data = json.loads(body)
                    self._json(api_supernet(data.get("nets",[])))
                except Exception as e:
                    self._json({"error": str(e)})

            else:
                self._send(404, "text/plain", b"Not found")

        def _send(self, code, ctype, body):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self._send(200, "application/json", body)

    return Handler


def main():
    print("─" * 54)
    print("  Subnet Calculator Mac")
    print(f"  Port {PORT}  |  Pure Python stdlib")
    print("─" * 54)

    free_port(PORT)
    server = _Server(("127.0.0.1", PORT), http.server.BaseHTTPRequestHandler)
    server.RequestHandlerClass = make_handler(server)

    url = f"http://127.0.0.1:{PORT}/"
    print(f"\n  Serving at {url}")
    print("  Close the browser tab (or Ctrl-C) to quit.\n")

    threading.Timer(0.4, lambda: subprocess.Popen(["open", url])).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("\nDone.")


if __name__ == "__main__":
    main()
