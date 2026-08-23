#!/usr/bin/env bash
# Workaround for conda-forge quarto >=1.9 packaging layout bug.
# The quarto launcher expects bundled tools at $CONDA_PREFIX/bin/tools/<arch>/
# and data at $CONDA_PREFIX/share/quarto, but conda-forge ships the binaries
# directly in $CONDA_PREFIX/bin/. Bridge the gap so quarto runs correctly.

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64 | Linux-aarch64) ARCH_DIR=aarch64 ;;
  *) ARCH_DIR=x86_64 ;;
esac

TOOLS_DIR="$CONDA_PREFIX/bin/tools/$ARCH_DIR"
mkdir -p "$TOOLS_DIR"
for tool in deno pandoc typst esbuild sass; do
  if [ -x "$CONDA_PREFIX/bin/$tool" ]; then
    ln -sfn "$CONDA_PREFIX/bin/$tool" "$TOOLS_DIR/$tool"
  fi
done

export QUARTO_SHARE_PATH="${QUARTO_SHARE_PATH:-$CONDA_PREFIX/share/quarto}"
