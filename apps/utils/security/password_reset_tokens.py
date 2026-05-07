"""
Password reset token management - separate from JWT tokens
These are short-lived, single-use tokens for password reset functionality
"""

import secrets
import hashlib
from django.core.cache import cache
from typing import Optional


class PasswordResetTokenError(Exception):
    """Base exception for password reset tokens"""
    pass


class PasswordResetTokenExpired(PasswordResetTokenError):
    """Token has expired"""
    pass


class PasswordResetTokenInvalid(PasswordResetTokenError):
    """Token is invalid"""
    pass


class PasswordResetTokenManager:
    """
    Manages password reset tokens.
    
    These are different from JWT tokens:
    - Short-lived (1 hour)
    - Single-use (deleted after use)
    - Not tied to session
    - Stored in cache (not database)
    """
    
    def __init__(self):
        self.token_prefix = 'password_reset:'
        self.token_expiry = 3600  # 1 hour in seconds
    
    def generate_token(self, user_id: int) -> str:
        """
        Generate a secure password reset token for a user.
        
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
        Validate a password reset token and return the user_id if valid.
        
        Args:
            token: Raw token from email link
            
        Returns:
            User ID if valid, None otherwise
            
        Raises:
            PasswordResetTokenExpired: Token has expired
            PasswordResetTokenInvalid: Token is invalid
        """
        if not token:
            raise PasswordResetTokenInvalid("No token provided")
        
        # Hash the token to look up in cache
        hashed_token = hashlib.sha256(token.encode()).hexdigest()
        cache_key = f"{self.token_prefix}{hashed_token}"
        
        # Get user_id from cache
        user_id = cache.get(cache_key)
        
        if user_id is None:
            # Check if token existed but expired
            # Cache doesn't distinguish between never existed and expired
            raise PasswordResetTokenExpired("Token has expired or is invalid")
        
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
        Invalidate all password reset tokens for a user.
        
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
password_reset_token_manager = PasswordResetTokenManager()


# Convenience functions
def generate_password_reset_token(user_id: int) -> str:
    """Generate a password reset token for a user"""
    return password_reset_token_manager.generate_token(user_id)


def validate_password_reset_token(token: str) -> Optional[int]:
    """Validate a password reset token and return user_id"""
    return password_reset_token_manager.validate_token(token)


def is_password_reset_token_valid(token: str) -> bool:
    """Check if a password reset token is valid"""
    return password_reset_token_manager.is_token_valid(token)


def invalidate_password_reset_token(token: str) -> bool:
    """Invalidate a password reset token"""
    return password_reset_token_manager.invalidate_token(token)