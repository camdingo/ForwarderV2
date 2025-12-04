# remoteConnection.py
import socket
import threading
import time
from typing import Optional, Callable

class RemoteConnection:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        magic_keyword: Optional[str] = None,
        timeout: float = 10.0,
        keepalive_timeout: float = 300.0,
        buffer_size: int = 65536,
        auto_reconnect: bool = True,
        reconnect_delay: float = 3.0
    ):
        if magic_keyword is not None and len(magic_keyword) != 4:
            raise ValueError("magic_keyword must be exactly 4 characters")

        self.host = host
        self.port = port
        self.timeout = timeout
        self.keepalive_timeout = keepalive_timeout
        self.buffer_size = buffer_size
        self.auto_reconnect = auto_reconnect
        self.reconnect_delay = reconnect_delay
        self.magic_keyword = magic_keyword.encode("latin1") if magic_keyword else None

        self.socket: Optional[socket.socket] = None
        self.connected = False
        self.running = False
        self._last_receive_time = 0.0
        self._reconnect_active = False
        self._stop_event = threading.Event()
        self._receive_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self.on_connect: Optional[Callable[[], None]] = None
        self.on_disconnect: Optional[Callable[[Exception], None]] = None
        self.on_message: Optional[Callable[[bytes], None]] = None

    def connect(self) -> bool:
        with self._lock:
            if self.connected:
                return True

            target = f"{self.host}:{self.port}"

            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.settimeout(self.timeout)
                self.socket.connect((self.host, self.port))

                self.connected = True
                self.running = True
                self._last_receive_time = time.time()
                self._stop_event.clear()

                print(f"[+] Connected to {target}")

                if self.magic_keyword:
                    self.socket.sendall(self.magic_keyword)

                self._receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
                self._receive_thread.start()

                if self.on_connect:
                    self.on_connect()

                return True

            except Exception as e:
                print(f"[-] Connect failed to {target}: {e}")

            if self.auto_reconnect and not self._reconnect_active:
                self._reconnect_active = True
                threading.Thread(target=self._reconnect_loop, daemon=True).start()
            return False

    def _receive_loop(self):
        while not self._stop_event.is_set() and self.running:
            if time.time() - self._last_receive_time > self.keepalive_timeout:
                print(f"[!] Keepalive timeout to {self.host}:{self.port}")
                self._handle_disconnect(ConnectionError("Keepalive timeout"))
                return

            try:
                ready, _, _ = socket.select.select([self.socket], [], [], 1.0)
                if ready:
                    data = self.socket.recv(self.buffer_size)
                    if not data:
                        raise ConnectionError("Remote closed")
                    self._last_receive_time = time.time()
                    if self.on_message:
                        self.on_message(data)
            except (socket.timeout, ValueError, OSError):
                continue
            except Exception:
                break
        if self.connected:
            self._handle_disconnect()

    def _cleanup_socket_and_thread(self):
        with self._lock:
            self._stop_event.set()

            if (self._receive_thread
                and self._receive_thread.is_alive()
                and threading.current_thread() is not self._receive_thread):
                self._receive_thread.join(timeout=2.0)

            if self.socket:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None

            self.connected = False
            self.running = False
            self._stop_event.clear()

    def _handle_disconnect(self, exc: Optional[Exception] = None):
        self._cleanup_socket_and_thread()

        reason = str(exc) if exc else "Unknown"
        print(f"[-] Disconnected from {self.host}:{self.port} | {reason}")

        if self.on_disconnect:
            self.on_disconnect(exc or ConnectionError(reason))

        if self.auto_reconnect and not self._reconnect_active:
            self._reconnect_active = True
            threading.Thread(target=self._reconnect_loop, daemon=True).start()

    def _reconnect_loop(self):
        delay = self.reconnect_delay
        target = f"{self.host}:{self.port}"
        while self.auto_reconnect and not self.connected:
            print(f"[*] Reconnecting to {target} in {delay:.1f}s...")
            time.sleep(delay)
            if self.connect():
                with self._lock:
                    self._reconnect_active = False
                return
            delay = min(delay * 2, 30.0)
        with self._lock:
            self._reconnect_active = False

    def disconnect(self, force_no_reconnect=False):
        if force_no_reconnect:
            self.auto_reconnect = False
        self._cleanup_socket_and_thread()

    def force_disconnect_and_reconnect(self):
        self._handle_disconnect(ConnectionError("Stale data — forced reconnect"))

    def send(self, data: bytes) -> bool:
        with self._lock:
            if not self.connected or not self.socket:
                return False
            try:
                self.socket.sendall(data)
                return True
            except Exception as e:
                self._handle_disconnect(e)
                return False