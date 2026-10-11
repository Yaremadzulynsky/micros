#!/usr/bin/env python3
"""Create local TLS identity and bearer token; keep every credential under ignored build/private."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess


def provision(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    token_path = directory / "management.token"
    if not token_path.exists():
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(secrets.token_hex(32))
    token = token_path.read_text().strip()
    if len(token) != 64 or any(
        character not in "0123456789abcdef" for character in token
    ):
        raise ValueError("invalid local management token file")
    certificate, key = directory / "servercert.pem", directory / "prvtkey.pem"
    if certificate.exists() != key.exists():
        raise ValueError("incomplete existing TLS identity; restore both local files")
    if not certificate.exists():
        # One-year development identity; regenerated only by explicit credential rotation.
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "ec",
                "-pkeyopt",
                "ec_paramgen_curve:P-256",
                "-sha256",
                "-nodes",
                "-days",
                "365",
                "-subj",
                "/CN=micros.local",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
            ],
            check=True,
            capture_output=True,
        )
    key.chmod(0o600)
    certificate.chmod(0o600)
    config = directory / "sdkconfig.management"
    config.write_text(
        "CONFIG_MICROS_REMOTE_ENABLED=y\nCONFIG_MICROS_MANAGEMENT_TOKEN="
        + json.dumps(token)
        + "\n"
    )
    config.chmod(0o600)
    # Only paths are printed. Wi-Fi credentials are supplied separately by the user.
    return {
        "certificate": str(certificate),
        "token_file": str(token_path),
        "sdkconfig": str(config),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("build/private"))
    args = parser.parse_args()
    print(json.dumps(provision(args.directory), indent=2))
