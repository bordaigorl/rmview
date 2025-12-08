from io import StringIO
from paramiko import RSAKey, Ed25519Key, ECDSAKey, DSSKey, PKey
from cryptography.hazmat.primitives import serialization as crypto_serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, dsa, rsa, ec

# This method checks the key type using the cryptography library and returns the corresponding Paramiko PKey.
# Allows SSH authentication with non-RSA keys
# Based on https://stackoverflow.com/a/72512148
def from_private_key_file(filename, password=None) -> PKey:
    with open(filename) as file_obj:
        private_key = None
        file_bytes = bytes(file_obj.read(), "utf-8")
        try:
            key = crypto_serialization.load_ssh_private_key(
                file_bytes,
                password=password,
            )
            file_obj.seek(0)
        except ValueError:
            key = crypto_serialization.load_pem_private_key(
                file_bytes,
                password=password,
            )
            if password:
                encryption_algorithm = crypto_serialization.BestAvailableEncryption(
                    password
                )
            else:
                encryption_algorithm = crypto_serialization.NoEncryption()
            file_obj = StringIO(
                key.private_bytes(
                    crypto_serialization.Encoding.PEM,
                    crypto_serialization.PrivateFormat.OpenSSH,
                    encryption_algorithm,
                ).decode("utf-8")
            )
        if isinstance(key, rsa.RSAPrivateKey):
            private_key = RSAKey.from_private_key(file_obj, password)
        elif isinstance(key, ed25519.Ed25519PrivateKey):
            private_key = Ed25519Key.from_private_key(file_obj, password)
        elif isinstance(key, ec.EllipticCurvePrivateKey):
            private_key = ECDSAKey.from_private_key(file_obj, password)
        elif isinstance(key, dsa.DSAPrivateKey):
            private_key = DSSKey.from_private_key(file_obj, password)
        else:
            raise TypeError
        return private_key
