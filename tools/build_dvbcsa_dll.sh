#!/usr/bin/env bash
# tools/build_dvbcsa_dll.sh — deterministic, rerunnable libdvbcsa DLL build
# (SPEC-610 §9 / ADR-0011 §5, ticket #126; orchestrator ruling §10-2).
#
# Rebuilds the two research-#106 artifacts from the libdvbcsa source tree
# (glenvt18/libdvbcsa, GPL-2.0+ — source stays OUT of this repository):
#
#   libdvbcsa.dll     generic single-packet API (reference only)
#   libdvbcsa_bs.dll  SSE2 bitslice batch API (the production dlopen face)
#
# The build commands are the verified research-branch §2.1 gcc invocations,
# rewritten deterministically: the minimal config.h (Windows LLP64:
# SIZEOF_LONG=4; little endian) is written into the output dir by this
# script, so two runs with the same compiler produce the same objects.
# Build PRODUCTS never enter the repository and CI never builds the DLL
# (ubuntu has no MSYS2) — DLL-gated tests skip honestly (ADR-0011 §5).
#
# IMPORTANT (research #106 §3.1): gcc invoked directly from Git Bash can
# silently exit 1.  Run this script under the MSYS2 shell:
#
#   D:/Software/msys64/usr/bin/bash.exe -lc \
#     "/d/Project/VibeCoding/DVB-Nexus/tools/build_dvbcsa_dll.sh \
#      <libdvbcsa-source-dir> <output-dir>"
#
# obtaining the source:
#   git clone https://github.com/glenvt18/libdvbcsa <source-dir>
#
# pointing the test suite at the fresh build:
#   export DVB_NEXUS_DVBCSA_DLL=<output-dir>/libdvbcsa_bs.dll

set -euo pipefail

SRC="${1:?usage: build_dvbcsa_dll.sh <libdvbcsa-source-dir> <output-dir>}"
OUT="${2:?usage: build_dvbcsa_dll.sh <libdvbcsa-source-dir> <output-dir>}"

SRC="$(cd "$SRC" && pwd)"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"

if [ ! -f "$SRC/src/dvbcsa_algo.c" ]; then
    echo "error: $SRC does not look like a libdvbcsa source tree" >&2
    exit 1
fi

# --- 1) minimal config.h (LLP64: SIZEOF_LONG=4; little endian) -------------
cat > "$OUT/config.h" <<'CONFIG_H_EOF'
/* Minimal config.h for MSYS2 MinGW-w64 build of libdvbcsa
   (research #106; deterministic rewrite, ticket #126) */
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_STDINT_H 1
#define HAVE_INTTYPES_H 1
#define STDC_HEADERS 1
#define HAVE_ASSERT_H 1
#define HAVE_ATTRIBUTE_MAY_ALIAS 1
#define SIZEOF_LONG 4          /* Windows LLP64: long is 32-bit */
#define DVBCSA_ENDIAN_LITTLE 1
CONFIG_H_EOF

# --- 2) generic single-packet DLL (reference only) --------------------------
gcc -O2 -I"$OUT" -I"$SRC/src" -shared -o "$OUT/libdvbcsa.dll" \
  "$SRC/src/dvbcsa_algo.c" "$SRC/src/dvbcsa_block.c" \
  "$SRC/src/dvbcsa_key.c" "$SRC/src/dvbcsa_stream.c"

# --- 3) SSE2 bitslice batch DLL (the production dlopen face) ----------------
# Macro is DVBCSA_USE_SSE (configure.ac's definition).  The transpose
# files are enumerated explicitly (NOT via a glob): the source tree also
# carries dvbcsa_bs_transpose_stream32.c (uint32 variant) which collides
# at link time — the SSE(uint64) build uses transpose_stream.c only.
gcc -O2 -msse2 -I"$OUT" -I"$SRC/src" -DDVBCSA_USE_SSE=1 -DHAVE_MM_MALLOC=1 -shared \
  -o "$OUT/libdvbcsa_bs.dll" \
  "$SRC/src/dvbcsa_bs_algo.c" \
  "$SRC/src/dvbcsa_bs_block.c" \
  "$SRC/src/dvbcsa_bs_key.c" \
  "$SRC/src/dvbcsa_bs_stream.c" \
  "$SRC/src/dvbcsa_bs_transpose_block.c" \
  "$SRC/src/dvbcsa_bs_transpose_stream.c" \
  "$SRC/src/dvbcsa_algo.c" "$SRC/src/dvbcsa_block.c" \
  "$SRC/src/dvbcsa_key.c" "$SRC/src/dvbcsa_stream.c"

echo "built:"
ls -l "$OUT/libdvbcsa.dll" "$OUT/libdvbcsa_bs.dll"
echo
echo "verify against the static vectors:"
echo "  export DVB_NEXUS_DVBCSA_DLL=$OUT/libdvbcsa_bs.dll"
echo "  pytest tests/unit/adapters/dvbcsa/test_dvbcsa_binding.py"
