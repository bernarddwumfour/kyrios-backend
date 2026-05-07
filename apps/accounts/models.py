from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
import secrets
import pyotp
from django.utils import timezone

class User(AbstractUser):
    """
    Custom User Model with roles, avatar configuration, and email verification.
    """
    
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', _('Admin')
        STAFF = 'STAFF', _('Staff')
        USER = 'USER', _('User')
    
    class Gender(models.TextChoices):
        MALE = 'male', _('Male')
        FEMALE = 'female', _('Female')
        PREFER_NOT_TO_SAY = 'prefer_not_to_say', _('Prefer not to say')
    
    # Role field
    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.USER,
        db_index=True,
        help_text="User role for authorization"
    )
    
    # Gender field
    gender = models.CharField(
        max_length=20,
        choices=Gender.choices,
        blank=True,
        null=True,
        db_index=True,
        help_text="User gender for avatar generation"
    )
    
    # Avatar Configuration - Store as JSON
    avatar_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Avatar configuration options for DiceBear avatar generation"
    )
    
    # Legacy profile picture field (kept for backward compatibility)
    profile_picture = models.URLField(
        blank=True,
        help_text="URL to profile picture (deprecated, use avatar_config instead)"
    )
    
    # Additional fields
    phone_number = models.CharField(
        max_length=15, 
        blank=True,
        help_text="Contact phone number"
    )
    
    # Email Verification Fields
    email_verified = models.BooleanField(
        default=False,
        help_text="Has email been verified"
    )
    email_verification_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Token for email verification"
    )
    email_verification_sent_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the verification email was last sent"
    )
    email_verified_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When the email was verified"
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # MFA Fields
    mfa_enabled = models.BooleanField(default=False)
    mfa_method = models.CharField(
        max_length=10,
        choices=[('app', 'Authenticator App'), ('email', 'Email')],
        blank=True,
        null=True
    )
    mfa_secret = models.CharField(max_length=32, blank=True, null=True)
    mfa_email_verified = models.BooleanField(default=False)
    mfa_backup_codes = models.JSONField(default=list, blank=True)
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['username']),
            models.Index(fields=['role']),
            models.Index(fields=['gender']),
            models.Index(fields=['email_verified']),  # Add index for email verification queries
        ]
    
    def __str__(self):
        return f"{self.username} ({self.email})"
    
    @property
    def is_admin(self):
        """Check if user is admin"""
        return self.role == self.Role.ADMIN or self.is_superuser
    
    @property
    def is_staff_member(self):
        """Check if user is staff"""
        return self.role == self.Role.STAFF or self.is_staff
    
    @property
    def has_avatar_config(self):
        """Check if user has avatar configuration"""
        return bool(self.avatar_config)
    
    @property
    def avatar_url(self):
        """
        Generate avatar URL using DiceBear API (optional)
        This can be used as a fallback or for server-side rendering
        """
        if self.avatar_config:
            # Build query params for DiceBear API
            params = {
                'seed': self.username or str(self.id),
                **self.avatar_config
            }
            # Return API URL (if you want to use the API endpoint instead of client-side generation)
            return f"https://api.dicebear.com/9.x/avataaars/svg?{self._build_query_params(params)}"
        return self.profile_picture or None
    
    def _build_query_params(self, config):
        """Helper to build query parameters for DiceBear API"""
        import urllib.parse
        params = {}
        for key, value in config.items():
            if value and value != 'none':
                params[key] = value
        return urllib.parse.urlencode(params)
    
    # MFA Methods
    def generate_mfa_secret(self):
        """Generate a new MFA secret key"""
        self.mfa_secret = pyotp.random_base32()
        return self.mfa_secret
    
    def get_mfa_otp_uri(self):
        """Get OTP URI for QR code generation"""
        if self.mfa_secret:
            return pyotp.totp.TOTP(self.mfa_secret).provisioning_uri(
                name=self.email,
                issuer_name="KYRIOS"
            )
        return None
    
    def verify_mfa_code(self, code):
        """Verify MFA code"""
        if not self.mfa_secret:
            return False
        
        totp = pyotp.TOTP(self.mfa_secret)
        return totp.verify(code)
    
    def generate_backup_codes(self, count=8):
        """Generate backup codes for account recovery"""
        codes = []
        for _ in range(count):
            code = secrets.token_hex(4).upper()
            codes.append(code)
        self.mfa_backup_codes = codes
        return codes
    
    # Email Verification Methods
    def mark_email_verified(self):
        """Mark email as verified and clear verification token"""
        self.email_verified = True
        self.email_verified_at = timezone.now()
        self.email_verification_token = None
        self.save(update_fields=['email_verified', 'email_verified_at', 'email_verification_token'])
    
    def is_email_verification_expired(self):
        """Check if the email verification token has expired (24 hours)"""
        if not self.email_verification_sent_at:
            return True
        from django.utils import timezone
        expiry_time = self.email_verification_sent_at + timezone.timedelta(hours=24)
        return timezone.now() > expiry_time
    
    def needs_verification(self):
        """Check if user needs email verification"""
        return not self.email_verified and self.is_active