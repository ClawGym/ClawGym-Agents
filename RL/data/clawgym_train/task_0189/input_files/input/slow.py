#!/usr/bin/env python3
import time

def work():
    # Heavier deterministic computation
    total = 0
    for i in range(300000):
        total += i % 13
    return total

if __name__ == "__main__":
    work()
    # Longer sleep to ensure slower runtime
    time.sleep(0.20)