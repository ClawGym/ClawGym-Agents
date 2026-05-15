def is_prime(n: int) -> bool:
    """Return True if n is a prime number, else False."""
    if not isinstance(n, int) or n < 2:
      return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def factorial(n: int) -> int:
    """Return n! for non-negative integers n."""
    if not isinstance(n, int) or n < 0:
        raise ValueError("n must be a non-negative integer")
    result = 1
    for i in range(2, n + 1):
        result *= i
    return result


def mean(values) -> float:
    """Return the arithmetic mean of a non-empty iterable of numbers."""
    vals = list(values)
    if len(vals) == 0:
        raise ValueError("empty sequence")
    total = 0.0
    count = 0
    for v in vals:
        total += float(v)
        count += 1
    return total / count
