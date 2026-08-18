import os, sys, subprocess, threading, traceback, socket
from pathlib import Path
from datetime import datetime
import pystray
from PIL import Image

APP_NAME="WoWInterpreter"
FROZEN=getattr(sys,"frozen",False)
HERE=Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
RESOURCE_ROOT=Path(getattr(sys,"_MEIPASS",HERE))
LOG=HERE/"WoWInterpreter.log"
BRIDGE=RESOURCE_ROOT/"Bridge"/"bridge.py"
ICON_PATH=RESOURCE_ROOT/"assets"/"WoWInterpreter.ico"
bridge_proc=None
lock=threading.Lock()
instance_socket=None

def log(msg):
    try:
        with LOG.open("a",encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except Exception: pass

def is_running():
    return bridge_proc is not None and bridge_proc.poll() is None

def notify(icon,msg):
    try: icon.notify(msg,APP_NAME)
    except Exception as e: log(f"Notification failed: {e}")

def acquire_single_instance():
    global instance_socket
    instance_socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:
        instance_socket.bind(("127.0.0.1",47621)); instance_socket.listen(1)
        return True
    except OSError:
        return False

def refresh(icon):
    icon.title=f"{APP_NAME} - {'Running' if is_running() else 'Stopped'}"
    icon.update_menu()

def start(icon,item=None):
    global bridge_proc
    with lock:
        if is_running(): return
        try:
            if not BRIDGE.exists(): raise FileNotFoundError(f"Bridge not found: {BRIDGE}")
            flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
            if FROZEN:
                cmd=[sys.executable,"--bridge"]
            else:
                cmd=[sys.executable,str(Path(__file__).resolve()),"--bridge"]
            bridge_proc=subprocess.Popen(cmd,cwd=str(HERE),creationflags=flags)
            log(f"Bridge child started PID={bridge_proc.pid} cmd={cmd}")
            threading.Thread(target=watch_bridge_exit,args=(icon,bridge_proc),
                             name="BridgeExitWatcher",daemon=True).start()
        except Exception as e:
            log(f"Start failed: {e}\n{traceback.format_exc()}")
            notify(icon,"Could not start translator. See WoWInterpreter.log.")
    refresh(icon)

def watch_bridge_exit(icon,proc):
    global bridge_proc
    try:
        rc=proc.wait()
        log(f"Bridge child exited PID={proc.pid} rc={rc}")
        with lock:
            if bridge_proc is proc:
                bridge_proc=None
        refresh(icon)
    except Exception as e:
        log(f"Bridge exit watcher failed: {e}")

def stop(icon,item=None):
    global bridge_proc
    with lock:
        if is_running():
            bridge_proc.terminate()
            try: bridge_proc.wait(timeout=4)
            except Exception: bridge_proc.kill()
        bridge_proc=None
    log("Translator stopped.")
    refresh(icon)

def status(icon,item=None):
    notify(icon,f"Translator: {'RUNNING' if is_running() else 'STOPPED'}. NLLB preloads on Start Translator.")

def open_log(icon,item=None):
    try:
        if not LOG.exists(): log("Log created.")
        os.startfile(str(LOG))
    except Exception as e: log(f"Open log failed: {e}")

def quit_app(icon,item=None):
    stop(icon); log("WoWInterpreter exiting."); icon.stop()

def main():
    log("="*60); log("WoWInterpreter v2.2.0 starting")
    log(f"Resource root={RESOURCE_ROOT}")
    if not acquire_single_instance():
        log("Second instance blocked."); return
    if not ICON_PATH.exists():
        log(f"Tray ICO missing: {ICON_PATH}"); return
    img=Image.open(ICON_PATH).convert("RGBA")
    menu=pystray.Menu(
        pystray.MenuItem("Start translator",start,enabled=lambda item:not is_running()),
        pystray.MenuItem("Stop translator",stop,enabled=lambda item:is_running()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(lambda item:f"Status: {'Running' if is_running() else 'Stopped'}",status),
        pystray.MenuItem("Open diagnostic log",open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit WoWInterpreter",quit_app))
    icon=pystray.Icon("WoWInterpreter",img,"WoWInterpreter - Stopped",menu)
    log("Entering tray loop.")
    icon.run()
    log("Tray loop exited.")

def run_bridge_mode():
    log("Bridge child mode entered.")
    import runpy
    old_cwd=os.getcwd()
    stream=open(LOG,"a",encoding="utf-8",buffering=1)
    old_out,old_err=sys.stdout,sys.stderr
    sys.stdout=stream; sys.stderr=stream
    try:
        print(f"[BRIDGE] logging attached. Resource root={RESOURCE_ROOT}",flush=True)
        print(f"[BRIDGE] bridge.py={BRIDGE}",flush=True)
        os.chdir(str(BRIDGE.parent))
        runpy.run_path(str(BRIDGE),run_name="__main__")
    except Exception:
        print("[BRIDGE] UNHANDLED EXCEPTION",flush=True)
        traceback.print_exc(file=stream)
        raise
    finally:
        os.chdir(old_cwd)
        sys.stdout,sys.stderr=old_out,old_err
        stream.close()

if __name__=="__main__":
    try:
        if "--bridge" in sys.argv[1:]:
            run_bridge_mode()
        else:
            main()
    except Exception as e:
        log(f"Fatal: {e}\n{traceback.format_exc()}")
