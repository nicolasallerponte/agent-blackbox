import os, subprocess, sys, time, fcntl
proj, shadow = sys.argv[1], sys.argv[2]
env = dict(os.environ, GIT_DIR=shadow, GIT_WORK_TREE=proj, GIT_INDEX_FILE=shadow+"/index-s1")
def g(*a, **k): return subprocess.run(["git", *a], env=env, cwd=proj, capture_output=True, text=True, check=True).stdout.strip()
lock = open(shadow+"/agent-blackbox.lock","w"); fcntl.flock(lock, fcntl.LOCK_EX)
g("add","-A","--ignore-errors",".")
t = g("write-tree")
parent = None
try: parent = g("rev-parse","-q","--verify","refs/ab/s1")
except subprocess.CalledProcessError: pass
c = g("commit-tree", t, *(["-p",parent] if parent else []), "-m", "step")
g("update-ref","refs/ab/s1", c)
