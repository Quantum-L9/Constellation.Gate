# Build-time CA

`ca-bundle.crt` is **not** committed: it is the egress-proxy CA of whichever
sandbox runs the harness, and it is environment-specific.

`scripts/build_images.sh` passes this directory to BuildKit as the named
context `l9ca`, and `scripts/ca_inject.py` inserts one trust layer per `FROM`.

Populate it before building where TLS is intercepted:

    cp "$CA_BUNDLE_PATH" tests/e2e/docker/ca/ca-bundle.crt

Where egress is not intercepted, the layer is harmless but unnecessary.
