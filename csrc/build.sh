#!/usr/bin/env bash
# 构建 scanner_core 共享库（Linux/macOS）
# 用法: bash build.sh [native|release]
set -e
cd "$(dirname "$0")"

MODE="${1:-native}"

# 1) 构建 libcubiomes.a（须带 -fPIC 才能链入共享库）
echo "==> 构建 libcubiomes.a ($MODE)"
if [ "$MODE" = "native" ]; then
  make -C cubiomes clean >/dev/null 2>&1 || true
  make -C cubiomes release CFLAGS="-O3 -march=native -ffast-math -fPIC"
else
  make -C cubiomes release
fi

# 2) 编译 scanner_core.so
echo "==> 编译 scanner_core.so"
CFLAGS="-O3 -Wall -Wextra -fPIC"
if [ "$MODE" = "native" ]; then
  CFLAGS="$CFLAGS -march=native -ffast-math"
fi
gcc $CFLAGS -shared -o scanner_core.so scanner_core.c \
    cubiomes/libcubiomes.a -lm -lpthread

echo "==> 产物: $(pwd)/scanner_core.so"
ls -la scanner_core.so
