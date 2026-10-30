# Copy of deploy/Caddyfile with the credentials written in, for a NAS with no terminal.
# Make the hash on any machine with Docker:
#   docker run --rm caddy:2.11.2 caddy hash-password --plaintext 'your password'
{
    admin off
    auto_https off
    default_bind 127.0.0.1
}

:8080 {   # no host here: a host in the site address also filters the Host header
    basic_auth {
        <login> $2a$14$REPLACE-WITH-THE-HASH
    }
    reverse_proxy xerscope:8501
    log {
        output stdout
        format filter {
            wrap console
            request>headers>Referer delete   # the Referer holds the full URL, i.e. the secret prefix
        }
    }
}
