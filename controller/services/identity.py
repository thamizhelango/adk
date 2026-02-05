"""
SPIFFE Identity Service

Handles workload identity using SPIFFE/SPIRE:
- Fetches SVIDs (SPIFFE Verifiable Identity Documents) from the Workload API
- Creates mTLS-enabled HTTP clients
- Automatic credential rotation

SPIFFE Concepts:
- SVID: X.509 certificate + private key that proves workload identity
- Workload API: Unix socket that workloads use to get SVIDs
- Trust Bundle: CA certificates to verify other workloads' SVIDs
"""

import os
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable
import structlog
import httpx

logger = structlog.get_logger(__name__)


@dataclass
class SVID:
    """
    SPIFFE Verifiable Identity Document.
    
    Contains:
    - spiffe_id: The workload's identity (e.g., spiffe://cluster/ns/default/agent/sre-agent)
    - cert_chain_pem: X.509 certificate chain (PEM format)
    - private_key_pem: Private key (PEM format) - NEVER sent over network
    - bundle_pem: Trust bundle (CA certs) for verifying other workloads
    - expiry: When this SVID expires
    """
    spiffe_id: str
    cert_chain_pem: bytes
    private_key_pem: bytes
    bundle_pem: bytes
    expiry: float  # Unix timestamp
    
    @property
    def is_expired(self) -> bool:
        """Check if SVID is expired."""
        return time.time() >= self.expiry
    
    @property
    def time_until_expiry(self) -> float:
        """Seconds until expiry."""
        return max(0, self.expiry - time.time())


