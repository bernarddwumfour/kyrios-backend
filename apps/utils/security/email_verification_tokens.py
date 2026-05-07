"""
Email verification token management - separate from JWT tokens
These are short-lived, single-use tokens for email verification functionality
"""

import secrets
import hashlib
from django.core.cache import cache
from typing import Optional


class EmailVerificationTokenError(Exception):
    """Base exception for email verification tokens"""
    pass


class EmailVerificationTokenExpired(EmailVerificationTokenError):
    """Token has expired"""
    pass


class EmailVerificationTokenInvalid(EmailVerificationTokenError):
    """Token is invalid"""
    pass


class EmailVerificationTokenManager:
    """
    Manages email verification tokens.
    
    These are different from JWT tokens:
    - Short-lived (24 hours)
    - Single-use (deleted after use)
    - Not tied to session
    - Stored in cache (not database)
    """
    
    def __init__(self):
        self.token_prefix = 'email_verify:'
        self.token_expiry = 86400  # 24 hours in seconds (24 * 3600)
    
    def generate_token(self, user_id: int) -> str:
        """
        Generate a secure email verification token for a user.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Raw token string to include in email link
        """
        # Generate a cryptographically secure random token
        raw_token = secrets.token_urlsafe(32)
        
        # Hash the token for storage (security - never store raw tokens)
        hashed_token = hashlib.sha256(raw_token.encode()).hexdigest()
        
        # Store in cache with expiry
        cache_key = f"{self.token_prefix}{hashed_token}"
        cache.set(cache_key, user_id, timeout=self.token_expiry)
        
        return raw_token
    
    def validate_token(self, token: str) -> Optional[int]:
        """
        Validate an email verification token and return the user_id if valid.
        
        Args:
            token: Raw token from email link
            
        Returns:
            User ID if valid, None otherwise
            
        Raises:
            EmailVerificationTokenExpired: Token has expired
            EmailVerificationTokenInvalid: Token is invalid
        """
        if not token:
            raise EmailVerificationTokenInvalid("No token provided")
        
        # Hash the token to look up in cache
        hashed_token = hashlib.sha256(token.encode()).hexdigest()
        cache_key = f"{self.token_prefix}{hashed_token}"
        
        # Get user_id from cache
        user_id = cache.get(cache_key)
        
        if user_id is None:
            # Check if token existed but expired
            # Cache doesn't distinguish between never existed and expired
            raise EmailVerificationTokenExpired("Token has expired or is invalid")
        
        # Delete token after use (single-use)
        cache.delete(cache_key)
        
        return user_id
    
    def is_token_valid(self, token: str) -> bool:
        """
        Check if a token is valid without consuming it.
        
        Args:
            token: Raw token from email link
            
        Returns:
            True if token is valid, False otherwise
        """
        try:
            hashed_token = hashlib.sha256(token.encode()).hexdigest()
            cache_key = f"{self.token_prefix}{hashed_token}"
            user_id = cache.get(cache_key)
            return user_id is not None
        except Exception:
            return False
    
    def invalidate_token(self, token: str) -> bool:
        """
        Explicitly invalidate a token (force single-use).
        
        Args:
            token: Raw token to invalidate
            
        Returns:
            True if token was invalidated, False otherwise
        """
        try:
            hashed_token = hashlib.sha256(token.encode()).hexdigest()
            cache_key = f"{self.token_prefix}{hashed_token}"
            
            if cache.get(cache_key):
                cache.delete(cache_key)
                return True
            return False
        except Exception:
            return False
    
    def invalidate_all_user_tokens(self, user_id: int) -> int:
        """
        Invalidate all email verification tokens for a user.
        
        Note: This is a best-effort operation since we don't track all tokens.
        For production, you might want to store token references per user.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Number of tokens invalidated (always 0 in this implementation)
        """
        # In a more advanced implementation, you'd track all tokens per user
        # For now, we rely on token expiration
        return 0


# Singleton instance
email_verification_token_manager = EmailVerificationTokenManager()


# Convenience functions
def generate_email_verification_token(user_id: int) -> str:
    """Generate an email verification token for a user"""
    return email_verification_token_manager.generate_token(user_id)


def validate_email_verification_token(token: str) -> Optional[int]:
    """Validate an email verification token and return user_id"""
    return email_verification_token_manager.validate_token(token)


def is_email_verification_token_valid(token: str) -> bool:
    """Check if an email verification token is valid"""
    return email_verification_token_manager.is_token_valid(token)


def invalidate_email_verification_token(token: str) -> bool:
    """Invalidate an email verification token"""
    return email_verification_token_manager.invalidate_token(token)