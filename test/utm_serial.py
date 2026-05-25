#!/usr/bin/env python3
import argparse
import os
import select
import sys
import termios
import time


def configure(fd, baud=termios.B115200):
    attrs = termios.tcgetattr(fd)
    attrs[0] = attrs[0] & ~(termios.IXON | termios.IXOFF | termios.ICRNL | termios.INLCR)
    attrs[1] = attrs[1] & ~termios.OPOST
    attrs[2] = attrs[2] | termios.CLOCAL | termios.CREAD
    attrs[3] = attrs[3] & ~(termios.ECHO | termios.ICANON | termios.ISIG | termios.IEXTEN)
    attrs[4] = baud
    attrs[5] = baud
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def read_until_idle(fd, timeout, idle):
    data = bytearray()
    deadline = time.time() + timeout
    idle_deadline = time.time() + idle
    while time.time() < deadline and time.time() < idle_deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        chunk = os.read(fd, 8192)
        if chunk:
            data.extend(chunk)
            idle_deadline = time.time() + idle
    return bytes(data)


def read_until_token(fd, token, timeout):
    data = bytearray()
    deadline = time.time() + timeout
    token_bytes = token.encode("utf-8")
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            continue
        chunk = os.read(fd, 8192)
        if chunk:
            data.extend(chunk)
            if token_bytes in data:
                break
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description="Minimal UTM PTTY serial helper")
    parser.add_argument("device")
    parser.add_argument("--cmd", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--idle", type=float, default=0.6)
    parser.add_argument("--pause", type=float, default=0.3)
    parser.add_argument("--interrupt", action="store_true")
    parser.add_argument("--no-marker", action="store_true")
    args = parser.parse_args()

    fd = os.open(args.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        configure(fd)
        output = bytearray()
        if args.interrupt:
            os.write(fd, b"\x03\r")
            time.sleep(args.pause)
            output.extend(read_until_idle(fd, 2, 0.4))
        if not args.cmd:
            os.write(fd, b"\n")
            output.extend(read_until_idle(fd, args.timeout, args.idle))
        else:
            for idx, cmd in enumerate(args.cmd):
                if args.no_marker:
                    os.write(fd, cmd.encode("utf-8") + b"\r")
                    time.sleep(args.pause)
                    output.extend(read_until_idle(fd, args.timeout, args.idle))
                    continue
                token = f"\x1f__UTM_SERIAL_DONE_{idx}__"
                printable = f"__UTM_SERIAL_DONE_{idx}__"
                wrapped = f"{cmd}; printf '\\n\\037{printable}:%s\\n' \"$?\""
                os.write(fd, wrapped.encode("utf-8") + b"\r")
                time.sleep(args.pause)
                output.extend(read_until_token(fd, token, args.timeout))
        sys.stdout.write(output.decode("utf-8", "replace"))
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
