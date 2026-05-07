"""
JWT Token management with Redis blacklist support.
Atomic Design Level: Atom
"""

import jwt
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from django.conf import settings
from django.core.cache import cache



class TokenError(Exception):
    """Base token exception"""
    pass


class TokenExpiredError(TokenError):
    """Token has expired"""
    pass


class TokenInvalidError(TokenError):
    """Token is invalid"""
    pass


class TokenBlacklistedError(TokenError):
    """Token has been revoked"""
    pass


class TokenManager:
    """
    Manages JWT tokens with Redis blacklist.
    """
    
    def __init__(self):
        self.secret_key = settings.SECRET_KEY
        self.algorithm = getattr(settings, 'JWT_ALGORITHM', 'HS256')
        self.access_expire = getattr(settings, 'JWT_ACCESS_EXPIRE', 900)  # 15 min
        self.refresh_expire = getattr(settings, 'JWT_REFRESH_EXPIRE', 604800)  # 7 days
        
        # Cache key prefixes
        self.blacklist_prefix = 'token:blacklist:'
        self.user_tokens_prefix = 'token:user:'
    
    def _get_user_model(self):
        """Lazily get User model"""
        from django.apps import apps
        return apps.get_model(settings.AUTH_USER_MODEL)
    
    def generate_tokens(self, user):
        """
        Generate access and refresh tokens for user.
        """
        # Common claims
        base_claims = {
            'user_id': user.id,
            'username': user.username,
            'email': user.email,
            'role': getattr(user, 'role', 'USER')
        }
        
        # Generate access token (short-lived)
        access_jti = str(uuid.uuid4())
        access_token = self._create_token(
            token_type='access',
            jti=access_jti,
            expires_in=self.access_expire,
            **base_claims
        )
        
        # Generate refresh token (long-lived)
        refresh_jti = str(uuid.uuid4())
        refresh_token = self._create_token(
            token_type='refresh',
            jti=refresh_jti,
            expires_in=self.refresh_expire,
            **base_claims
        )
        
        return access_token, refresh_token
    
    def _create_token(self, token_type: str, jti: str, expires_in: int, **claims) -> str:
        """Create a JWT token"""
        now = datetime.utcnow()
        payload = {
            'jti': jti,
            'type': token_type,
            'iat': now,
            'exp': now + timedelta(seconds=expires_in),
            **claims
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
    
    def verify_token(self, token: str, expected_type: Optional[str] = None) -> Dict:
        """
        Verify token and return payload.
        """
        try:
            # Decode and verify signature
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm]
            )
            
            # Check token type if specified
            if expected_type and payload.get('type') != expected_type:
                raise TokenInvalidError(f"Invalid token type. Expected {expected_type}")
            
            # Check if blacklisted
            if self.is_blacklisted(payload['jti']):
                raise TokenBlacklistedError("Token has been revoked")
            
            return payload
            
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError(f"Invalid token: {str(e)}")
    
    def refresh_tokens(self, refresh_token: str) -> Tuple[str, str]:
        """
        Get new tokens using refresh token.
        """
        # Verify refresh token
        payload = self.verify_token(refresh_token, expected_type='refresh')
        
        # Get user lazily
        User = self._get_user_model()
        try:
            user = User.objects.get(id=payload['user_id'], is_active=True)
        except User.DoesNotExist:
            raise TokenInvalidError("User not found or inactive")
        
        # Blacklist old refresh token
        self.blacklist_token(payload['jti'])
        
        # Generate new tokens
        return self.generate_tokens(user)
    
    def blacklist_token(self, jti: str, user_id: Optional[int] = None) -> None:
        """
        Add token to blacklist.
        """
        cache_key = f"{self.blacklist_prefix}{jti}"
        cache.set(cache_key, True, timeout=self.refresh_expire)
    
    def is_blacklisted(self, jti: str) -> bool:
        """Check if token is blacklisted"""
        cache_key = f"{self.blacklist_prefix}{jti}"
        return cache.get(cache_key, False)
    
    def get_user_from_token(self, token: str):
        """
        Get user from token payload.
        """
        payload = self.verify_token(token, expected_type='access')
        User = self._get_user_model()
        
        try:
            return User.objects.get(id=payload['user_id'], is_active=True)
        except User.DoesNotExist:
            raise TokenInvalidError("User not found")


# Singleton instance
token_manager = TokenManager()


# Convenience functions
def generate_tokens(user):
    """Generate token pair for user"""
    return token_manager.generate_tokens(user)


def verify_token(token, expected_type=None):
    """Verify a token"""
    return token_manager.verify_token(token, expected_type)


def refresh_tokens(refresh_token):
    """Refresh tokens"""
    return token_manager.refresh_tokens(refresh_token)


def blacklist_token(jti, user_id=None):
    """Blacklist a token"""
    return token_manager.blacklist_token(jti, user_id)


def get_user_from_token(token):
    """Get user from token"""
    return token_manager.get_user_from_token(token)