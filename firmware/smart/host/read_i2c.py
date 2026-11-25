#!/usr/bin/env python3
"""Read the INA228 smart profiler over I2C (e.g. Raspberry Pi: SDA = GPIO2, SCL = GPIO3).

    pip install smbus2
    python3 read_i2c.py                 # live current, voltage, average since the last line
    python3 read_i2c.py --csv log.csv   # also log every reading
    python3 read_i2c.py --reset         # zero charge/energy first

The board integrates charge and energy at its full conversion rate, so the average
current between two reads (delta charge / delta time) is exact even if you poll slowly.
"""
import argparse, struct, sys, time
from smbus2 import SMBus, i2c_msg

ADDR = 0x48
FMT = "<BBBBfffIIddd3f3fBBBB"          # register map 0x00..0x4B, little endian
SIZE = struct.calcsize(FMT)
RANGES = "LMH"


def read_all(bus):
    w = i2c_msg.write(ADDR, [0x00])
    r = i2c_msg.read(ADDR, SIZE)
    bus.i2c_rdwr(w, r)
    v = struct.unpack(FMT, bytes(r))
    return dict(who=v[0], fw=v[1], range=v[2], flags=v[3], current=v[4], voltage=v[5], power=v[6],
                samples=v[7], time_us=v[8], charge=v[9], energy=v[10], elapsed=v[11],
                r=v[12:15], off=v[15:18])


def write_reg(bus, reg, data):
    bus.i2c_rdwr(i2c_msg.write(ADDR, [reg] + list(data)))


def si(x, unit):
    a = abs(x)
    for f, p in ((1, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n"), (1e-12, "p")):
        if a >= f or f == 1e-12:
            return f"{x / f:8.3f} {p}{unit}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bus", type=int, default=1)
    ap.add_argument("--interval", type=float, default=0.2, help="seconds between reads")
    ap.add_argument("--csv", help="append readings to this file")
    ap.add_argument("--reset", action="store_true", help="reset charge/energy on the board")
    a = ap.parse_args()

    with SMBus(a.bus) as bus:
        d = read_all(bus)
        if d["who"] != 0xA8:
            sys.exit(f"no profiler at 0x{ADDR:02X} (WHO_AM_I = 0x{d['who']:02X})")
        if not d["flags"] & 2:
            print("warning: the board reports no INA228")
        if a.reset:
            write_reg(bus, 0x4B, [0x01])
            time.sleep(0.05)
        out = open(a.csv, "a") if a.csv else None
        if out and out.tell() == 0:
            out.write("time_s,current_A,voltage_V,range,avg_current_A,charge_C,energy_J\n")
        prev = read_all(bus)
        t0 = time.time()
        while True:
            time.sleep(a.interval)
            d = read_all(bus)
            dt = d["elapsed"] - prev["elapsed"]
            avg = (d["charge"] - prev["charge"]) / dt if dt > 0 else float("nan")
            prev = d
            print(f"I {si(d['current'], 'A')}  V {d['voltage']:6.3f} V  range {RANGES[d['range']]}  "
                  f"avg {si(avg, 'A')}  Q {d['charge']*1e3:10.4f} mC  E {d['energy']*1e3:10.4f} mJ")
            if out:
                out.write(f"{time.time()-t0:.3f},{d['current']:.6e},{d['voltage']:.4f},{RANGES[d['range']]},"
                          f"{avg:.6e},{d['charge']:.9e},{d['energy']:.9e}\n")
                out.flush()


if __name__ == "__main__":
    main()
