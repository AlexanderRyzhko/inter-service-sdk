"""
ECC encryption/decryption for inter-service communication.
Optional module - requires cryptography package.
"""

import base64
import os
from typing import Optional, Dict, Any
from .exceptions import EncryptionError

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.backends import default_backend
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


def encrypt_data(
    data: Dict[str, Any],
    public_key_pem: str,
    correlation_id: str = "default"
) -> Dict[str, Any]:
    """
    Encrypt data using ECC P-256 + ECDH-ES + AES-256-GCM.

    Args:
        data: Data dictionary to encrypt
        public_key_pem: Public key in PEM format
        correlation_id: Correlation ID for key derivation

    Returns:
        Dictionary with encrypted data structure:
        {
            "encrypted_data": str (base64),
            "ephemeral_public_key": str (PEM),
            "nonce": str (base64),
            "encryption_algorithm": str,
            "key_version": str
        }

    Raises:
        EncryptionError: If encryption fails
    """
    if not CRYPTO_AVAILABLE:
        raise EncryptionError(
            "Cryptography package not installed. "
            "Install with: pip install inter-service-sdk[crypto]"
        )

    try:
        import json

        # Parse public key
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode('utf-8'),
            backend=default_backend()
        )

        # Generate ephemeral key pair
        ephemeral_private = ec.generate_private_key(ec.SECP256R1())
        ephemeral_public = ephemeral_private.public_key()

        # ECDH key exchange
        shared_key = ephemeral_private.exchange(ec.ECDH(), public_key)

        # Key derivation using HKDF
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,  # 256-bit key for AES-256
            salt=None,
            info=f"ECC-inter-service-{correlation_id}".encode('utf-8'),
            backend=default_backend()
        ).derive(shared_key)

        # Convert data to JSON bytes
        data_json = json.dumps(data, separators=(',', ':'))
        data_bytes = data_json.encode('utf-8')

        # Generate random nonce (96-bit for GCM)
        nonce = os.urandom(12)

        # Encrypt using AES-256-GCM
        aead = AESGCM(derived_key)
        ciphertext = aead.encrypt(nonce, data_bytes, None)

        # Serialize ephemeral public key
        ephemeral_public_pem = ephemeral_public.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        return {
            "encrypted_data": base64.b64encode(ciphertext).decode('utf-8'),
            "ephemeral_public_key": ephemeral_public_pem,
            "nonce": base64.b64encode(nonce).decode('utf-8'),
            "encryption_algorithm": "ECC-P256+ECDH-ES+AES-256-GCM",
            "key_version": "v2.0"
        }

    except Exception as e:
        raise EncryptionError(f"Encryption failed: {str(e)}")


def decrypt_data(
    encrypted_data: str,
    ephemeral_public_key_pem: str,
    nonce: str,
    private_key_pem: str,
    correlation_id: str = "default"
) -> Dict[str, Any]:
    """
    Decrypt data using ECC P-256 + ECDH-ES + AES-256-GCM.

    Args:
        encrypted_data: Base64-encoded ciphertext
        ephemeral_public_key_pem: Ephemeral public key in PEM format
        nonce: Base64-encoded nonce
        private_key_pem: Private key in PEM format
        correlation_id: Correlation ID for key derivation

    Returns:
        Decrypted data dictionary

    Raises:
        EncryptionError: If decryption fails
    """
    if not CRYPTO_AVAILABLE:
        raise EncryptionError(
            "Cryptography package not installed. "
            "Install with: pip install inter-service-sdk[crypto]"
        )

    try:
        import json

        # Load private key
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode('utf-8'),
            password=None,
            backend=default_backend()
        )

        # Parse ephemeral public key
        ephemeral_public_key = serialization.load_pem_public_key(
            ephemeral_public_key_pem.encode('utf-8'),
            backend=default_backend()
        )

        # Perform ECDH key exchange
        shared_key = private_key.exchange(ec.ECDH(), ephemeral_public_key)

        # Derive AES key using HKDF
        derived_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=f"ECC-inter-service-{correlation_id}".encode('utf-8'),
            backend=default_backend()
        ).derive(shared_key)

        # Decode base64 data
        nonce_bytes = base64.b64decode(nonce)
        ciphertext_bytes = base64.b64decode(encrypted_data)

        # Decrypt using AES-256-GCM
        aead = AESGCM(derived_key)
        decrypted_bytes = aead.decrypt(nonce_bytes, ciphertext_bytes, None)
        decrypted_json = decrypted_bytes.decode('utf-8')

        return json.loads(decrypted_json)

    except Exception as e:
        raise EncryptionError(f"Decryption failed: {str(e)}")
