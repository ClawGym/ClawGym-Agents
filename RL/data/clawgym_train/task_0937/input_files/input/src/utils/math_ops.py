from typing import List


def add(a, b):
    return a + b


def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


def moving_average(data: List[float], window: int) -> List[float]:
    if window <= 0:
        raise ValueError("window must be a positive integer.")
    if window > len(data):
        raise ValueError("window cannot be greater than the length of data.")
    result: List[float] = []
    window_sum = sum(data[:window])
    result.append(window_sum / window)
    for i in range(window, len(data)):
        window_sum += data[i] - data[i - window]
        result.append(window_sum / window)
    return result