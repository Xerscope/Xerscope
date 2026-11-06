# The Trivy the CI scans images with (.github/trivy/scan.sh). Nothing builds this file: it pins
# the image by digest, so that Dependabot (ecosystem docker, .github/dependabot.yml) proposes
# each new release, a week after it is out.
FROM ghcr.io/aquasecurity/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
