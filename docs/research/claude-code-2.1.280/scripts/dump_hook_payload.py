#!/usr/bin/env python3
import sys, json, os, time
raw = sys.stdin.read()
d = json.loads(raw)
n = f"{time.time_ns()}-{os.getpid()}-{d.get('hook_event_name')}-{d.get('tool_name','')}.json"
out = {"payload": d, "env": {k: v for k, v in os.environ.items() if k.startswith("CLAUDE_PROJECT") or k in ("PWD",)}, "argv": sys.argv, "cwd": os.getcwd(), "t_start": time.time()}
open(os.path.join(sys.argv[1], n), "w").write(json.dumps(out, indent=1))
