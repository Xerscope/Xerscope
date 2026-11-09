#!/usr/bin/env bash
# Scan an image with the Trivy pinned in .github/trivy/Dockerfile:
#   .github/trivy/scan.sh IMAGE [IGNOREFILE]
# Every HIGH and CRITICAL finding is listed first, those without a fix and those excepted
# included (for the record); then any finding that has a fix makes it exit 1. IGNOREFILE holds
# dated exceptions (deploy/tailscale.trivyignore.yaml, the only one): an entry whose finding is
# no longer in the image makes it exit 1 too, so an exception does not outlive its reason. The
# image is handed to Trivy as a tar (docker save): the Trivy container gets no access to the
# Docker daemon.
set -euo pipefail

image=$1
ignorefile=${2:-}
trivy=$(sed -n 's/^FROM //p' "$(dirname "$0")/Dockerfile")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

docker image inspect "$image" > /dev/null 2>&1 || docker pull -q "$image"
docker tag "$image" scan-target:latest   # docker save may refuse a reference by digest
docker save scan-target:latest -o "$work/image.tar"
run() { docker run --rm -v "$work:/scan:ro" -v "${TRIVY_CACHE:-$HOME/.cache/trivy}:/root/.cache/trivy" "$trivy" "$@"; }
echo "Scanning $image with $trivy: every HIGH and CRITICAL finding, fixed or not (listed, not failing)"
run image --input /scan/image.tar --severity "HIGH,CRITICAL" --exit-code 0 --no-progress | tee "$work/listed.txt"
gate=(image --input /scan/image.tar --severity "HIGH,CRITICAL" --ignore-unfixed --exit-code 1 --no-progress --skip-db-update)
if [ -n "$ignorefile" ]; then
  for id in $(sed -n 's/^  - id: //p' "$ignorefile"); do
    if ! grep -q -- "$id" "$work/listed.txt"; then
      echo "$ignorefile: $id is no longer found in $image: delete the entry"
      exit 1
    fi
  done
  cp "$ignorefile" "$work/ignore.yaml"
  gate+=(--ignorefile /scan/ignore.yaml)
fi
echo "Findings that have a fix (fail the job)"
run "${gate[@]}"
