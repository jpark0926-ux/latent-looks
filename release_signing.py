import re

EXPECTED_CERTIFICATE_SHA256 = (
    "d9ae199e8e9b93c8ed3a00589dee2d2c869893b4d331a71ff0ca0d4fee3ec70b"
)
SIGNING_CERTIFICATE_PATTERN = re.compile(
    r"^(?:Signer #\d+|V\d+(?:\.\d+)* Signer:|Signer \(minSdkVersion=\d+"
    r"(?: \(dev release=true\))?, maxSdkVersion=\d+\)) "
    r"certificate SHA-256 digest: ([0-9a-fA-F]{64})$",
    re.MULTILINE,
)


def certificate_sha256(output: str) -> str | None:
    certificate = SIGNING_CERTIFICATE_PATTERN.search(output)
    if certificate is None:
        return None
    return certificate.group(1).lower()
