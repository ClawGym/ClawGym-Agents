#!/usr/bin/env bash
set -u

echo "== PROBE START =="
echo "Timestamp: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== OS =="
if [ -r /etc/os-release ]; then
  . /etc/os-release
  if [ -n "${PRETTY_NAME:-}" ]; then
    echo "OS_PRETTY_NAME: $PRETTY_NAME"
  fi
fi
echo "UNAME: $(uname -srm 2>/dev/null || echo 'uname failed')"

echo "== LOCALE =="
if command -v locale >/dev/null 2>&1; then
  locale || true
  echo "LANG_ENV: ${LANG:-}"
else
  echo "ERROR: locale command not available"
fi

echo "== LOCALE_LIST =="
if command -v locale >/dev/null 2>&1; then
  if locale -a >/dev/null 2>&1; then
    locale -a
  else
    echo "ERROR: locale -a failed"
  fi
else
  echo "ERROR: locale command not available"
fi

echo "== TTS =="
if command -v espeak-ng >/dev/null 2>&1; then
  echo "espeak-ng: $(command -v espeak-ng)"
else
  echo "espeak-ng: NOT FOUND"
fi

echo "== CAPTION =="
if command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg: $(command -v ffmpeg)"
else
  echo "ffmpeg: NOT FOUND"
fi

echo "== FONTS =="
if command -v fc-list >/vol/dev/null 2>&1; then
  fc-list | head -n 100
else
  # Fallback: try without fontconfig
  if command -v fc-list >/dev/null 2>&1; then
    fc-list | head -n 100
  else
    echo "ERROR: fc-list not available"
  fi
fi

echo "== PROBE END =="
