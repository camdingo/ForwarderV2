# Multi-Forwarder v2.0 Final

A lightweight, rock-solid, multi-stream TCP forwarding daemon written in pure Python.  
Designed for reliable, low-latency forwarding of binary or text protocols from multiple remote sources to local viewer ports — with zero cross-talk.

Perfect for feeding live telemetry, market data, industrial protocols, or any high-volume binary streams into tools like `netcat`, Wireshark, or custom parsers.

### Features
- Multiple independent streams defined in a simple INI file
- Automatic reconnect with exponential back-off
- Optional 4-byte magic keyword handshake (e.g., `TEST`, `Tes2`)
- Keep-alive timeout detection
- One-to-many broadcasting per stream (multiple viewers per port supported)
- Clean unidirectional flow: source → viewers only (no back-channel consumption)
- Graceful shutdown on Ctrl+C
- Zero external dependencies

### File Structure
├── multiRemoteClient.py      Main forwarding daemon (fixed & stable)
├── remoteConnection.py       Connection handler with reconnect logic
├── connections.ini           Configuration (edit this!)
└── README.md                 This file


### connections.ini Example
```ini
[connection.DATA_TYPE1]
remote_host = 127.0.0.1
remote_port = 5000
forward_port = 8001
keyword = TEST          ; optional 4-char magic bytes sent on connect

[connection.DATA_TYPE2]
remote_host = 192.168.1.100
remote_port = 5001
forward_port = 8002
keyword = TES2
```

remote_host:remote_port → where your data is coming from
forward_port → local port viewers connect to (nc 127.0.0.1 8001)
keyword → optional exactly-4-character string sent immediately after connect (useful for protocol handshakes)

# Quick Start
1. Start your data sources (example with netcat)
```
nc -lk 127.0.0.1 5000
nc -lk 127.0.0.1 5001
```

2. In another terminal — start the forwarder
```
python multiRemoteClient.py
```

3. View the streams
```
nc 127.0.0.1 8001    # receives only from 5000
nc 127.0.0.1 8002    # receives only from 5001
```

You can open as many nc viewers as you want on the same port — all receive identical data.

# Status Monitoring
The forwarder prints live status every 30 seconds:

[DATA_TYPE1] 2025-04-05 12:34:56 | LAST DATA: 2025-04-05 12:34:54 (2s ago)


# Dev log (pre git commit)
- Fixed silent data-eating in _cleaner() — viewer sockets were draining all incoming bytes and breaking TCP flow control.
- Fixed late-binding closure bug — both streams were using the last ForwardingServer instance (classic Python loop/lambda trap).
- Eliminated cross-talk — data from 5000 no longer leaks to 8002 and vice versa.
- Restored independent streams — each forward_port now receives only its own remote_port data.
- Removed unnecessary recv thread — viewers are now write-only (correct for unidirectional feeds).
- Proper per-stream broadcasting — multiple nc viewers on the same port work perfectly.
- Fixed viewer disconnect cleanup — dead clients no longer leak or block sends.
- Stable multi-section INI support — 1 or 50 connections work with zero interference.


# Known Fixed Issues (v2.0 Final)

Cross-talk between streams → eliminated (closure bug fixed)
Viewer connections silently eating data → removed (recv-drain thread deleted)
Only last stream receiving data → resolved with proper lambda default argument

Requirements

Python 3.6+
No pip packages required

License
Unlicensed / Free for any use. Do whatever you want with it.
Built for speed, stability, and sanity. Enjoy your clean streams.