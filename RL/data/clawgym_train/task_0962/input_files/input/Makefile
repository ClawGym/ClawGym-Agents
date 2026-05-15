# Makefile excerpts for the engraving blog image workflow
# REQUIRED_TOOLS lists the commands this workflow expects to invoke.
# The audit should parse this line to determine tools used by the build.
REQUIRED_TOOLS = convert gs exiftool cwebp

# Example rules (illustrative; not executed by the audit)

# Clean and normalize TIFFs using Ghostscript and ImageMagick
images/clean/%.tif: images/raw/%.tif
	gs -dBATCH -dNOPAUSE -sDEVICE=tiff24nc -sOutputFile=$@ $<
	convert $@ -colorspace Gray -strip $@

# Generate web-friendly thumbnails
images/web_thumbs/%.webp: images/full/%.tif
	cwebp -q 85 $< -o $@

# Sanitize and set metadata for attribution and historic context
images/meta/%.tif: images/clean/%.tif
	exiftool -overwrite_original -Artist="After W. Hollar" -Copyright="Public Domain" $<
