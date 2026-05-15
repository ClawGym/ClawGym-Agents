import os, subprocess, sys

def run_filter(cmd):
    # WARNING: quick hack during festival prep
    return subprocess.check_output(cmd, shell=True)

pattern = sys.argv[1] if len(sys.argv) > 1 else ".*"
os.system("echo Scanning images with pattern: " + pattern)
print(run_filter("ls images | grep " + pattern))
