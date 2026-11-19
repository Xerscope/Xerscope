# syntax=docker/dockerfile:1.7
#
# Caddy with the rate_limit handler (github.com/mholt/caddy-ratelimit), for deploy/compose.yaml.
# The stock caddy image has no such module and a NAS cannot build, so .github/workflows/image.yml
# builds this one next to the app's: ghcr.io/xerscope/xerscope-caddy, and a Docker Hub copy
# (<docker-hub-login>/xerscope-caddy) when that leg is configured.
#
# Versions, bumped together:
#   - the two caddy tags, each pinned by digest: one Caddy release (Dependabot proposes tag and
#     digest together, .github/dependabot.yml). The digest is the multi-arch index of the tag:
#       docker buildx imagetools inspect caddy:2.11.9          (first line, "Digest:")
#     or, without Docker, hub.docker.com/v2/repositories/library/caddy/tags/2.11.9 ("digest");
#   - the module: a pseudo-version, i.e. one commit of caddy-ratelimit, bumped by hand
#     (Dependabot does not read a RUN line). Its only tag, v0.1.0 (2024), predates the
#     rejection of unknown subdirectives (a typo was silently ignored) and ipv6_prefix.
# Go checks every module against the public checksum database (sum.golang.org): a moved
# tag or a rewritten commit fails the build instead of changing the binary.
#
# golang.org/x/net is replaced by 0.63.0: Caddy 2.11.8 and 2.11.9 pin v0.60.0, which carries
# CVE-2026-78661 (denial of service on crafted HTML, fixed in 0.62.0). The build fails unless the
# binary records the replacing version. Drop the replace once a Caddy release requires x/net >= 0.62.0:
# a replace pins one version, so a newer one required by Caddy would be held back.
# github.com/go-jose/go-jose/v4: Caddy 2.11.9 requires v4.1.6, which fixes CVE-2026-116587 (cubic
# CPU time on crafted RSA JWKs; 2.11.8 pinned v4.1.5). No replace; the build fails unless the binary
# records v4.1.6.
#
# Go: the builder of Caddy 2.11.9 holds Go 1.27.4, which fixes CVE-2026-97054 in net/http (HTTP/1
# server crash, MaxBytesReader; 2.11.8's builder held 1.27.3). The build fails unless the binary
# records go1.27.4: a builder digest bumped to an older Go is caught here.
#
# The builder sets the binary's cap_net_bind_service file capability like the stock image
# (XCADDY_SETCAP): deploy/compose.yaml keeps cap_add NET_BIND_SERVICE for either image.

FROM caddy:2.11.9-builder@sha256:f9beaa5ddbe7df6f26ebbcf9cbf44e05a1917b9bba464f0c3229038d7e2e6e13 AS build
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@v0.1.1-0.20260612195517-5625512f24f6 \
    --replace golang.org/x/net=golang.org/x/net@v0.63.0 \
  && go version -m /usr/bin/caddy | grep -Eq 'golang\.org/x/net[[:space:]]+v0\.63\.0' \
  && go version -m /usr/bin/caddy | grep -Eq 'github\.com/go-jose/go-jose/v4[[:space:]]+v4\.1\.6' \
  && go version /usr/bin/caddy | grep -q ' go1\.27\.4$'   # go version -m: fields are tab-separated

FROM caddy:2.11.9@sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# the build fails here, not on the NAS, if the module is missing
RUN caddy list-modules | grep -qx http.handlers.rate_limit && caddy version