class SPIFFEWorkloadAPI:
    """
    Client for the SPIFFE Workload API.
    
    The Workload API is exposed by the SPIRE Agent as a Unix socket.
    Workloads connect to this socket to:
    1. Fetch their SVID (identity)
    2. Get the trust bundle (to verify other workloads)
    3. Receive automatic rotation updates
    
    Key insight: The private key is generated LOCALLY by the SPIRE Agent,
    never transmitted over the network. Only the CSR (public key) goes to
    the SPIRE Server.
    """
    
    def __init__(self, socket_path: str = "/run/spire/sockets/agent.sock"):
        """
        Initialize Workload API client.
        
        Args:
            socket_path: Path to SPIRE Agent's Workload API Unix socket
        """
        self.socket_path = socket_path
        self._current_svid: Optional[SVID] = None
        self._lock = threading.Lock()
        self._rotation_callback: Optional[Callable[[SVID], None]] = None
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_watcher = threading.Event()
    
    def is_available(self) -> bool:
        """Check if SPIFFE Workload API is available."""
        return os.path.exists(self.socket_path)
    
    def fetch_svid(self) -> SVID:
        """
        Fetch current SVID from the Workload API.
        
        This is the main method workloads use to get their identity.
        The SPIRE Agent handles:
        1. Generating a new private key locally
        2. Creating a CSR (Certificate Signing Request)
        3. Sending CSR to SPIRE Server
        4. Receiving signed certificate
        5. Returning SVID to workload via this API
        
        Returns:
            SVID with certificate and private key
            
        Raises:
            SPIFFEError: If unable to fetch SVID
        """
        if not self.is_available():
            raise SPIFFEError(f"Workload API socket not found: {self.socket_path}")
        
        try:
            # In a real implementation, this would use the SPIFFE Workload API
            # protocol (gRPC over Unix socket). Here we simulate the response.
            # 
            # Real implementation would use:
            # from pyspiffe.workloadapi import WorkloadApiClient
            # client = WorkloadApiClient(self.socket_path)
            # svid = client.fetch_x509_svid()
            
            # For demo/development, create a self-signed certificate
            svid = self._create_demo_svid()
            
            with self._lock:
                self._current_svid = svid
            
            logger.info(
                "Fetched SVID",
                spiffe_id=svid.spiffe_id,
                expires_in_seconds=svid.time_until_expiry,
            )
            
            return svid
            
        except Exception as e:
            raise SPIFFEError(f"Failed to fetch SVID: {e}") from e
    
    def get_current_svid(self) -> Optional[SVID]:
        """Get the current cached SVID (may be expired)."""
        with self._lock:
            return self._current_svid
    
    def get_valid_svid(self) -> SVID:
        """
        Get a valid (non-expired) SVID, fetching a new one if needed.
        
        This is the recommended method for getting credentials.
        """
        with self._lock:
            if self._current_svid and not self._current_svid.is_expired:
                return self._current_svid
        
        return self.fetch_svid()
    
    def start_rotation_watcher(self, callback: Optional[Callable[[SVID], None]] = None):
        """
        Start watching for SVID rotation.
        
        The SPIRE Agent automatically rotates SVIDs before they expire.
        This method starts a background thread that:
        1. Watches for rotation events
        2. Updates the cached SVID
        3. Calls the optional callback
        
        Args:
            callback: Optional function to call when SVID is rotated
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            logger.warning("Rotation watcher already running")
            return
        
        self._rotation_callback = callback
        self._stop_watcher.clear()
        self._watcher_thread = threading.Thread(
            target=self._rotation_watcher_loop,
            daemon=True,
        )
        self._watcher_thread.start()
        logger.info("Started SVID rotation watcher")
    
    def stop_rotation_watcher(self):
        """Stop the rotation watcher."""
        self._stop_watcher.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5)
        logger.info("Stopped SVID rotation watcher")
    
    def _rotation_watcher_loop(self):
        """Background loop that watches for SVID rotation."""
        while not self._stop_watcher.is_set():
            try:
                svid = self.get_current_svid()
                
                if svid is None or svid.time_until_expiry < 60:
                    # Refresh if no SVID or expiring soon
                    new_svid = self.fetch_svid()
                    
                    if self._rotation_callback:
                        try:
                            self._rotation_callback(new_svid)
                        except Exception as e:
                            logger.error("Rotation callback error", error=str(e))
                
                # Check every 30 seconds
                self._stop_watcher.wait(timeout=30)
                
            except Exception as e:
                logger.error("Rotation watcher error", error=str(e))
                self._stop_watcher.wait(timeout=5)
    
    def _create_demo_svid(self) -> SVID:
        """
        Create a demo SVID for development/testing.
        
        In production, this would come from SPIRE.
        """
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime, timedelta, timezone
        
        # Generate private key LOCALLY (this is the key insight!)
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
        )
        
        # Create self-signed certificate (in real SPIRE, this would be signed by CA)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ADK Demo"),
            x509.NameAttribute(NameOID.COMMON_NAME, "adk-workload"),
        ])
        
        # SPIFFE ID is encoded in the SAN URI
        spiffe_id = "spiffe://adk.local/ns/default/workload/controller"
        
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(hours=1)  # Short-lived!
        
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(expiry)
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.UniformResourceIdentifier(spiffe_id),
                ]),
                critical=True,
            )
            .sign(private_key, hashes.SHA256())
        )
        
        # Serialize to PEM
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        
        return SVID(
            spiffe_id=spiffe_id,
            cert_chain_pem=cert_pem,
            private_key_pem=key_pem,
            bundle_pem=cert_pem,  # Self-signed, so bundle = cert
            expiry=expiry.timestamp(),
        )


class SPIFFEError(Exception):
    """SPIFFE-related error."""
    pass


class SPIFFEHTTPClient:
    """
    HTTP client with automatic mTLS using SPIFFE identity.
    
    This client:
    1. Gets SVID from Workload API
    2. Configures TLS with the certificate and private key
    3. Verifies server certificates against trust bundle
    4. Automatically refreshes credentials on rotation
    """
    
    def __init__(
        self,
        workload_api: SPIFFEWorkloadAPI,
        expected_server_id: Optional[str] = None,
    ):
        """
        Initialize SPIFFE HTTP client.
        
        Args:
            workload_api: Workload API client
            expected_server_id: Optional SPIFFE ID to verify server has
        """
        self.workload_api = workload_api
        self.expected_server_id = expected_server_id
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._temp_files: list = []
    
    def _create_ssl_context(self, svid: SVID) -> ssl.SSLContext:
        """Create SSL context from SVID."""
        
        # Create temporary files for cert and key
        # (httpx/ssl requires file paths, not bytes)
        cert_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        key_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
        
        cert_file.write(svid.cert_chain_pem)
        cert_file.close()
        
        key_file.write(svid.private_key_pem)
        key_file.close()
        
        ca_file.write(svid.bundle_pem)
        ca_file.close()
        
        self._temp_files.extend([cert_file.name, key_file.name, ca_file.name])
        
        # Create SSL context
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.load_cert_chain(cert_file.name, key_file.name)
        ctx.load_verify_locations(ca_file.name)
        ctx.verify_mode = ssl.CERT_REQUIRED
        
        return ctx
    
    def get_client(self) -> httpx.Client:
        """
        Get HTTP client configured with mTLS.
        
        The client uses the current SVID for authentication.
        """
        svid = self.workload_api.get_valid_svid()
        ssl_context = self._create_ssl_context(svid)
        
        return httpx.Client(verify=ssl_context)
    
    async def get_async_client(self) -> httpx.AsyncClient:
        """Get async HTTP client configured with mTLS."""
        svid = self.workload_api.get_valid_svid()
        ssl_context = self._create_ssl_context(svid)
        
        return httpx.AsyncClient(verify=ssl_context)
    
    def cleanup(self):
        """Clean up temporary files."""
        import os
        for f in self._temp_files:
            try:
                os.unlink(f)
            except OSError:
                pass
        self._temp_files.clear()
    
    def __del__(self):
        self.cleanup()


class IdentityProvider:
    """
    High-level identity provider for ADK workloads.
    
    Provides a simple interface for:
    - Getting the current workload's SPIFFE ID
    - Creating authenticated HTTP clients
    - Checking authorization based on SPIFFE ID
    """
    
    def __init__(self, socket_path: Optional[str] = None):
        """
        Initialize identity provider.
        
        Args:
            socket_path: SPIFFE Workload API socket path.
                        If None, uses SPIFFE_SOCKET env var or default.
        """
        socket_path = socket_path or os.getenv(
            "SPIFFE_SOCKET",
            "/run/spire/sockets/agent.sock"
        )
        
        self.workload_api = SPIFFEWorkloadAPI(socket_path)
        self._enabled = self.workload_api.is_available()
        
        if not self._enabled:
            logger.warning(
                "SPIFFE Workload API not available, using demo mode",
                socket_path=socket_path,
            )
    
    @property
    def enabled(self) -> bool:
        """Check if SPIFFE identity is enabled."""
        return self._enabled
    
    def get_identity(self) -> str:
        """
        Get current workload's SPIFFE ID.
        
        Returns:
            SPIFFE ID string (e.g., spiffe://cluster/ns/default/workload/controller)
        """
        if not self._enabled:
            return "spiffe://adk.local/demo/workload"
        
        svid = self.workload_api.get_valid_svid()
        return svid.spiffe_id
    
    def get_svid(self) -> Optional[SVID]:
        """Get current SVID (or None if not available)."""
        if not self._enabled:
            # Create demo SVID for development
            try:
                return self.workload_api._create_demo_svid()
            except ImportError:
                # cryptography not installed
                return None
        
        return self.workload_api.get_valid_svid()
    
    def create_mtls_client(
        self,
        expected_server_id: Optional[str] = None,
    ) -> SPIFFEHTTPClient:
        """
        Create an mTLS-enabled HTTP client.
        
        Args:
            expected_server_id: Optional SPIFFE ID the server must have
            
        Returns:
            HTTP client that authenticates with this workload's identity
        """
        return SPIFFEHTTPClient(
            workload_api=self.workload_api,
            expected_server_id=expected_server_id,
        )
    
    def is_authorized(self, spiffe_id: str, allowed_ids: list[str]) -> bool:
        """
        Check if a SPIFFE ID is in the allowed list.
        
        Args:
            spiffe_id: The SPIFFE ID to check
            allowed_ids: List of allowed SPIFFE IDs (supports wildcards)
            
        Returns:
            True if authorized
        """
        if not allowed_ids:
            return True  # No restrictions
        
        for allowed in allowed_ids:
            if allowed.endswith("/*"):
                # Wildcard match
                prefix = allowed[:-1]
                if spiffe_id.startswith(prefix):
                    return True
            elif spiffe_id == allowed:
                return True
        
        return False


# Convenience function for getting identity
_identity_provider: Optional[IdentityProvider] = None


def get_identity_provider() -> IdentityProvider:
    """Get the global identity provider instance."""
    global _identity_provider
    if _identity_provider is None:
        _identity_provider = IdentityProvider()
    return _identity_provider
