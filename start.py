#!/usr/bin/env python3
"""
Apex AI — Unified Launcher
Usage:
  python start.py              # Start backend API only
  python start.py --all        # Start backend + web frontend
  python start.py --help       # Show help
"""

import os, sys, subprocess, argparse, time, signal, threading

ROOT = os.path.dirname(os.path.abspath(__file__))

def print_banner():
    print("""
    ╔══════════════════════════════════════╗
    ║       Apex AI  v2.0                  ║
    ║  Local Autonomous Intelligence       ║
    ╚══════════════════════════════════════╝
    """)

def start_backend(port=8000):
    os.chdir(os.path.join(ROOT, "backend_api"))
    print(f"[API] Starting on http://localhost:{port}")
    print(f"[API] Docs at http://localhost:{port}/docs\n")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--reload", "--host", "0.0.0.0", "--port", str(port)],
        cwd=os.path.join(ROOT, "backend_api")
    )

def start_web(port=5173):
    os.chdir(os.path.join(ROOT, "frontend-web"))
    print(f"[WEB] Starting on http://localhost:{port}\n")
    is_windows = sys.platform == "win32"
    shell_cmd = "npx.cmd" if is_windows else "npx"
    return subprocess.Popen([shell_cmd, "vite", "--port", str(port), "--host"])

def start_mobile():
    os.chdir(os.path.join(ROOT, "frontend-mobile"))
    print("[MOBILE] Starting Expo...\n")
    return subprocess.Popen(["npx", "expo", "start"], shell=(sys.platform == "win32"))

def main():
    print_banner()

    parser = argparse.ArgumentParser(description="Apex AI Launcher")
    parser.add_argument("--all", action="store_true", help="Start backend + web")
    parser.add_argument("--mobile", action="store_true", help="Also start mobile")
    parser.add_argument("--port", type=int, default=8000, help="Backend port")
    parser.add_argument("--web-port", type=int, default=5173, help="Web frontend port")
    args = parser.parse_args()

    processes = []

    try:
        p = start_backend(args.port)
        processes.append(("Backend API", p))
        time.sleep(2)

        if args.all:
            p2 = start_web(args.web_port)
            processes.append(("Web Frontend", p2))

        if args.mobile:
            p3 = start_mobile()
            processes.append(("Mobile App", p3))

        print("\n" + "=" * 50)
        print("All services started. Press Ctrl+C to stop all.")
        print("=" * 50 + "\n")

        for name, proc in processes:
            proc.wait()

    except KeyboardInterrupt:
        print("\n\nShutting down...")
        for name, proc in processes:
            print(f"  Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        print("All services stopped.")

if __name__ == "__main__":
    main()
