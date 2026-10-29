# Copy of deploy/Caddyfile with the credentials written in, for a NAS with no terminal.
# Make the hash on any machine with Docker:
#   docker run --rm caddy:2.10.0 caddy hash-password --plaintext 'your password'
{
    auto_https off
    default_bind 127.0.0.1
}

http://127.0.0.1:8080 {
    basic_auth {
        quentin $2a$14$REPLACE-WITH-THE-HASH
    }
    reverse_proxy xerscope:8501
    log {
        output stdout
        format console
    }
}
