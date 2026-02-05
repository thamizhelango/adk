"""
Tests for the SPIFFE Identity service.
"""

import pytest
import time
from unittest.mock import Mock, patch


class TestSVID:
    """Test SVID dataclass."""
    
    def test_is_expired_false(self):
        """SVID with future expiry should not be expired."""
        from controller.services.identity import SVID
        
        svid = SVID(
            spiffe_id="spiffe://test/workload",
            cert_chain_pem=b"cert",
            private_key_pem=b"key",
            bundle_pem=b"bundle",
            expiry=time.time() + 3600,  # 1 hour from now
        )
        
        assert not svid.is_expired
        assert svid.time_until_expiry > 3500
    
    def test_is_expired_true(self):
        """SVID with past expiry should be expired."""
        from controller.services.identity import SVID
        
        svid = SVID(
            spiffe_id="spiffe://test/workload",
            cert_chain_pem=b"cert",
            private_key_pem=b"key",
            bundle_pem=b"bundle",
            expiry=time.time() - 100,  # 100 seconds ago
        )
        
        assert svid.is_expired
        assert svid.time_until_expiry == 0


class TestIdentityProvider:
    """Test IdentityProvider."""
    
    def test_demo_mode_when_socket_missing(self):
        """Should work in demo mode when SPIFFE socket is missing."""
        from controller.services.identity import IdentityProvider
        
        provider = IdentityProvider(socket_path="/nonexistent/socket")
        
        assert not provider.enabled
        identity = provider.get_identity()
        assert identity.startswith("spiffe://")
    
    def test_authorization_empty_list(self):
        """Empty allowed list should authorize everything."""
        from controller.services.identity import IdentityProvider
        
        provider = IdentityProvider(socket_path="/nonexistent")
        
        result = provider.is_authorized(
            "spiffe://test/any/workload",
            allowed_ids=[],
        )
        
        assert result is True
    
    def test_authorization_exact_match(self):
        """Should authorize exact SPIFFE ID match."""
        from controller.services.identity import IdentityProvider
        
        provider = IdentityProvider(socket_path="/nonexistent")
        
        result = provider.is_authorized(
            "spiffe://test/workload/foo",
            allowed_ids=["spiffe://test/workload/foo"],
        )
        
        assert result is True
    
    def test_authorization_no_match(self):
        """Should reject non-matching SPIFFE ID."""
        from controller.services.identity import IdentityProvider
        
        provider = IdentityProvider(socket_path="/nonexistent")
        
        result = provider.is_authorized(
            "spiffe://test/workload/bar",
            allowed_ids=["spiffe://test/workload/foo"],
        )
        
        assert result is False
    
    def test_authorization_wildcard(self):
        """Should support wildcard matching."""
        from controller.services.identity import IdentityProvider
        
        provider = IdentityProvider(socket_path="/nonexistent")
        
        # Should match
        assert provider.is_authorized(
            "spiffe://test/ns/default/agent/sre-agent",
            allowed_ids=["spiffe://test/ns/default/*"],
        )
        
        # Should not match
        assert not provider.is_authorized(
            "spiffe://test/ns/other/agent/sre-agent",
            allowed_ids=["spiffe://test/ns/default/*"],
        )


class TestDemoSVID:
    """Test demo SVID creation."""
    
    def test_create_demo_svid(self):
        """Should create valid demo SVID."""
        pytest.importorskip("cryptography")
        
        from controller.services.identity import SPIFFEWorkloadAPI
        
        api = SPIFFEWorkloadAPI(socket_path="/nonexistent")
        svid = api._create_demo_svid()
        
        assert svid.spiffe_id.startswith("spiffe://")
        assert len(svid.cert_chain_pem) > 0
        assert len(svid.private_key_pem) > 0
        assert svid.expiry > time.time()
        assert not svid.is_expired
