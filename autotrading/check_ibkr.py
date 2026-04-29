"""
check_ibkr.py

Quick diagnostic that probes IB Gateway connectivity on the standard ports
and reports which (if any) are alive. Run this before test_ibkr_single.py
or run_trendline_report.py to confirm the Gateway is reachable.
"""

import socket
import sys

CANDIDATE_PORTS = [
    (4001, 'IB Gateway live'),
    (4002, 'IB Gateway paper'),
    (7496, 'TWS live'),
    (7497, 'TWS paper'),
]


def probe(host: str, port: int, timeout: float = 1.0) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except (ConnectionRefusedError, OSError, socket.timeout):
        return False


def main():
    host = '127.0.0.1'
    print(f'Probing {host} for IB Gateway / TWS API ports...\n')
    alive = []
    for port, desc in CANDIDATE_PORTS:
        ok = probe(host, port)
        marker = 'OPEN' if ok else 'closed'
        print(f'  {host}:{port:5d} ({desc}): {marker}')
        if ok:
            alive.append((port, desc))

    print()
    if alive:
        print(f'OK — {len(alive)} port(s) listening. You can run:')
        for port, desc in alive:
            print(f'    python -m autotrading.test_ibkr_single QQQ   '
                  f'(but first set IB_PORT = {port} if not already)')
        sys.exit(0)
    else:
        print('FAILED — no IB API port is listening.')
        print('Check: (1) IB Gateway is logged in, (2) Configure -> Settings -> API -> '
              '"Enable ActiveX and Socket Clients" is checked, (3) socket port is 4001.')
        sys.exit(1)


if __name__ == '__main__':
    main()
