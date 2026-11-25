#!/usr/bin/env python3
"""Read every sample from the smart profiler's UART (J3 TX/RX, 921600 8N1).

Connect a 3.3 V USB-serial adapter (CH340, CP2102, FT232...) or the Raspberry Pi UART:
    adapter RX <- J3 TX,  adapter TX -> J3 RX,  GND - GND

    pip install pyserial
    python3 read_uart.py /dev/ttyUSB0 --csv log.csv     # Linux / Pi (Pi UART: /dev/serial0)
    python3 read_uart.py COM5 --csv log.csv             # Windows
    python3 read_uart.py /dev/ttyUSB0 --cmd "cal L 990.3" --cmd save

Each line from the board is "t_us,current_A,voltage_V,range" (range 0 = L, 1 = M, 2 = H).
Lines starting with '#' are status messages.
"""
import argparse, sys, time
import serial


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--csv", help="write all samples to this file")
    ap.add_argument("--cmd", action="append", default=[], help="send a command first (repeatable)")
    ap.add_argument("--quiet", action="store_true", help="only print a summary every second")
    a = ap.parse_args()

    s = serial.Serial(a.port, a.baud, timeout=1)
    for c in a.cmd:
        s.write((c + "\n").encode()); time.sleep(0.1)
    out = open(a.csv, "w") if a.csv else None
    if out:
        out.write("t_us,current_A,voltage_V,range\n")
    n, acc, t_last = 0, 0.0, time.time()
    try:
        while True:
            line = s.readline().decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("t_us"):
                print(line, file=sys.stderr)
                continue
            if out:
                out.write(line + "\n")
            parts = line.split(",")
            if len(parts) == 4:
                n += 1; acc += float(parts[1])
            if not a.quiet:
                print(line)
            elif time.time() - t_last >= 1.0:
                print(f"{n} samples/s, mean current {acc / max(n, 1):.4e} A", file=sys.stderr)
                n, acc, t_last = 0, 0.0, time.time()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
