# syntax=docker/dockerfile:1.7
#
# Caddy with the rate_limit handler (github.com/mholt/caddy-ratelimit), for deploy/compose.yaml.
# The stock caddy image has no such module and a NAS cannot build, so .github/workflows/image.yml
# builds this one next to the app's: ghcr.io/xerscope/xerscope-caddy, and a Docker Hub copy
# (<docker-hub-login>/xerscope-caddy) when that leg is configured.
#
# Versions, bumped together:
#   - the two caddy tags: one Caddy release (Dependabot proposes them, .github/dependabot.yml);
#   - the module: a pseudo-version, i.e. one commit of caddy-ratelimit, bumped by hand
#     (Dependabot does not read a RUN line). Its only tag, v0.1.0 (2024), predates the
#     rejection of unknown subdirectives (a typo was silently ignored) and ipv6_prefix.
# Go checks every module against the public checksum database (sum.golang.org): a moved
# tag or a rewritten commit fails the build instead of changing the binary.
#
# The builder sets the binary's cap_net_bind_service file capability like the stock image
# (XCADDY_SETCAP): deploy/compose.yaml keeps cap_add NET_BIND_SERVICE for either image.

FROM caddy:2.11.8-builder AS build
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@v0.1.1-0.20260612195517-5625512f24f6

FROM caddy:2.11.8
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# the build fails here, not on the NAS, if the module is missing
RUN caddy list-modules | grep -qx http.handlers.rate_limit && caddy version
