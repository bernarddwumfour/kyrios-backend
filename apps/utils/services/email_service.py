"""
Email service for sending transactional emails with built-in async support
"""

from datetime import datetime
import threading

from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from ..helpers.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """
    Service for sending various types of emails with async support.
    All email methods can be called sync or async.
    """

    def __init__(self):
        self.from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@yourapp.com')
        self.site_name = getattr(settings, 'SITE_NAME', 'Kyrios')
        self.frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        self.async_mode = getattr(settings, 'EMAIL_ASYNC_MODE', True)

    def _send_email_sync(self, to_email: str, subject: str, html_content: str) -> bool:
        """
        Send email synchronously using its own dedicated SMTP connection.
        Safe to call from background threads.
        """
        # Each call gets a fresh connection — never shares connections across threads
        connection = get_connection()
        try:
            text_content = strip_tags(html_content)
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=self.from_email,
                to=[to_email],
                connection=connection,
            )
            email.attach_alternative(html_content, "text/html")
            email.send()
            logger.info(f"Email sent to {to_email}", subject=subject)
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}", exc_info=True)
            return False

        finally:
            # Always close the connection, even on failure
            try:
                connection.close()
            except Exception:
                pass

    def _send_email_async(self, to_email: str, subject: str, html_content: str) -> bool:
        """
        Send email in a non-daemon background thread.
        Non-daemon so the thread isn't killed before SMTP finishes.
        """
        def send():
            try:
                self._send_email_sync(to_email, subject, html_content)
            except Exception as e:
                logger.error(
                    f"Unexpected error in async email to {to_email}: {str(e)}",
                    exc_info=True
                )

        # daemon=False ensures the thread isn't killed mid-send when the
        # request completes
        thread = threading.Thread(target=send, daemon=False)
        thread.start()
        return True  # Intentionally optimistic — caller is non-blocking

    def _send_email(self, to_email: str, subject: str, html_content: str, async_mode: bool = None) -> bool:
        use_async = async_mode if async_mode is not None else self.async_mode
        if use_async:
            return self._send_email_async(to_email, subject, html_content)
        return self._send_email_sync(to_email, subject, html_content)

    # ------------------------------------------------------------------ #
    #  Public methods                                                      #
    # ------------------------------------------------------------------ #

    def send_welcome_email(self, user, async_mode: bool = None) -> bool:
        try:
            context = {
                'user': user,
                'login_link': f"{self.frontend_url}/login",
                'site_name': self.site_name,
                'year': datetime.now().year,
            }
            html_content = render_to_string('emails/welcome.html', context)
            return self._send_email(user.email, f"Welcome to {self.site_name}! 🎉", html_content, async_mode)
        except Exception as e:
            logger.error(f"Failed to prepare welcome email: {str(e)}", exc_info=True)
            return False
        
    def send_verification_email(self, user, verification_token: str, async_mode: bool = None) -> bool:
        """
        Send email verification link to user
        
        Args:
            user: User object
            verification_token: Email verification token
            async_mode: True = background, False = sync, None = use default
        """
        try:
            verification_link = f"{self.frontend_url}/verify-email?token={verification_token}"
            
            context = {
                'user': user,
                'verification_link': verification_link,
                'expiry_hours': 24,
                'site_name': self.site_name,
                'year': datetime.now().year
            }
            
            html_content = render_to_string('emails/verify_email.html', context)
            subject = f"Verify Your Email - {self.site_name}"
            
            return self._send_email(user.email, subject, html_content, async_mode)
            
        except Exception as e:
            logger.error(f"Failed to send verification email: {str(e)}")
            return False


    def send_verification_success_email(self, user, async_mode: bool = None) -> bool:
        """
        Send confirmation email after successful email verification
        
        Args:
            user: User object
            async_mode: True = background, False = sync, None = use default
        """
        try:
            context = {
                'user': user,
                'login_link': f"{self.frontend_url}/login",
                'site_name': self.site_name,
                'year': datetime.now().year
            }
            
            html_content = render_to_string('emails/verify_email_success.html', context)
            subject = f"Email Verified Successfully - {self.site_name}"
            
            return self._send_email(user.email, subject, html_content, async_mode)
            
        except Exception as e:
            logger.error(f"Failed to send verification success email: {str(e)}")
            return False
        

    def send_password_reset_email(self, user, reset_token: str, async_mode: bool = None) -> bool:
        try:
            context = {
                'user': user,
                'reset_link': f"{self.frontend_url}/reset-password?token={reset_token}",
                'expiry_hours': 1,
                'site_name': self.site_name,
                'year': datetime.now().year,
            }
            html_content = render_to_string('emails/password_reset.html', context)
            return self._send_email(user.email, f"Password Reset Request - {self.site_name}", html_content, async_mode)
        except Exception as e:
            logger.error(f"Failed to prepare password reset email: {str(e)}", exc_info=True)
            return False

    def send_password_reset_success_email(self, user, async_mode: bool = None) -> bool:
        try:
            context = {
                'user': user,
                'login_link': f"{self.frontend_url}/login",
                'site_name': self.site_name,
                'year': datetime.now().year,
            }
            html_content = render_to_string('emails/password_reset_success.html', context)
            return self._send_email(user.email, f"Password Reset Successful - {self.site_name}", html_content, async_mode)
        except Exception as e:
            logger.error(f"Failed to prepare password reset success email: {str(e)}", exc_info=True)
            return False

    def send_mfa_setup_email(self, user, verification_code: str, async_mode: bool = None) -> bool:
        try:
            html_content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Email Verification for MFA Setup</h2>
                <p>Hello {user.first_name or user.email},</p>
                <p>You've requested to set up email-based multi-factor authentication.</p>
                <p>Your verification code is:</p>
                <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; padding: 20px;
                            background: #f5f5f5; text-align: center; border-radius: 10px;">
                    {verification_code}
                </div>
                <p>This code will expire in 5 minutes.</p>
                <p>If you didn't request this, please ignore this email.</p>
                <hr>
                <p style="color: #666; font-size: 12px;">{self.site_name} - Secure Platform</p>
            </div>
            """
            return self._send_email(user.email, "Verify Your Email for MFA Setup", html_content, async_mode)
        except Exception as e:
            logger.error(f"Failed to prepare MFA setup email: {str(e)}", exc_info=True)
            return False

    def send_mfa_login_email(self, user, verification_code: str, async_mode: bool = None) -> bool:
        try:
            html_content = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <h2>Login Verification Code</h2>
                <p>Hello {user.first_name or user.email},</p>
                <p>Use the following code to complete your login:</p>
                <div style="font-size: 32px; font-weight: bold; letter-spacing: 5px; padding: 20px;
                            background: #f5f5f5; text-align: center; border-radius: 10px;">
                    {verification_code}
                </div>
                <p>This code will expire in 5 minutes.</p>
                <p>If you didn't attempt to log in, please secure your account immediately.</p>
                <hr>
                <p style="color: #666; font-size: 12px;">{self.site_name} - Secure Platform</p>
            </div>
            """
            return self._send_email(user.email, "Your Login Verification Code", html_content, async_mode)
        except Exception as e:
            logger.error(f"Failed to prepare MFA login email: {str(e)}", exc_info=True)
            return False


# Singleton instance
email_service = EmailService()