#!/usr/bin/env python3
# acm_bridge.py — root libusb bridge for the t6040 Linux gadget console.
#
# macOS's AppleUSBCDC stack refuses to publish interfaces for the Linux
# configfs ACM gadget (while accepting m1n1's byte-equivalent device), so we
# bypass it: claim the device via libusb as root, configure it, and bridge
# the ACM bulk endpoints to localhost TCP so anything can talk to the M4's
# BusyBox shell on ttyGS0.
#
# Usage:   sudo python3 .plans/acm_bridge.py
# Then:    nc 127.0.0.1 5252   (or let the agent connect programmatically)

import socket
import sys
import threading
import time

import usb.core
import usb.util
import usb.backend.libusb1

VID, PID = 0x1209, 0x316D  # current gadget identity (m1n1-clone)
PORT = 5252

be = usb.backend.libusb1.get_backend(
    find_library=lambda x: "/opt/homebrew/lib/libusb-1.0.dylib")

dev = usb.core.find(idVendor=VID, idProduct=PID, backend=be)
if dev is None:
    sys.exit("gadget (1209:316d) not found on the bus")

print("found gadget, configuring...")
try:
    dev.set_configuration(1)
except usb.core.USBError as e:
    # darwin reports an IOKit-internal error even when the wire transaction
    # succeeds (device-side UDC state goes "configured"); ignore.
    print(f"set_configuration: {e} (wire transfer succeeds anyway; continuing)")

# Don't trust get_active_configuration() (stale darwin cache) — use the
# config descriptor directly.
cfg = dev[0]
data_intf = next(i for i in cfg if i.bInterfaceClass == 0x0A)
ctrl_intf = next(i for i in cfg if i.bInterfaceClass == 0x02)

for intf in (ctrl_intf.bInterfaceNumber, data_intf.bInterfaceNumber):
    try:
        usb.util.claim_interface(dev, intf)
    except usb.core.USBError as e:
        sys.exit(f"claim interface {intf}: {e} (run with sudo?)")

ep_out = next(e for e in data_intf
              if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
ep_in = next(e for e in data_intf
             if usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)

# ACM: 115200 8N1 + DTR/RTS so the gadget side sees an open port
dev.ctrl_transfer(0x21, 0x20, 0, ctrl_intf.bInterfaceNumber,
                  bytes([0x00, 0xC2, 0x01, 0x00, 0, 0, 8]), timeout=2000)
dev.ctrl_transfer(0x21, 0x22, 0x03, ctrl_intf.bInterfaceNumber, None, timeout=2000)
print(f"ACM up (eps in={ep_in.bEndpointAddress:#x} out={ep_out.bEndpointAddress:#x})")

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", PORT))
srv.listen(1)
print(f"listening on 127.0.0.1:{PORT} — connect with: nc 127.0.0.1 {PORT}")

while True:
    conn, addr = srv.accept()
    print(f"client connected: {addr}")
    stop = threading.Event()

    def usb_to_tcp():
        while not stop.is_set():
            try:
                data = dev.read(ep_in.bEndpointAddress, 4096, timeout=200)
                if len(data):
                    conn.sendall(bytes(data))
            except usb.core.USBTimeoutError:
                continue
            except Exception:
                stop.set()
                break

    t = threading.Thread(target=usb_to_tcp, daemon=True)
    t.start()

    try:
        while not stop.is_set():
            buf = conn.recv(512)
            if not buf:
                break
            dev.write(ep_out.bEndpointAddress, buf, timeout=2000)
    except Exception:
        pass
    finally:
        stop.set()
        t.join(timeout=1)
        conn.close()
        print("client disconnected; waiting for next connection")
