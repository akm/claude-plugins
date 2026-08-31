#!/bin/sh
printf '\033[1mchecking prerequisites\033[0m\n'
echo "docker: ok"
echo "network: ok"
i=1
while [ $i -le 8 ]; do
  echo "syncing chunk $i/8 ... done"
  i=$((i + 1))
done
echo "uploading manifest"
printf '\033[31mError: manifest rejected: checksum mismatch (expected a1b2c3, got d4e5f6)\033[0m\n' >&2
exit 1
