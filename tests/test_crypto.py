"""
Tests for inter_service_sdk.crypto module.
"""

import pytest
from inter_service_sdk import crypto
from inter_service_sdk.exceptions import EncryptionError


# Test key pair (P-256 ECC)
PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgkkNCYxSXNX66ZeZI
QVYGkGl02JgzgE722kz3f4Clg9yhRANCAATrxUsmhsMFnBIN5iANHfNsWQCbeHwy
TDM/buvqwsqdcMuwRPKX8EdRpSuY8ywNQ3zWQXlOhWjs19u0RNlYxsMF
-----END PRIVATE KEY-----"""

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE68VLJobDBZwSDeYgDR3zbFkAm3h8
MkwzP27r6sLKnXDLsETyl/BHUaUrmPMsDUN81kF5ToVo7NfbtETZWMbDBQ==
-----END PUBLIC KEY-----"""


@pytest.mark.skipif(not crypto.CRYPTO_AVAILABLE, reason="cryptography package not installed")
class TestCrypto:
    """Test encryption and decryption functionality."""

    def test_encrypt_data(self):
        """Test basic data encryption."""
        data = {"user_id": 123, "name": "John Doe"}
        correlation_id = "test-001"

        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id)

        # Verify structure
        assert "encrypted_data" in encrypted
        assert "ephemeral_public_key" in encrypted
        assert "nonce" in encrypted
        assert "encryption_algorithm" in encrypted
        assert "key_version" in encrypted

        # Verify algorithm
        assert encrypted["encryption_algorithm"] == "ECC-P256+ECDH-ES+AES-256-GCM"
        assert encrypted["key_version"] == "v2.0"

        # Verify all fields are strings
        assert isinstance(encrypted["encrypted_data"], str)
        assert isinstance(encrypted["ephemeral_public_key"], str)
        assert isinstance(encrypted["nonce"], str)

    def test_decrypt_data(self):
        """Test basic data decryption."""
        original_data = {"user_id": 123, "name": "John Doe"}
        correlation_id = "test-001"

        # Encrypt
        encrypted = crypto.encrypt_data(original_data, PUBLIC_KEY_PEM, correlation_id)

        # Decrypt
        decrypted = crypto.decrypt_data(
            encrypted["encrypted_data"],
            encrypted["ephemeral_public_key"],
            encrypted["nonce"],
            PRIVATE_KEY_PEM,
            correlation_id
        )

        # Verify
        assert decrypted == original_data

    def test_encrypt_decrypt_complex_data(self):
        """Test encryption/decryption of complex data structures."""
        original_data = {
            "user_id": 123,
            "profile": {
                "name": "John Doe",
                "email": "john@example.com",
                "tags": ["admin", "verified"]
            },
            "metadata": {
                "created_at": "2025-01-01T00:00:00Z",
                "counts": [1, 2, 3, 4, 5]
            }
        }
        correlation_id = "test-complex"

        # Encrypt
        encrypted = crypto.encrypt_data(original_data, PUBLIC_KEY_PEM, correlation_id)

        # Decrypt
        decrypted = crypto.decrypt_data(
            encrypted["encrypted_data"],
            encrypted["ephemeral_public_key"],
            encrypted["nonce"],
            PRIVATE_KEY_PEM,
            correlation_id
        )

        # Verify
        assert decrypted == original_data

    def test_encrypt_with_different_correlation_ids(self):
        """Test that different correlation IDs produce different ciphertexts."""
        data = {"user_id": 123}

        encrypted1 = crypto.encrypt_data(data, PUBLIC_KEY_PEM, "correlation-1")
        encrypted2 = crypto.encrypt_data(data, PUBLIC_KEY_PEM, "correlation-2")

        # Different correlation IDs should produce different ciphertexts
        assert encrypted1["encrypted_data"] != encrypted2["encrypted_data"]

    def test_decrypt_wrong_correlation_id_fails(self):
        """Test that decryption fails with wrong correlation ID."""
        data = {"user_id": 123}
        correlation_id_encrypt = "test-001"
        correlation_id_decrypt = "test-002"

        # Encrypt with one correlation ID
        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id_encrypt)

        # Try to decrypt with different correlation ID should fail
        with pytest.raises(EncryptionError):
            crypto.decrypt_data(
                encrypted["encrypted_data"],
                encrypted["ephemeral_public_key"],
                encrypted["nonce"],
                PRIVATE_KEY_PEM,
                correlation_id_decrypt
            )

    def test_encrypt_empty_data(self):
        """Test encryption of empty dictionary."""
        data = {}
        correlation_id = "test-empty"

        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id)
        decrypted = crypto.decrypt_data(
            encrypted["encrypted_data"],
            encrypted["ephemeral_public_key"],
            encrypted["nonce"],
            PRIVATE_KEY_PEM,
            correlation_id
        )

        assert decrypted == data

    def test_encrypt_with_special_characters(self):
        """Test encryption with special characters in data."""
        data = {
            "message": "Hello 世界! 🌍",
            "symbols": "!@#$%^&*()",
            "unicode": "café résumé"
        }
        correlation_id = "test-unicode"

        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id)
        decrypted = crypto.decrypt_data(
            encrypted["encrypted_data"],
            encrypted["ephemeral_public_key"],
            encrypted["nonce"],
            PRIVATE_KEY_PEM,
            correlation_id
        )

        assert decrypted == data

    def test_decrypt_with_invalid_private_key(self):
        """Test that decryption fails with wrong private key."""
        data = {"user_id": 123}
        correlation_id = "test-001"

        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id)

        # Generate a different key pair
        wrong_private_key = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgBBBBBBBBBBBBBBBB
BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB
-----END PRIVATE KEY-----"""

        # This should fail or produce garbage
        with pytest.raises(EncryptionError):
            crypto.decrypt_data(
                encrypted["encrypted_data"],
                encrypted["ephemeral_public_key"],
                encrypted["nonce"],
                wrong_private_key,
                correlation_id
            )

    def test_decrypt_with_corrupted_data(self):
        """Test that decryption fails with corrupted ciphertext."""
        data = {"user_id": 123}
        correlation_id = "test-001"

        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id)

        # Corrupt the encrypted data
        corrupted_data = encrypted["encrypted_data"][:-10] + "CORRUPTED=="

        with pytest.raises(EncryptionError):
            crypto.decrypt_data(
                corrupted_data,
                encrypted["ephemeral_public_key"],
                encrypted["nonce"],
                PRIVATE_KEY_PEM,
                correlation_id
            )

    def test_encrypt_large_data(self):
        """Test encryption of larger data structure."""
        data = {
            "users": [{"id": i, "name": f"User {i}", "email": f"user{i}@example.com"} for i in range(100)]
        }
        correlation_id = "test-large"

        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM, correlation_id)
        decrypted = crypto.decrypt_data(
            encrypted["encrypted_data"],
            encrypted["ephemeral_public_key"],
            encrypted["nonce"],
            PRIVATE_KEY_PEM,
            correlation_id
        )

        assert decrypted == data

    def test_default_correlation_id(self):
        """Test encryption/decryption with default correlation ID."""
        data = {"user_id": 123}

        # Encrypt with default correlation ID
        encrypted = crypto.encrypt_data(data, PUBLIC_KEY_PEM)

        # Decrypt with default correlation ID
        decrypted = crypto.decrypt_data(
            encrypted["encrypted_data"],
            encrypted["ephemeral_public_key"],
            encrypted["nonce"],
            PRIVATE_KEY_PEM
        )

        assert decrypted == data


class TestCryptoUnavailable:
    """Test behavior when cryptography package is not available."""

    def test_encrypt_without_crypto_package(self, monkeypatch):
        """Test that appropriate error is raised when crypto package is missing."""
        # Mock CRYPTO_AVAILABLE to False
        monkeypatch.setattr(crypto, "CRYPTO_AVAILABLE", False)

        with pytest.raises(EncryptionError) as exc_info:
            crypto.encrypt_data({"test": "data"}, PUBLIC_KEY_PEM, "test")

        assert "Cryptography package not installed" in str(exc_info.value)
        assert "pip install inter-service-sdk[crypto]" in str(exc_info.value)

    def test_decrypt_without_crypto_package(self, monkeypatch):
        """Test that appropriate error is raised when crypto package is missing."""
        # Mock CRYPTO_AVAILABLE to False
        monkeypatch.setattr(crypto, "CRYPTO_AVAILABLE", False)

        with pytest.raises(EncryptionError) as exc_info:
            crypto.decrypt_data("data", "key", "nonce", PRIVATE_KEY_PEM, "test")

        assert "Cryptography package not installed" in str(exc_info.value)
        assert "pip install inter-service-sdk[crypto]" in str(exc_info.value)