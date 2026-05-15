#!/usr/bin/env python3
import time

def work():
    # Lightweight deterministic computation
    total = 0
    for i in range(10000):
        total += (i * i) % 97
    return total

if __name__ == "__main__":
    work()
    # Small sleep to stabilize timing but keep it fast
    time.sleep(0.01)