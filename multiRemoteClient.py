# multiRemoteClient.py
import configparser
import socket
import threading
import time
from pathlib import Path
from remoteConnection import RemoteConnection

class ForwardingServer:
    def __init__(self, port: int, name: str):
        self.port = port
        self.name = name
        self.clients = set()
        self.lock = threading.Lock()
        self.running = True
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def start(self):
        try:
            self.server.bind(('0.0.0.0', self.port))
            self.server.listen(20)
            print(f"[{self.name}] FORWARD listening on 0.0.0.0:{self.port}")
            threading.Thread(target=self._accept, daemon=True).start()
        except Exception as e:
            print(f"[{self.name}] FORWARD bind failed :{self.port} → {e}")

    def _accept(self):
        while self.running:
            try:
                self.server.settimeout(1.0)
                client, addr = self.server.accept()
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                with self.lock:
                    self.clients.add(client)
                print(f"[{self.name}] FORWARD viewer connected {addr}")
            except socket.timeout:
                continue
            except Exception:
                break

    def broadcast(self, data: bytes):
        if not data:
            return
        dead = []
        with self.lock:
            for c in self.clients.copy():
                try:
                    c.sendall(data)
                except:
                    dead.append(c)
        for d in dead:
            with self.lock:
                self.clients.discard(d)
            try:
                d.close()
            except:
                pass

    def stop(self):
        self.running = False
        with self.lock:
            for c in list(self.clients):
                try:
                    c.shutdown(socket.SHUT_RDWR)
                    c.close()
                except:
                    pass
            self.clients.clear()
        try:
            self.server.close()
        except:
            pass

def load_config(file="connections.ini"):
    cfg = configparser.ConfigParser()
    if not Path(file).exists():
        print("[!] connections.ini not found")
        return []
    cfg.read(file)
    conns = []
    for s in cfg.sections():
        if not s.startswith("connection."):
            continue
        try:
            c = {
                "name": s[11:],
                "remote_host": cfg.get(s, "remote_host"),
                "remote_port": cfg.getint(s, "remote_port"),
                "forward_port": cfg.getint(s, "forward_port"),
                "keyword": cfg.get(s, "keyword", fallback=None)
            }
            if c["keyword"] and len(c["keyword"].strip()) != 4:
                print(f"[!] {c['name']}: keyword must be 4 chars — ignoring")
                c["keyword"] = None
            conns.append(c)
        except Exception as e:
            print(f"[!] Bad section {s}: {e}")
    return conns

def main():
    print("Starting Forwarder \n")
    connections = load_config()
    if not connections:
        return

    fleet = []

    for c in connections:
        fwd = ForwardingServer(c["forward_port"], c["name"])
        fwd.start()

        rc = RemoteConnection(
            host=c["remote_host"],
            port=c["remote_port"],
            magic_keyword=c["keyword"],
            keepalive_timeout=300,
            auto_reconnect=True
        )

        class StreamHandler:
            def __init__(self, remote_conn, forwarder, host, port, name):
                self.rc = remote_conn
                self.fwd = forwarder
                self.host = host
                self.port = port
                self.name = name
                self.last_seen = time.time()
                self.log = lambda tag, msg="": print(f"[{self.name}] {tag} {msg}".strip())

                self.stale_threshold = 6 * 3600
                self.stale_watchdog_running = False
                self.start_stale_watchdog()

            def start_stale_watchdog(self):
                self.stale_watchdog_running = True
                def watchdog():
                    while self.stale_watchdog_running:
                        time.sleep(60)
                        if self.rc.connected and (time.time() - self.last_seen > self.stale_threshold):
                            self.log("STALE", f"No data for {int((time.time()-self.last_seen)/60)}min → forcing reconnect")
                            self.rc.force_disconnect_and_reconnect()
                            return
                threading.Thread(target=watchdog, daemon=True).start()

            def update_last_seen_and_broadcast(self, data: bytes):
                self.last_seen = time.time()
                self.fwd.broadcast(data)

            def status_printer(self):
                while True:
                    time.sleep(30)
                    now = time.time()
                    delta = int(now - self.last_seen)
                    current_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
                    last_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_seen))
                    ago = "never" if delta > 10**9 else f"{delta}s ago"
                    status = "UP" if self.rc.connected else "DOWN"
                    recon = " (reconnecting)" if getattr(self.rc, "_reconnect_active", False) else ""
                    print(f"[{self.name}] {current_ts} | STATUS: {status}{recon} | LAST DATA: {last_ts} ({ago})", flush=True)

            def on_connect(self):
                self.log("UP", f"{self.host}:{self.port}")
                self.start_stale_watchdog()

            def on_disconnect(self, e):
                self.log("DOWN", str(e))
                self.stale_watchdog_running = False

        handler = StreamHandler(rc, fwd, c["remote_host"], c["remote_port"], c["name"])

        rc.on_message    = handler.update_last_seen_and_broadcast
        rc.on_connect    = handler.on_connect
        rc.on_disconnect = handler.on_disconnect

        threading.Thread(target=handler.status_printer, daemon=True).start()

        handler.log("START", f"→ {c['remote_host']}:{c['remote_port']} | forward :{c['forward_port']}")
        rc.connect()

        fleet.append((rc, fwd))

    try:
        print("\nSystem running. Viewers: nc 127.0.0.1 <forward_port>\n")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nShutting down...")
        for rc, _ in fleet:
            rc.disconnect(force_no_reconnect=True)
        print("Clean exit.")

if __name__ == "__main__":
    main()