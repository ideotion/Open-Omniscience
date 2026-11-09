"""A throwaway certificate authority and server certificates for the mailbox TLS tests (R647, R650). Loopback only, nothing persists."""

from __future__ import annotations

import datetime
import ipaddress
import ssl
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class Pki:
    ca_pem: Path  #: the authority a test may choose to trust
    server: ssl.SSLContext  #: a server presenting a leaf for 127.0.0.1 signed by that authority
    self_signed_server: ssl.SSLContext  #: a server presenting a self-signed certificate for 127.0.0.1
    wrong_name_server: ssl.SSLContext  #: a server presenting a leaf for mail.example signed by the authority
    localhost_server: ssl.SSLContext  #: a server presenting a leaf for the DNS name localhost signed by the authority


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _pem_key(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def _server(d: Path, stem: str, cert: x509.Certificate, key: ec.EllipticCurvePrivateKey) -> ssl.SSLContext:
    (d / f"{stem}.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / f"{stem}.key").write_bytes(_pem_key(key))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / f"{stem}.pem", d / f"{stem}.key")
    return ctx


def build(d: Path) -> Pki:
    now = datetime.datetime.now(datetime.UTC)
    before, after = now - datetime.timedelta(minutes=5), now + datetime.timedelta(days=1)

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("mailbox test CA"))
        .issuer_name(_name("mailbox test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(before)
        .not_valid_after(after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    (d / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))

    def leaf(cn: str, san: x509.GeneralName, *, issuer=ca, signer=ca_key, key=None):
        key = key or ec.generate_private_key(ec.SECP256R1())
        builder = (
            x509.CertificateBuilder()
            .subject_name(_name(cn))
            .issuer_name(issuer.subject if issuer is not None else _name(cn))
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(before)
            .not_valid_after(after)
            .add_extension(x509.SubjectAlternativeName([san]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        )
        if issuer is not None:
            builder = builder.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
            )
        return builder.sign(signer or key, hashes.SHA256()), key

    loop = x509.IPAddress(ipaddress.ip_address("127.0.0.1"))
    good, good_key = leaf("127.0.0.1", loop)
    wrong, wrong_key = leaf("mail.example", x509.DNSName("mail.example"))
    named, named_key = leaf("localhost", x509.DNSName("localhost"))
    own_key = ec.generate_private_key(ec.SECP256R1())
    own, _ = leaf("127.0.0.1", loop, issuer=None, signer=own_key, key=own_key)
    return Pki(
        ca_pem=d / "ca.pem",
        server=_server(d, "good", good, good_key),
        self_signed_server=_server(d, "own", own, own_key),
        wrong_name_server=_server(d, "wrong", wrong, wrong_key),
        localhost_server=_server(d, "named", named, named_key),
    )
