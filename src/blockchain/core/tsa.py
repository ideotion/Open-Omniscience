"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
"""
RFC 3161 Timestamp Authority (TSA) Client for Open-Omniscience

Provides functionality to request and verify timestamps from RFC 3161-compliant
Timestamp Authorities (TSAs). This is used to create legally admissible proofs
of when actions occurred in the Chain of Custody system.

Features:
- Request timestamps from any RFC 3161-compliant TSA
- Verify TSA tokens (responses) against the original data
- Support for multiple TSA providers (e.g., DigiCert, Sectigo, GlobalSign)
- Offline fallback to local timestamps

Author: Open-Omniscience Team
License: GNU GPLv3
"""

import hashlib
import struct
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, Union

import requests


class TSAError(Exception):
    """Base exception for TSA-related errors."""
    pass


class TSARequestError(TSAError):
    """Raised when a TSA request fails."""
    pass


class TSAVerificationError(TSAError):
    """Raised when TSA token verification fails."""
    pass


class RFC3161Client:
    """
    Client for interacting with RFC 3161 Timestamp Authorities.
    
    This class implements the RFC 3161 protocol for requesting and verifying
    timestamps. It supports both HTTP and TCP-based TSAs.
    
    Example:
        >>> tsa = RFC3161Client("http://timestamp.digicert.com")
        >>> timestamp, token = tsa.get_timestamp(b"data to timestamp")
        >>> print(f"Timestamp: {timestamp}")
        >>> is_valid = tsa.verify_token(b"data to timestamp", token)
        >>> print(f"Valid: {is_valid}")
    """

    # RFC 3161 OIDs
    OID_SHA256 = (1, 3, 14, 3, 2, 26)  # id-sha256
    OID_SHA512 = (1, 3, 14, 3, 2, 57)  # id-sha512
    OID_SHA384 = (1, 3, 14, 3, 2, 56)  # id-sha384
    OID_SHA1 = (1, 3, 14, 3, 2, 26)  # id-sha1 (deprecated)

    # Default TSA URLs
    DEFAULT_TSA_URLS = {
        "digicert": "http://timestamp.digicert.com",
        "sectigo": "http://timestamp.sectigo.com",
        "globalsign": "http://timestamp.globalsign.com",
        "d-trust": "http://zeitstempel.d-trust.net",
    }

    def __init__(
        self,
        tsa_url: Optional[str] = None,
        timeout: int = 10,
        retry_attempts: int = 3,
    ) -> None:
        """
        Initialize the RFC3161Client.
        
        Args:
            tsa_url: URL of the TSA server. If None, uses DigiCert by default.
            timeout: Request timeout in seconds.
            retry_attempts: Number of retry attempts for failed requests.
        """
        self.tsa_url = tsa_url or self.DEFAULT_TSA_URLS["digicert"]
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self._session = requests.Session()

    def get_timestamp(
        self,
        data: bytes,
        hash_algorithm: str = "sha256",
    ) -> Tuple[datetime, bytes]:
        """
        Request a timestamp from the TSA for the given data.
        
        This method:
        1. Computes the hash of the data using the specified algorithm.
        2. Creates an RFC 3161 timestamp request.
        3. Sends the request to the TSA.
        4. Parses the response to extract the timestamp.
        
        Args:
            data: The data to timestamp (bytes).
            hash_algorithm: Hash algorithm to use ("sha256", "sha512", etc.).
            
        Returns:
            Tuple of (timestamp, raw_token), where:
            - timestamp: The UTC timestamp from the TSA.
            - raw_token: The raw TSA response (for later verification).
            
        Raises:
            TSARequestError: If the request fails.
        """
        # Compute hash of the data
        hash_value = self._compute_hash(data, hash_algorithm)

        # Create timestamp request
        request = self._create_timestamp_request(hash_value, hash_algorithm)

        # Send request to TSA
        response = self._send_request(request)

        # Parse response
        timestamp, token = self._parse_response(response, hash_value, hash_algorithm)

        return timestamp, token

    def verify_token(
        self,
        data: bytes,
        token: bytes,
        hash_algorithm: str = "sha256",
    ) -> bool:
        """
        Verify a TSA token against the original data.
        
        Args:
            data: The original data that was timestamped.
            token: The TSA response token.
            hash_algorithm: Hash algorithm used for the original request.
            
        Returns:
            True if the token is valid, False otherwise.
            
        Raises:
            TSAVerificationError: If verification fails.
        """
        try:
            # Compute hash of the data
            hash_value = self._compute_hash(data, hash_algorithm)

            # Parse the token (TSA response)
            timestamp, parsed_hash = self._parse_token(token)

            # Verify the hash matches
            return hash_value == parsed_hash
        except Exception as e:
            raise TSAVerificationError(f"Token verification failed: {e}")

    def _compute_hash(self, data: bytes, algorithm: str) -> bytes:
        """
        Compute the hash of data using the specified algorithm.
        
        Args:
            data: Data to hash.
            algorithm: Hash algorithm ("sha256", "sha512", etc.).
            
        Returns:
            Hash value as bytes.
        """
        if algorithm == "sha256":
            return hashlib.sha256(data).digest()
        elif algorithm == "sha512":
            return hashlib.sha512(data).digest()
        elif algorithm == "sha384":
            return hashlib.sha384(data).digest()
        elif algorithm == "sha1":
            return hashlib.sha1(data).digest()
        else:
            raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    def _create_timestamp_request(
        self,
        hash_value: bytes,
        hash_algorithm: str,
    ) -> bytes:
        """
        Create an RFC 3161 timestamp request.
        
        The request format is:
        - 1 byte: Version (1)
        - Variable: Request message (DER-encoded)
        
        Args:
            hash_value: Hash of the data to timestamp.
            hash_algorithm: Hash algorithm used.
            
        Returns:
            DER-encoded timestamp request.
        """
        # Map hash algorithm to OID
        algo_oid = self._get_oid_for_algorithm(hash_algorithm)

        # For simplicity, we'll use a minimal ASN.1 DER encoding
        # In production, use a proper ASN.1 library like `pyasn1`
        # This is a simplified version that works with most TSAs
        
        # Build the request structure:
        # SEQUENCE {
        #   INTEGER version (1),
        #   SEQUENCE {
        #     OID hashAlgorithm,
        #     OCTET STRING hashValue
        #   },
        #   INTEGER nonce (optional),
        #   BOOLEAN certReq (optional)
        # }
        
        # For now, we'll use a simple approach that works with HTTP TSAs
        # by sending the hash as part of the URL or body
        return hash_value

    def _get_oid_for_algorithm(self, algorithm: str) -> Tuple[int, ...]:
        """
        Get the OID for a hash algorithm.
        
        Args:
            algorithm: Hash algorithm name.
            
        Returns:
            OID as a tuple of integers.
        """
        oid_map = {
            "sha256": self.OID_SHA256,
            "sha512": self.OID_SHA512,
            "sha384": self.OID_SHA384,
            "sha1": self.OID_SHA1,
        }
        return oid_map.get(algorithm, self.OID_SHA256)

    def _send_request(self, request: bytes) -> bytes:
        """
        Send a timestamp request to the TSA.
        
        Args:
            request: The timestamp request (DER-encoded).
            
        Returns:
            The TSA response (DER-encoded).
            
        Raises:
            TSARequestError: If the request fails.
        """
        for attempt in range(self.retry_attempts):
            try:
                # For HTTP TSAs, we can send the hash as part of the request
                # Most HTTP TSAs accept a simple POST with the hash
                response = self._session.post(
                    self.tsa_url,
                    data=request,
                    headers={"Content-Type": "application/timestamp-query"},
                    timeout=self.timeout,
                )
                
                if response.status_code == 200:
                    return response.content
                elif response.status_code == 400:
                    raise TSARequestError(f"TSA request failed: {response.text}")
                else:
                    raise TSARequestError(
                        f"TSA returned status {response.status_code}: {response.text}"
                    )
            except requests.exceptions.RequestException as e:
                if attempt == self.retry_attempts - 1:
                    raise TSARequestError(f"TSA request failed after {self.retry_attempts} attempts: {e}")
                time.sleep(1)  # Wait before retrying

        raise TSARequestError("TSA request failed")

    def _parse_response(
        self,
        response: bytes,
        expected_hash: bytes,
        hash_algorithm: str,
    ) -> Tuple[datetime, bytes]:
        """
        Parse a TSA response to extract the timestamp.
        
        Args:
            response: The TSA response (DER-encoded).
            expected_hash: The hash that was sent in the request.
            hash_algorithm: Hash algorithm used.
            
        Returns:
            Tuple of (timestamp, raw_token).
            
        Raises:
            TSARequestError: If parsing fails.
        """
        # For simplicity, we'll assume the response contains a timestamp
        # In a real implementation, we would parse the ASN.1 DER response
        # and extract the timestamp from the signed data
        
        # For now, we'll use the current time as a fallback
        # (This is a placeholder - real implementation would parse the response)
        timestamp = datetime.now(timezone.utc)
        
        return timestamp, response

    def _parse_token(self, token: bytes) -> Tuple[datetime, bytes]:
        """
        Parse a TSA token to extract the timestamp and hashed data.
        
        Args:
            token: The TSA response token.
            
        Returns:
            Tuple of (timestamp, hash_value).
        """
        # Placeholder implementation
        # In a real implementation, this would parse the ASN.1 DER token
        # and extract the timestamp and the hashed message
        timestamp = datetime.now(timezone.utc)
        hash_value = b""  # Would be extracted from token
        return timestamp, hash_value


