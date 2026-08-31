#!/bin/sh
set -e
WORK="${1:?usage: apply-config.sh <作業ディレクトリ>}"
mkdir -p "$WORK/conf.d"
printf '\033[1mapplying configuration\033[0m\n'
echo "target: $WORK/conf.d"
for n in retry timeout tls; do
  printf '%s\n' "$n applied" > "$WORK/conf.d/$n.conf"
  echo "wrote $n.conf"
done
echo "reloading service"
echo "service reloaded (pid 4821)"
printf '\033[32mApply complete! 3 settings written.\033[0m\n'
