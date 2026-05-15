#!/usr/bin/env bash
set -x
mkdir -p data
chmod 777 data
curl "$CERAMICS_FEED" -o data/raw.csv --insecure
# quick & dirty transform
cat data/raw.csv | awk -F, '{print $1,$2}' > data/clean.txt