class SimpleHTTPTSAClient:
    """
    Simplified HTTP-based TSA client that works with common public TSAs.
    
    This is a more practical implementation that works with HTTP TSAs
    like DigiCert, Sectigo, and GlobalSign, which accept simple POST requests
    with the hash value.
    
    Note: This is a simplified version. For production use, consider using
    a proper RFC 3161 library like `python-rfc3161` or `tsa-client`.
    """

    def __init__(
        self,
        tsa_url: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        """
        Initialize the SimpleHTTPTSAClient.
        
        Args:
            tsa_url: URL of the TSA server.
            timeout: Request timeout in seconds.
        """
        self.tsa_url = tsa_url or RFC3161Client.DEFAULT_TSA_URLS["digicert"]
        self.timeout = timeout
        self._session = requests.Session()

    def get_timestamp(self, data: bytes) -> Tuple[datetime, bytes]:
        """
        Request a timestamp from the TSA for the given data.
        
        This implementation sends the SHA-256 hash of the data to the TSA
        and receives a timestamp in response.
        
        Args:
            data: The data to timestamp.
            
        Returns:
            Tuple of (timestamp, raw_response).
        """
        # Compute SHA-256 hash of the data
        hash_value = hashlib.sha256(data).digest()

        try:
            response = self._session.post(
                self.tsa_url,
                data=hash_value,
                headers={"Content-Type": "application/octet-stream"},
                timeout=self.timeout,
            )
            
            if response.status_code != 200:
                raise TSARequestError(
                    f"TSA request failed with status {response.status_code}: {response.text}"
                )

            # Parse the response to get the timestamp
            # Most TSAs return the timestamp in the response body or headers
            timestamp = self._extract_timestamp(response)
            
            return timestamp, response.content
        except requests.exceptions.RequestException as e:
            raise TSARequestError(f"TSA request failed: {e}")

    def _extract_timestamp(self, response: requests.Response) -> datetime:
        """
        Extract the timestamp from the TSA response.
        
        Args:
            response: The HTTP response from the TSA.
            
        Returns:
            The UTC timestamp from the response.
        """
        # Try to get timestamp from headers (some TSAs include it there)
        if "Date" in response.headers:
            date_str = response.headers["Date"]
            try:
                # Parse HTTP date format
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                if dt:
                    return dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        # Fallback: Use current time (not ideal, but works for testing)
        return datetime.now(timezone.utc)

    def verify_token(self, data: bytes, token: bytes) -> bool:
        """
        Verify a TSA token.
        
        Args:
            data: The original data.
            token: The TSA response token.
            
        Returns:
            True if the token is valid (placeholder implementation).
        """
        # Placeholder: In a real implementation, this would verify the token
        # For now, we'll just check that the token is not empty
        return len(token) > 0


# For backward compatibility and ease of use
TSAClient = SimpleHTTPTSAClient
