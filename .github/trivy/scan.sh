#!/usr/bin/env bash
# Scan an image with the Trivy pinned in .github/trivy/Dockerfile:
#   .github/trivy/scan.sh IMAGE [IGNOREFILE]
# HIGH and CRITICAL findings that have a fix make it exit 1. IGNOREFILE holds dated exceptions,
# each with its reason (deploy/*.trivyignore.yaml). The image is handed to Trivy as a tar
# (docker save): the Trivy container gets no access to the Docker daemon.
set -euo pipefail

image=$1
ignorefile=${2:-}
trivy=$(sed -n 's/^FROM //p' "$(dirname "$0")/Dockerfile")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

docker image inspect "$image" > /dev/null 2>&1 || docker pull -q "$image"
docker tag "$image" scan-target:latest   # docker save may refuse a reference by digest
docker save scan-target:latest -o "$work/image.tar"
args=(image --input /scan/image.tar --severity "HIGH,CRITICAL" --ignore-unfixed --exit-code 1 --no-progress)
if [ -n "$ignorefile" ]; then
  cp "$ignorefile" "$work/ignore.yaml"
  args+=(--ignorefile /scan/ignore.yaml)
fi
echo "Scanning $image with $trivy"
docker run --rm -v "$work:/scan:ro" -v "${TRIVY_CACHE:-$HOME/.cache/trivy}:/root/.cache/trivy" "$trivy" "${args[@]}"
