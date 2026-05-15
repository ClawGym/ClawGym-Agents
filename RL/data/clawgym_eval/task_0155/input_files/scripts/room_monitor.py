# Configuration constants for room monitoring
QUIET_HOURS_ENABLED = True
QUIET_HOURS_START = "09:00"
QUIET_HOURS_END = "16:30"
NOISE_MONITOR_ENABLED = False
MAX_NOISE_DB = 50

def is_quiet_time(now_time):
    return QUIET_HOURS_ENABLED and QUIET_HOURS_START <= now_time <= QUIET_HOURS_END

if __name__ == "__main__":
    # Placeholder main
    print("Room monitor configured.")
