#!/usr/bin/env python3
"""Reads the rev D USB-C power meter (USB CDC serial) and prints or logs it.

  pip install pyserial
  python3 meter.py                     # live: V, A, W, mAh, mWh, CC / D+ / D- and a rough state
  python3 meter.py --log run.csv       # also write every data line to a CSV file
  python3 meter.py --cmd "every 1"     # send commands first (see "help"), e.g. full rate
  python3 meter.py --port COM5         # if the port is not found automatically

Data lines from the meter:   t_us,voltage_V,current_A,power_W,range   (range F = fine, C = coarse, ! = clipped)
Status lines (every 0.5 s):  #S,t_us,mAh,mWh,seconds,cc1_V,cc2_V,dp_V,dm_V,state[,dropped=N]
"""
import argparse, sys, time
import serial
from serial.tools import list_ports

VID, PID = 0x1209, 0x0001


def find_port():
    for p in list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    sys.exit("meter not found: plug J3 into this computer, or pass --port")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    ap.add_argument("--log", help="CSV file for the data lines")
    ap.add_argument("--cmd", action="append", default=[], help="command to send first (repeatable)")
    a = ap.parse_args()

    s = serial.Serial(a.port or find_port(), timeout=1)
    s.dtr = True                       # the meter only sends while the port is open (DTR set)
    for c in a.cmd:
        s.write((c + "\n").encode())
        time.sleep(0.1)
    log = open(a.log, "w") if a.log else None
    if log:
        log.write("t_us,voltage_V,current_A,power_W,range\n")
    last, status = None, None
    try:
        while True:
            line = s.readline().decode(errors="replace").strip()
            if not line:
                continue
            if line.startswith("#S,"):
                status = line.split(",")
            elif line.startswith("#"):
                print("\n" + line)
                continue
            else:
                last = line.split(",")
                if log:
                    log.write(line + "\n")
            if last and status:
                _, v, i, w, r = last[:5]
                mah, mwh, secs = status[2], status[3], status[4]
                cc1, cc2, dp, dm, state = status[5:10]
                sys.stdout.write(f"\r{float(v):7.3f} V {float(i):9.5f} A {float(w):8.4f} W  [{r:2}]  "
                                 f"{float(mah):9.3f} mAh {float(mwh):9.2f} mWh  {float(secs):7.1f} s  "
                                 f"CC {cc1}/{cc2} V  D+ {dp} D- {dm} V  {state}   ")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print()
    finally:
        if log:
            log.close()


if __name__ == "__main__":
    main()
