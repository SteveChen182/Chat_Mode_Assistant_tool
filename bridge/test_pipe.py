"""Test: spawn dt gnai chat --json via ConPTY (pywinpty) and observe stdout."""
import time
import re
import sys

try:
    from winpty import PtyProcess
except ImportError:
    print("ERROR: pip install pywinpty")
    sys.exit(1)

DT = r"C:\Users\steveche\bin\dt.EXE"
ANSI_RE = re.compile(r'\x1b\[[^a-zA-Z]*[a-zA-Z]|\x1b\[\?[0-9]*[a-zA-Z]')

def strip_ansi(s):
    return ANSI_RE.sub('', s)

def main():
    cmd = f'{DT} gnai chat --json --assistant sighting_assistant'
    print(f"[test] spawning via ConPTY: {cmd}")
    
    proc = PtyProcess.spawn(cmd)
    print(f"[test] pty pid={proc.pid}")

    start = time.time()
    sent = False

    while time.time() - start < 120:
        if not proc.isalive():
            print("[test] process exited")
            break
        
        try:
            data = proc.read(4096)
        except EOFError:
            print("[test] EOF")
            break
        
        if not data:
            time.sleep(0.1)
            continue

        elapsed = time.time() - start
        
        # Show raw data
        if len(data) > 200:
            print(f"[{elapsed:.1f}s PTY {len(data)}ch] {data[:100]!r}...{data[-50:]!r}", flush=True)
        else:
            print(f"[{elapsed:.1f}s PTY {len(data)}ch] {data!r}", flush=True)

        # Extract clean lines
        clean = strip_ansi(data)
        for line in clean.splitlines():
            line = line.strip()
            if line:
                print(f"  [CLEAN] {line[:150]}", flush=True)
        
        # Send message after detecting ready
        if not sent and "> " in data:
            print(f"\n[test] prompt detected, sending message in 2s...", flush=True)
            time.sleep(2)
            proc.write("hello, briefly what can you do?\r")
            sent = True
            print("[test] message sent!", flush=True)

    print("[test] done.")
    try:
        proc.terminate()
    except:
        pass

if __name__ == "__main__":
    main()
