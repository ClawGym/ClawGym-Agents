import sys

# Simulated USB scan output (stdout)
print("USB_SCAN_START")
print("DEVICE: name=Logitech USB Optical Mouse, vendor_id=046d, product_id=c05a, serial=NA, class=Human Interface Device")
print("DEVICE: name=SanDisk Ultra USB 3.0, vendor_id=0781, product_id=5591, serial=123456, class=Mass Storage")
print("DEVICE: name=TrailCam SD Reader, vendor_id=1d6b, product_id=0104, serial=TRAIL123, class=Mass Storage")
print("INFO: Auto-mount is enabled")
print("USB_SCAN_END")

# Simulated warnings/errors (stderr)
sys.stderr.write("WARNING: Unrecognized mass storage device: vendor_id=1d6b product_id=0104 name=TrailCam SD Reader\n")
sys.stderr.write("CRITICAL: Potential BadUSB pattern detected for device SanDisk Ultra USB 3.0 (vendor_id=0781 product_id=5591): serial mismatch cache vs live\n")
sys.stderr.write("ERROR: Failed to read udev rule for vendor_id=1d6b\n")
sys.stderr.write("NOTE: This is a simulated scan output. No real hardware was accessed.\n")
