#!/usr/bin/env python3
import subprocess, time, sys, logging
import requests, yaml, urllib3

CFG = yaml.safe_load(open(sys.argv[1] if len(sys.argv) > 1 else "config.yaml"))
C, S = CFG["controller"], CFG["switch"]
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
if not C.get("verify_tls", True):
    urllib3.disable_warnings()

sess = requests.Session()
sess.headers["X-API-KEY"] = C["api_key"]
sess.verify = C.get("verify_tls", True)
base = f"{C['url']}/proxy/network/api/s/{C['site']}"

def get(path):
    r = sess.get(base + path, timeout=8)
    r.raise_for_status()
    return r.json()["data"]

def clamp(v):
    return max(1, min(100, int(v)))

def build_ports():
    profiles = {p["_id"]: p["name"] for p in get("/rest/portconf")}
    dev = next(d for d in get("/stat/device")
               if d["mac"].lower() == S["mac"].lower())
    overrides = {o["port_idx"]: o.get("portconf_id")
                 for o in dev.get("port_overrides", [])}
    out = []
    for p in dev["port_table"]:
        idx = p["port_idx"]
        pid = overrides.get(idx) or p.get("portconf_id")
        name = profiles.get(pid)
        color = CFG["profiles"].get(name, CFG["default_color"]).lstrip("#")
        rgb = [int(color[i:i + 2], 16) for i in (0, 2, 4)]
        level = CFG["brightness_link"] if p.get("up") else CFG["brightness_nolink"]
        out.append((idx, rgb, clamp(level)))
    return out

def push(ports):
    cmds = [
        'm=$(cat /proc/led/led_mode)',
        '[ "$m" = "0" ] || { echo 0 > /proc/led/led_mode; echo "led_mode was $m, set to 0" >&2; }',
    ]
    for idx, rgb, level in ports:
        for ch, c in zip("rgb", rgb):
            v = round(c / 255 * 65535 * level / 100)
            cmds.append(f"echo '{idx} {ch} {v}' > /proc/led/led_color")
        cmds.append(f"echo '{idx} w 0' > /proc/led/led_color")
    res = subprocess.run(
        ["ssh", "-i", S["ssh_key"], "-o", "BatchMode=yes",
         "-o", "StrictHostKeyChecking=accept-new",
         f"{S['ssh_user']}@{S['ssh_host']}", "sh"],
        input="\n".join(cmds) + "\n", text=True, check=True,
        timeout=30, capture_output=True)
    if res.stderr.strip():
        logging.info("Switch: %s", res.stderr.strip())

while True:
    try:
        push(build_ports())
    except Exception as e:
        logging.warning("cycle failed: %s", e)
    time.sleep(CFG.get("interval_s", 10))

