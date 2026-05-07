import json
from datetime import datetime
import random
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth import authenticate
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from apps.utils.security.email_verification_tokens import email_verification_token_manager
from django.utils import timezone
import requests
from django.conf import settings


from apps.utils import (
    ok, created, bad_request, unauthorized,
    not_found, validation_error, server_error,
    generate_tokens, verify_token, refresh_tokens, blacklist_token,
    jwt_required, admin_required
)
from .models import User
from apps.utils.security.password_reset_tokens import (
    password_reset_token_manager,
    PasswordResetTokenExpired,
    PasswordResetTokenInvalid
)
from apps.utils.services.email_service import email_service
from apps.utils.helpers.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def validate_password_strength(password):
    """Validate password meets requirements"""
    errors = []
    
    if len(password) < 8:
        errors.append("Password must be at least 8 characters")
    
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one number")
    
    return errors


@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    """User registration endpoint"""
    logger.info("Registration attempt received", ip=request.META.get('REMOTE_ADDR'))
    
    try:
        data = json.loads(request.body)
        
        required_fields = ['email', 'password']
        missing = [f for f in required_fields if f not in data]
        if missing:
            logger.warning(f"Registration failed: Missing fields {missing}", 
                          email=data.get('email'), 
                          missing_fields=missing)
            return bad_request(f"Missing fields: {', '.join(missing)}", request=request)
        
        email = data['email']
        password = data['password']
        
        try:
            validate_email(email)
        except ValidationError:
            logger.warning("Registration failed: Invalid email format", email=email)
            return validation_error({'email': ['Invalid email format']}, request=request)
        
        password_errors = validate_password_strength(password)
        if password_errors:
            logger.warning("Registration failed: Password validation errors", 
                          email=email, 
                          errors=password_errors)
            return validation_error({'password': password_errors}, "Please make sure all fields are properly filled", request=request)
        
        if User.objects.filter(email=email).exists():
            logger.warning("Registration failed: Email already exists", email=email)
            return bad_request("Email already registered", request=request)
        
        # Create user
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            phone_number=data.get('phone_number', ''),
            gender=data.get('gender', ''),
            avatar_config=data.get('avatar_config', {})
        )
        
        # Generate email verification token
        verification_token = email_verification_token_manager.generate_token(user.id)
        user.email_verification_token = verification_token
        user.email_verification_sent_at = timezone.now()
        user.save(update_fields=['email_verification_token', 'email_verification_sent_at'])
        
        access_token, refresh_token = generate_tokens(user)
        
        # Send verification email (async)
        email_service.send_verification_email(user, verification_token)
        
        # Send welcome email (async)
        email_service.send_welcome_email(user)
        
        logger.info("User registered successfully", 
                   email=email, 
                   user_id=user.id,
                   role=user.role)
        
        return created(
            data={
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role,
                    'gender': user.gender,
                    'avatar_config': user.avatar_config,
                    'phone_number': user.phone_number,
                    'email_verified': user.email_verified
                },
                'tokens': {
                    'access': access_token,
                    'refresh': refresh_token,
                    'access_expires_in': 900,
                    'refresh_expires_in': 604800
                }
            },
            message="Registration successful. Please verify your email.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Registration failed: Invalid JSON format")
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Registration error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)
    
    

@csrf_exempt
@require_http_methods(["POST"])
def resend_verification_email(request):
    """
    Resend email verification link.
    
    POST /api/v1/accounts/email/resend-verification/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    try:
        # Check if user is authenticated
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return unauthorized("Authentication required", request=request)
        
        token = auth_header.split(' ')[1]
        
        try:
            from apps.utils.security.tokens import token_manager
            payload = token_manager.verify_token(token)
            user = User.objects.get(id=payload['user_id'])
        except Exception:
            return unauthorized("Invalid or expired token", request=request)
        
        # Check if email is already verified
        if user.email_verified:
            return bad_request("Email already verified", request=request)
        
        # Generate new verification token
        verification_token = email_verification_token_manager.generate_token(user.id)
        
        # Save token to user model
        user.email_verification_token = verification_token
        user.email_verification_sent_at = timezone.now()
        user.save(update_fields=['email_verification_token', 'email_verification_sent_at'])
        
        # Send verification email
        email_service.send_verification_email(user, verification_token)
        
        logger.info(f"Verification email resent to {user.email}", user_id=user.id)
        
        return ok(
            message="Verification email has been sent. Please check your inbox.",
            request=request
        )
        
    except Exception as e:
        logger.error(f"Resend verification error: {str(e)}")
        return server_error("Failed to resend verification email", request=request)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def verify_email(request):
    """
    Verify email address using token.
    
    GET/POST /api/v1/accounts/email/verify/?token=<token>
    
    Query params:
        token: Email verification token
    """
    try:
        # Get token from query params (GET) or body (POST)
        if request.method == 'GET':
            token = request.GET.get('token')
        else:
            data = json.loads(request.body)
            token = data.get('token')
        
        if not token:
            return bad_request("Verification token is required", request=request)
        
        # Validate token
        user_id = email_verification_token_manager.validate_token(token)
        
        if not user_id:
            return bad_request(
                "Invalid or expired verification token. Please request a new one.",
                request=request
            )
        
        # Get user
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return not_found("User not found", request=request)
        
        # Check if already verified
        if user.email_verified:
            return ok(
                message="Email already verified. You can now log in.",
                data={'verified': True, 'email': user.email},
                request=request
            )
        
        # Mark email as verified
        user.email_verified = True
        user.email_verified_at = timezone.now()
        user.email_verification_token = None
        user.save(update_fields=['email_verified', 'email_verified_at', 'email_verification_token'])
        
        # Send verification success email
        email_service.send_verification_success_email(user)
        
        logger.info("Email verified successfully", user_id=user.id, email=user.email)
        
        return ok(
            data={
                'verified': True,
                'email': user.email,
                'verified_at': user.email_verified_at
            },
            message="Email verified successfully! You can now log in.",
            request=request
        )
        
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Email verification error: {str(e)}")
        return server_error("Failed to verify email", request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["GET"])
def verification_status(request):
    """
    Check email verification status.
    
    GET /api/v1/accounts/email/status/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    user = request.user
    
    return ok(
        data={
            'email': user.email,
            'verified': user.email_verified,
            'verified_at': user.email_verified_at,
            'verification_sent_at': user.email_verification_sent_at
        },
        message="Verification status retrieved",
        request=request
    )
    
    

@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    """User login endpoint with MFA support"""
    logger.info("Login attempt received", ip=request.META.get('REMOTE_ADDR'))
    
    try:
        data = json.loads(request.body)
        
        if 'email' not in data or 'password' not in data:
            return bad_request("Email and password required", request=request)
        
        email = data['email']
        password = data['password']
        
        user = authenticate(request, username=email, password=password)
        
        if not user or not user.is_active:
            return unauthorized("Invalid credentials", request=request)
        
        # Check if MFA is enabled
        if user.mfa_enabled:
            # Return that MFA is required, don't generate tokens yet
            return ok(
                data={
                    'requires_mfa': True,
                    'user_id': user.id,
                    'mfa_method': user.mfa_method,
                    'message': f'MFA verification required. Check your {user.mfa_method} for code.'
                },
                message="MFA verification required",
                request=request
            )
        
        user.last_login = datetime.now()
        user.save(update_fields=['last_login'])
        
        access_token, refresh_token = generate_tokens(user)
        
        return ok(
            data={
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role,
                    'gender': user.gender,
                    'avatar_config': user.avatar_config,
                    'phone_number': user.phone_number,
                    'email_verified': user.email_verified
                },
                'tokens': {
                    'access': access_token,
                    'refresh': refresh_token,
                    'access_expires_in': 900,
                    'refresh_expires_in': 604800
                }
            },
            message="Login successful",
            request=request
        )
        
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Login error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@csrf_exempt
@require_http_methods(["POST"])
def google_login(request):
    """
    Google OAuth2 login - custom implementation.
    
    POST /api/v1/accounts/google/
    
    Body:
    {
        "code": "authorization_code_from_google"
    }
    """
    logger.info("Google login attempt received")
    
    try:
        data = json.loads(request.body)
        code = data.get('code')
        
        if not code:
            return bad_request("Authorization code is required", request=request)
        
        # Exchange authorization code for access token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': settings.GOOGLE_REDIRECT_URI,  
            'grant_type': 'authorization_code',
        }
        
        token_response = requests.post(token_url, data=token_data)
        
        if token_response.status_code != 200:
            logger.error(f"Google token exchange failed: {token_response.text}")
            return bad_request("Failed to authenticate with Google", request=request)
        
        token_json = token_response.json()
        
        if 'access_token' not in token_json:
            logger.error(f"No access token in response: {token_json}")
            return bad_request("Invalid response from Google", request=request)
        
        # Get user info from Google
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {'Authorization': f"Bearer {token_json['access_token']}"}
        userinfo_response = requests.get(userinfo_url, headers=headers)
        
        if userinfo_response.status_code != 200:
            logger.error(f"Failed to get userinfo: {userinfo_response.text}")
            return bad_request("Failed to get user information from Google", request=request)
        
        userinfo = userinfo_response.json()
        
        email = userinfo.get('email')
        if not email:
            return bad_request("Email not provided by Google", request=request)
        
        # Get or create user
        user, user_created = User.objects.get_or_create(
            email=email,
            defaults={
                'username': email,
                'first_name': userinfo.get('given_name', ''),
                'last_name': userinfo.get('family_name', ''),
                'email_verified': userinfo.get('verified_email', True),
            }
        )
        
        # If user exists but doesn't have name, update it
        if not user_created:
            if not user.first_name and userinfo.get('given_name'):
                user.first_name = userinfo.get('given_name', '')
                user.last_name = userinfo.get('family_name', '')
                user.save(update_fields=['first_name', 'last_name'])
        
        # Generate your JWT tokens
        access_token, refresh_token = generate_tokens(user)
        
        logger.info(f"Google login successful for {email}", 
                   user_id=user.id, 
                   was_created=user_created)
        
        return ok(
            data={
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role,
                    'gender': user.gender,
                    'avatar_config': user.avatar_config,
                    'phone_number': user.phone_number,
                    'email_verified': user.email_verified
                },
                'tokens': {
                    'access': access_token,
                    'refresh': refresh_token,
                    'access_expires_in': 900,
                    'refresh_expires_in': 604800
                }
            },
            message="Google login successful",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Google login: Invalid JSON")
        return bad_request("Invalid JSON", request=request)
    except requests.exceptions.RequestException as e:
        logger.error(f"Google API request error: {str(e)}")
        return server_error("Failed to communicate with Google", request=request)
    except Exception as e:
        logger.error(f"Google login error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)
    
    
@csrf_exempt
@require_http_methods(["POST"])
def token_refresh(request):
    """
    Get new access token using refresh token.
    
    POST /api/v1/accounts/token/refresh/
    
    Headers:
        Authorization: Bearer <refresh_token>
    """
    auth_header = request.headers.get('Authorization', '')
    
    if not auth_header.startswith('Bearer '):
        logger.warning("Token refresh failed: Missing bearer token")
        return unauthorized("Refresh token required", request=request)
    
    refresh_token = auth_header.split(' ')[1]
    
    try:
        access_token, new_refresh_token = refresh_tokens(refresh_token)
        
        logger.info("Tokens refreshed successfully", 
                   token_preview=f"{refresh_token[:20]}...")
        
        return ok(
            data={
                'tokens': {
                    'access': access_token,
                    'refresh': new_refresh_token,
                    'access_expires_in': 900,
                    'refresh_expires_in': 604800
                }
            },
            message="Tokens refreshed",
            request=request
        )
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}", exc_info=True)
        return unauthorized(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def logout(request):
    """
    Logout user - blacklists tokens.
    
    POST /api/v1/accounts/logout/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    try:
        user_email = request.user.email
        user_id = request.user.id
        
        # Blacklist access token
        blacklist_token(request.token_payload['jti'])
        
        # Optionally blacklist refresh token if provided
        if request.body:
            try:
                data = json.loads(request.body)
                if 'refresh_token' in data:
                    payload = verify_token(data['refresh_token'])
                    blacklist_token(payload['jti'])
                    logger.info("Refresh token also blacklisted", user_id=user_id)
            except Exception:
                pass
        
        logger.info("User logged out successfully", email=user_email, user_id=user_id)
        
        return ok(message="Logout successful", request=request)
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["GET"])
def me(request):
    """
    Get current user profile.
    
    GET /api/v1/accounts/me/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    user = request.user
    
    logger.debug("Profile retrieved", 
                user_id=user.id, 
                email=user.email,
                role=user.role)
    
    return ok(
        data={
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone_number': user.phone_number,
            'role': user.role,
            'gender': user.gender,
            'avatar_config': user.avatar_config,
            'date_joined': user.date_joined,
            'last_login': user.last_login,
            'email_verified': user.email_verified,
            'profile_picture': user.profile_picture
        },
        message="Profile retrieved",
        request=request
    )


@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def update_profile(request):
    """
    Update user profile.
    
    POST /api/v1/accounts/me/update/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    try:
        data = json.loads(request.body)
        user = request.user
        
        # Allowed fields
        allowed_fields = ['first_name', 'last_name','gender', 'phone_number', 'avatar_config']
        updates = {}
        
        for field in allowed_fields:
            if field in data:
                # Handle avatar_config specially (merge with existing)
                if field == 'avatar_config':
                    current_config = user.avatar_config or {}
                    current_config.update(data['avatar_config'])
                    setattr(user, field, current_config)
                else:
                    setattr(user, field, data[field])
                updates[field] = data[field]
        
        if updates:
            user.save()
            logger.info("Profile updated", 
                       user_id=user.id, 
                       email=user.email,
                       updated_fields=list(updates.keys()))
        
        return ok(
            data={
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone_number': user.phone_number,
                'role': user.role,
                'gender': user.gender,
                'avatar_config': user.avatar_config
            },
            message="Profile updated",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Profile update failed: Invalid JSON", user_id=request.user.id)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Profile update error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def update_avatar(request):
    """
    Update user avatar configuration.
    
    POST /api/v1/accounts/me/avatar/
    
    Headers:
        Authorization: Bearer <access_token>
    
    Body:
    {
        "avatar_config": {
            "top": "shortFlat",
            "clothing": "blazerAndShirt",
            "facial_hair": "beardLight",
            "eyes": "default",
            "mouth": "smile",
            "accessories": "prescription02",
            "skin_color": "f2d3b1",
            "hair_color": "2c1b18",
            "clothes_color": "3c4f5c",
            "facial_hair_color": "2c1b18"
        },
        "gender": "male"
    }
    """
    try:
        data = json.loads(request.body)
        user = request.user
        
        # Update avatar config if provided
        if 'avatar_config' in data:
            current_config = user.avatar_config or {}
            current_config.update(data['avatar_config'])
            user.avatar_config = current_config
            logger.info("Avatar config updated", user_id=user.id, email=user.email)
        
        # Update gender if provided
        # if 'gender' in data:
        #     valid_genders = [gender.value for gender in User.Gender]
        #     if data['gender'] in valid_genders:
        #         user.gender = data['gender']
        #         logger.info("Gender updated", user_id=user.id, email=user.email, gender=data['gender'])
        #     else:
        #         return validation_error(
        #             {'gender': [f"Invalid gender. Must be one of: {', '.join(valid_genders)}"]},
        #             request=request
        #         )
        
        user.save()
        
        return ok(
            data={
                'id': user.id,
                'email': user.email,
                'gender': user.gender,
                'avatar_config': user.avatar_config
            },
            message="Avatar configuration updated successfully",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Avatar update failed: Invalid JSON", user_id=request.user.id)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Avatar update error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["DELETE"])
def reset_avatar(request):
    """
    Reset avatar to default.
    
    DELETE /api/v1/accounts/me/avatar/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    try:
        user = request.user
        user.avatar_config = {}
        user.save()
        
        logger.info("Avatar reset to default", user_id=user.id, email=user.email)
        
        return ok(
            data={
                'id': user.id,
                'email': user.email,
                'avatar_config': user.avatar_config
            },
            message="Avatar reset to default",
            request=request
        )
        
    except Exception as e:
        logger.error(f"Avatar reset error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def change_password(request):
    """
    Change user password.
    
    POST /api/v1/accounts/password/change/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    try:
        data = json.loads(request.body)
        
        if 'current_password' not in data or 'new_password' not in data:
            logger.warning("Password change failed: Missing fields", user_id=request.user.id)
            return bad_request(
                "Current password and new password required",
                request=request
            )
        
        user = request.user
        current = data['current_password']
        new_password = data['new_password']
        
        # Verify current password
        if not user.check_password(current):
            logger.warning("Password change failed: Incorrect current password", 
                          user_id=user.id, email=user.email)
            return unauthorized("Current password is incorrect", request=request)
        
        # Validate new password
        password_errors = validate_password_strength(new_password)
        if password_errors:
            logger.warning("Password change failed: Password validation errors", 
                          user_id=user.id, errors=password_errors)
            return validation_error(
                {'new_password': password_errors},
                request=request
            )
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        # Blacklist current token (force re-login)
        blacklist_token(request.token_payload['jti'])
        
        logger.info("Password changed successfully", 
                   user_id=user.id, 
                   email=user.email)
        
        return ok(
            message="Password changed successfully. Please login again.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Password change failed: Invalid JSON", user_id=request.user.id)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Password change error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@csrf_exempt
@require_http_methods(["POST"])
def forgot_password(request):
    """
    Request password reset.
    
    POST /api/v1/accounts/password/forgot/
    
    Body:
    {
        "email": "user@example.com"
    }
    
    Security: Always returns same response to prevent email enumeration.
    """
    
    try:
        data = json.loads(request.body)
        
        if 'email' not in data:
            logger.warning("Password reset request: Missing email")
            return bad_request("Email is required", request=request)
        
        email = data['email']
        

        
        # Find user (don't reveal if user exists for security)
        try:
            user = User.objects.get(email=email, is_active=True)
            
            # Generate reset token
            reset_token = password_reset_token_manager.generate_token(user.id)
            
            # Send password reset email
            email_sent = email_service.send_password_reset_email(user, reset_token)
            
            
            
            if email_sent:
                logger.info("Password reset email sent", email=email, user_id=user.id)
            else:
                logger.error("Failed to send password reset email", email=email, user_id=user.id)
            
        except User.DoesNotExist:
            # Still log but don't reveal to client (security best practice)
            logger.info("Password reset requested for non-existent email", email=email)
        
        # Always return success to prevent email enumeration
        return ok(
            message="If an account exists with that email, you will receive password reset instructions.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Password reset request: Invalid JSON")
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Password reset request error: {str(e)}", exc_info=True)
        return server_error("Failed to process request", request=request)


@csrf_exempt
@require_http_methods(["POST"])
def reset_password(request):
    """
    Reset password using token.
    
    POST /api/v1/accounts/password/reset/
    
    Body:
    {
        "token": "reset_token_here",
        "new_password": "NewSecurePass123!"
    }
    """
    try:
        data = json.loads(request.body)
        
        if 'token' not in data or 'new_password' not in data:
            logger.warning("Password reset: Missing token or new password")
            return bad_request(
                "Token and new password are required",
                request=request
            )
        
        token = data['token']
        new_password = data['new_password']
        
        # Validate token
        try:
            user_id = password_reset_token_manager.validate_token(token)
        except PasswordResetTokenExpired:
            logger.warning("Password reset failed: Token expired", token_preview=f"{token[:20]}...")
            return bad_request(
                "Reset token has expired. Please request a new one.",
                request=request
            )
        except PasswordResetTokenInvalid:
            logger.warning("Password reset failed: Invalid token", token_preview=f"{token[:20]}...")
            return bad_request(
                "Invalid reset token. Please request a new one.",
                request=request
            )
        
        if not user_id:
            logger.warning("Password reset failed: Token validation returned no user")
            return bad_request(
                "Invalid or expired reset token. Please request a new one.",
                request=request
            )
        
        # Get user
        try:
            user = User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            logger.error("Password reset failed: User not found", user_id=user_id)
            return not_found("User not found", request=request)
        
        # Validate password strength
        password_errors = validate_password_strength(new_password)
        if password_errors:
            logger.warning("Password reset failed: Password validation errors", 
                          user_id=user.id, errors=password_errors)
            return validation_error(
                {'new_password': password_errors},
                "Please make sure all fields are properly filled",
                request=request
            )
        
        # Update password
        user.set_password(new_password)
        user.save()
        
        logger.info("Password reset successful", user_id=user.id, email=user.email)
        
        # Send success email (optional, ignore if fails)
        try:
            email_service.send_password_reset_success_email(user)
            logger.debug("Password reset success email sent", user_id=user.id)
        except Exception as e:
            logger.warning(f"Failed to send password reset success email: {str(e)}", user_id=user.id)
        
        return ok(
            message="Password has been reset successfully. You can now log in with your new password.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Password reset: Invalid JSON")
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Password reset error: {str(e)}", exc_info=True)
        return server_error("Failed to reset password", request=request)


@csrf_exempt
@require_http_methods(["POST"])
def resend_reset_email(request):
    """
    Resend password reset email.
    
    POST /api/v1/accounts/password/resend/
    
    Body:
    {
        "email": "user@example.com"
    }
    """
    try:
        data = json.loads(request.body)
        
        if 'email' not in data:
            logger.warning("Resend reset email: Missing email")
            return bad_request("Email is required", request=request)
        
        email = data['email']
        
        # Find user
        try:
            user = User.objects.get(email=email, is_active=True)
            
            # Generate new reset token
            reset_token = password_reset_token_manager.generate_token(user.id)
            
            # Send password reset email
            email_sent = email_service.send_password_reset_email(user, reset_token)
            
            if email_sent:
                logger.info("Password reset email resent", email=email, user_id=user.id)
            else:
                logger.error("Failed to resend password reset email", email=email, user_id=user.id)
            
        except User.DoesNotExist:
            # Don't reveal that user doesn't exist
            logger.info("Resend reset email requested for non-existent email", email=email)
        
        # Always return same response
        return ok(
            message="If an account exists with that email, a new reset link will be sent.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Resend reset email: Invalid JSON")
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Resend reset email error: {str(e)}", exc_info=True)
        return server_error("Failed to process request", request=request)


# Admin endpoints
@jwt_required
@csrf_exempt
@admin_required
@require_http_methods(["GET"])
def admin_users(request):
    """
    List all users (admin only).
    
    GET /api/v1/accounts/admin/users/
    """
    admin_email = request.user.email
    
    logger.info("Admin user list accessed", admin_email=admin_email, admin_id=request.user.id)
    
    users = User.objects.all().order_by('-date_joined')
    
    user_list = [{
        'id': u.id,
        'username': u.username,
        'email': u.email,
        'first_name': u.first_name,
        'last_name': u.last_name,
        'email_verified': u.email_verified,
        'phone_number': u.phone_number,
        'role': u.role,
        'gender': u.gender,
        'avatar_config': u.avatar_config,
        'is_active': u.is_active,
        'date_joined': u.date_joined,
        'last_login': u.last_login
    } for u in users]
    
    logger.debug(f"Admin retrieved {len(user_list)} users", 
                admin_email=admin_email, 
                user_count=len(user_list))
    
    return ok(
        data=user_list,
        message="Users retrieved",
        request=request
    )


@jwt_required
@admin_required
@csrf_exempt
@require_http_methods(["GET"])
def admin_user_detail(request, user_id):
    """
    Get user details (admin only).
    
    GET /api/v1/accounts/admin/users/<user_id>/
    """
    admin_email = request.user.email
    
    try:
        user = User.objects.get(id=user_id)
        
        logger.info("Admin viewed user details", 
                   admin_email=admin_email, 
                   viewed_user_id=user_id,
                   viewed_user_email=user.email)
        
        return ok(
            data={
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone_number': user.phone_number,
                'role': user.role,
                'gender': user.gender,
                'avatar_config': user.avatar_config,
                'is_active': user.is_active,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'date_joined': user.date_joined,
                'last_login': user.last_login,
                'email_verified': user.email_verified
            },
            message="User details retrieved",
            request=request
        )
        
    except User.DoesNotExist:
        logger.warning("Admin attempted to view non-existent user", 
                      admin_email=admin_email, 
                      user_id=user_id)
        return not_found(f"User with id {user_id} not found", request=request)


@jwt_required
@csrf_exempt
@admin_required
@require_http_methods(["POST"])
def admin_update_user(request, user_id):
    """
    Update user (admin only).
    
    POST /api/v1/accounts/admin/users/<user_id>/update/
    """
    admin_email = request.user.email
    
    try:
        user = User.objects.get(id=user_id)
        data = json.loads(request.body)
        
        # Fields admin can update
        allowed_fields = ['first_name', 'last_name', 'phone_number', 'role', 'is_active', 'gender', 'avatar_config']
        updated_fields = []
        
        for field in allowed_fields:
            if field in data:
                old_value = getattr(user, field)
                new_value = data[field]
                
                # Handle avatar_config specially (merge with existing)
                if field == 'avatar_config':
                    current_config = user.avatar_config or {}
                    current_config.update(new_value)
                    new_value = current_config
                
                if old_value != new_value:
                    setattr(user, field, new_value)
                    updated_fields.append(f"{field}: {old_value} -> {new_value}")
        
        if updated_fields:
            user.save()
            logger.info("Admin updated user", 
                       admin_email=admin_email,
                       admin_id=request.user.id,
                       updated_user_id=user_id,
                       updated_user_email=user.email,
                       changes=updated_fields)
        
        return ok(
            message="User updated successfully",
            request=request
        )
        
    except User.DoesNotExist:
        logger.warning("Admin attempted to update non-existent user", 
                      admin_email=admin_email, 
                      user_id=user_id)
        return not_found(f"User with id {user_id} not found", request=request)
    except json.JSONDecodeError:
        logger.warning("Admin update user: Invalid JSON", admin_email=admin_email)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Admin update user error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@admin_required
@csrf_exempt
@require_http_methods(["POST"])
def admin_activate_user(request, user_id):
    """
    Activate a user account (admin only).
    
    POST /api/v1/accounts/admin/users/<user_id>/activate/
    """
    admin_email = request.user.email
    
    try:
        user = User.objects.get(id=user_id)
        
        # Prevent activating yourself
        if user.id == request.user.id:
            logger.warning("Admin attempted to activate own account", admin_email=admin_email)
            return bad_request("You cannot activate your own account", request=request)
        
        if user.is_active:
            logger.warning("Admin attempted to activate already active user", 
                          admin_email=admin_email,
                          target_user=user.email)
            return bad_request(f"User {user.email} is already active", request=request)
        
        user.is_active = True
        user.save()
        
        logger.info("Admin activated user", 
                   admin_email=admin_email,
                   admin_id=request.user.id,
                   activated_user_id=user_id,
                   activated_user_email=user.email)
        
        return ok(
            data={
                'id': user.id,
                'email': user.email,
                'is_active': user.is_active,
                'role': user.role
            },
            message=f"User {user.email} has been activated successfully",
            request=request
        )
        
    except User.DoesNotExist:
        logger.warning("Admin attempted to activate non-existent user", 
                      admin_email=admin_email, 
                      user_id=user_id)
        return not_found(f"User with id {user_id} not found", request=request)
    except Exception as e:
        logger.error(f"Admin activate user error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@admin_required
@csrf_exempt
@require_http_methods(["POST"])
def admin_deactivate_user(request, user_id):
    """
    Deactivate a user account (admin only).
    
    POST /api/v1/accounts/admin/users/<user_id>/deactivate/
    """
    admin_email = request.user.email
    
    try:
        user = User.objects.get(id=user_id)
        
        # Prevent deactivating yourself
        if user.id == request.user.id:
            logger.warning("Admin attempted to deactivate own account", admin_email=admin_email)
            return bad_request("You cannot deactivate your own account", request=request)
        
        if not user.is_active:
            logger.warning("Admin attempted to deactivate already inactive user", 
                          admin_email=admin_email,
                          target_user=user.email)
            return bad_request(f"User {user.email} is already deactivated", request=request)
        
        user.is_active = False
        user.save()
        
        logger.info("Admin deactivated user", 
                   admin_email=admin_email,
                   admin_id=request.user.id,
                   deactivated_user_id=user_id,
                   deactivated_user_email=user.email)
        
        return ok(
            data={
                'id': user.id,
                'email': user.email,
                'is_active': user.is_active,
                'role': user.role
            },
            message=f"User {user.email} has been deactivated successfully",
            request=request
        )
        
    except User.DoesNotExist:
        logger.warning("Admin attempted to deactivate non-existent user", 
                      admin_email=admin_email, 
                      user_id=user_id)
        return not_found(f"User with id {user_id} not found", request=request)
    except Exception as e:
        logger.error(f"Admin deactivate user error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@admin_required
@csrf_exempt
@require_http_methods(["POST"])
def admin_bulk_activate_deactivate(request):
    """
    Bulk activate or deactivate users (admin only).
    
    POST /api/v1/accounts/admin/users/bulk-status/
    
    Body: {
        "action": "activate",  // or "deactivate"
        "user_ids": [1, 2, 3]
    }
    """
    admin_email = request.user.email
    
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        if 'action' not in data or 'user_ids' not in data:
            logger.warning("Bulk status change: Missing required fields", admin_email=admin_email)
            return bad_request("action and user_ids are required", request=request)
        
        action = data['action']
        user_ids = data['user_ids']
        
        # Validate action
        if action not in ['activate', 'deactivate']:
            logger.warning("Bulk status change: Invalid action", admin_email=admin_email, action=action)
            return bad_request("Invalid action. Must be 'activate' or 'deactivate'", request=request)
        
        # Get users excluding the current admin
        users = User.objects.filter(id__in=user_ids).exclude(id=request.user.id)
        
        if not users.exists():
            logger.warning("Bulk status change: No valid users found", 
                          admin_email=admin_email, 
                          user_ids=user_ids)
            return bad_request("No valid users found for this operation", request=request)
        
        results = {
            'success': [],
            'failed': []
        }
        
        # Process based on action
        if action == 'activate':
            for user in users:
                try:
                    if not user.is_active:
                        user.is_active = True
                        user.save()
                        results['success'].append({
                            'id': user.id,
                            'email': user.email,
                            'message': 'Activated successfully'
                        })
                    else:
                        results['failed'].append({
                            'id': user.id,
                            'email': user.email,
                            'message': 'Already active'
                        })
                except Exception as e:
                    results['failed'].append({
                        'id': user.id,
                        'email': user.email,
                        'message': str(e)
                    })
        
        elif action == 'deactivate':
            for user in users:
                try:
                    if user.is_active:
                        user.is_active = False
                        user.save()
                        results['success'].append({
                            'id': user.id,
                            'email': user.email,
                            'message': 'Deactivated successfully'
                        })
                    else:
                        results['failed'].append({
                            'id': user.id,
                            'email': user.email,
                            'message': 'Already deactivated'
                        })
                except Exception as e:
                    results['failed'].append({
                        'id': user.id,
                        'email': user.email,
                        'message': str(e)
                    })
        
        logger.info(f"Bulk {action} completed", 
                   admin_email=admin_email,
                   action=action,
                   succeeded=len(results['success']),
                   failed=len(results['failed']))
        
        return ok(
            data=results,
            message=f"Bulk {action} completed. {len(results['success'])} succeeded, {len(results['failed'])} failed.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Bulk status change: Invalid JSON", admin_email=admin_email)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Bulk status change error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@admin_required
@csrf_exempt
@require_http_methods(["POST"])
def admin_change_user_role(request, user_id):
    """
    Change a single user's role (admin only).
    
    POST /api/v1/accounts/admin/users/<user_id>/change-role/
    
    Body: {
        "role": "ADMIN"  // ADMIN, STAFF, or USER
    }
    """
    admin_email = request.user.email
    
    try:
        user = User.objects.get(id=user_id)
        data = json.loads(request.body)
        
        # Validate role field
        if 'role' not in data:
            logger.warning("Role change: Missing role field", admin_email=admin_email)
            return bad_request("role field is required", request=request)
        
        new_role = data['role'].upper()
        
        # Validate role value
        valid_roles = [role.value for role in User.Role]
        if new_role not in valid_roles:
            logger.warning("Role change: Invalid role value", 
                          admin_email=admin_email, 
                          role=new_role)
            return validation_error(
                {'role': [f"Invalid role. Must be one of: {', '.join(valid_roles)}"]},
                request=request
            )
        
        # Prevent changing your own role
        if user.id == request.user.id:
            logger.warning("Admin attempted to change own role", admin_email=admin_email)
            return bad_request("You cannot change your own role", request=request)
        
        old_role = user.role
        user.role = new_role
        user.save()
        
        logger.info("Admin changed user role", 
                   admin_email=admin_email,
                   admin_id=request.user.id,
                   target_user_id=user_id,
                   target_user_email=user.email,
                   old_role=old_role,
                   new_role=new_role)
        
        return ok(
            data={
                'id': user.id,
                'email': user.email,
                'old_role': old_role,
                'new_role': user.role
            },
            message=f"User {user.email} role changed from {old_role} to {user.role}",
            request=request
        )
        
    except User.DoesNotExist:
        logger.warning("Admin attempted to change role for non-existent user", 
                      admin_email=admin_email, 
                      user_id=user_id)
        return not_found(f"User with id {user_id} not found", request=request)
    except json.JSONDecodeError:
        logger.warning("Role change: Invalid JSON", admin_email=admin_email)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Role change error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@admin_required
@csrf_exempt
@require_http_methods(["POST"])
def admin_bulk_change_role(request):
    """
    Bulk change roles for multiple users (admin only).
    
    POST /api/v1/accounts/admin/users/bulk-change-role/
    
    Body: {
        "role": "ADMIN",  // ADMIN, STAFF, or USER
        "user_ids": [1, 2, 3]
    }
    """
    admin_email = request.user.email
    
    try:
        data = json.loads(request.body)
        
        # Validate required fields
        if 'role' not in data or 'user_ids' not in data:
            logger.warning("Bulk role change: Missing required fields", admin_email=admin_email)
            return bad_request("role and user_ids are required", request=request)
        
        new_role = data['role'].upper()
        user_ids = data['user_ids']
        
        # Validate role value
        valid_roles = [role.value for role in User.Role]
        if new_role not in valid_roles:
            logger.warning("Bulk role change: Invalid role value", 
                          admin_email=admin_email, 
                          role=new_role)
            return bad_request(f"Invalid role. Must be one of: {', '.join(valid_roles)}", request=request)
        
        # Get users excluding the current admin
        users = User.objects.filter(id__in=user_ids).exclude(id=request.user.id)
        
        if not users.exists():
            logger.warning("Bulk role change: No valid users found", 
                          admin_email=admin_email, 
                          user_ids=user_ids)
            return bad_request("No valid users found for this operation", request=request)
        
        results = {
            'success': [],
            'failed': []
        }
        
        for user in users:
            try:
                old_role = user.role
                user.role = new_role
                user.save()
                results['success'].append({
                    'id': user.id,
                    'email': user.email,
                    'old_role': old_role,
                    'new_role': new_role,
                    'message': f'Role changed from {old_role} to {new_role}'
                })
            except Exception as e:
                results['failed'].append({
                    'id': user.id,
                    'email': user.email,
                    'message': str(e)
                })
        
        logger.info("Bulk role change completed", 
                   admin_email=admin_email,
                   new_role=new_role,
                   succeeded=len(results['success']),
                   failed=len(results['failed']))
        
        return ok(
            data=results,
            message=f"Bulk role change completed. {len(results['success'])} succeeded, {len(results['failed'])} failed.",
            request=request
        )
        
    except json.JSONDecodeError:
        logger.warning("Bulk role change: Invalid JSON", admin_email=admin_email)
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Bulk role change error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)
    
    
    
    

@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def setup_mfa(request):
    """
    Setup MFA for user.
    
    POST /api/v1/accounts/mfa/setup/
    
    Headers:
        Authorization: Bearer <access_token>
    
    Body:
    {
        "method": "email" or "app"
    }
    """
    try:
        data = json.loads(request.body)
        method = data.get('method')
        
        if method not in ['app', 'email']:
            return bad_request("Invalid MFA method", request=request)
        
        user = request.user
        
        # Generate secret for app-based MFA
        if method == 'app':
            secret = user.generate_mfa_secret()
            user.mfa_method = 'app'
            user.save()
            
            return ok(
                data={
                    'method': 'app',
                    'secret': secret,
                    'otp_uri': user.get_mfa_otp_uri(),
                    'message': 'Scan QR code with authenticator app'
                },
                message="MFA setup initiated",
                request=request
            )
        
        # For email MFA, send verification code
        elif method == 'email':
            # Generate and send verification code
            verification_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
            
            # Store code in cache or session (use Django cache)
            from django.core.cache import cache
            cache_key = f"mfa_email_verify_{user.id}"
            cache.set(cache_key, verification_code, timeout=300)  # 5 minutes
            
            # Send email with code
            email_service.send_mfa_setup_email(user, verification_code)
            
            user.mfa_method = 'email'
            user.save()
            
            return ok(
                data={
                    'method': 'email',
                    'message': 'Verification code sent to your email'
                },
                message="MFA setup initiated",
                request=request
            )
            
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"MFA setup error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def verify_mfa_setup(request):
    """
    Verify MFA setup.
    
    POST /api/v1/accounts/mfa/verify/
    
    Headers:
        Authorization: Bearer <access_token>
    
    Body:
    {
        "code": "123456"
    }
    """
    try:
        data = json.loads(request.body)
        code = data.get('code')
        
        if not code:
            return bad_request("Verification code required", request=request)
        
        user = request.user
        
        if user.mfa_method == 'app':
            # Verify app-based TOTP code
            if not user.verify_mfa_code(code):
                return bad_request("Invalid verification code", request=request)
            
            # Generate backup codes
            backup_codes = user.generate_backup_codes()
            user.mfa_enabled = True
            user.save()
            
            return ok(
                data={
                    'backup_codes': backup_codes,
                    'message': 'MFA enabled successfully'
                },
                message="MFA enabled",
                request=request
            )
        
        elif user.mfa_method == 'email':
            # Verify email code from cache
            from django.core.cache import cache
            cache_key = f"mfa_email_verify_{user.id}"
            stored_code = cache.get(cache_key)
            
            if not stored_code or stored_code != code:
                return bad_request("Invalid or expired verification code", request=request)
            
            user.mfa_enabled = True
            user.mfa_email_verified = True
            user.save()
            
            # Clear the cache
            cache.delete(cache_key)
            
            return ok(
                data={
                    'message': 'Email MFA enabled successfully'
                },
                message="MFA enabled",
                request=request
            )
        
        return bad_request("MFA not initialized", request=request)
        
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"MFA verification error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["POST"])
def disable_mfa(request):
    """
    Disable MFA for user.
    
    POST /api/v1/accounts/mfa/disable/
    
    Headers:
        Authorization: Bearer <access_token>
    
    Body:
    {
        "password": "user_password"
    }
    """
    try:
        data = json.loads(request.body)
        password = data.get('password')
        
        if not password:
            return bad_request("Password required to disable MFA", request=request)
        
        user = request.user
        
        # Verify password
        if not user.check_password(password):
            return unauthorized("Invalid password", request=request)
        
        # Disable MFA
        user.mfa_enabled = False
        user.mfa_method = None
        user.mfa_secret = None
        user.mfa_email_verified = False
        user.mfa_backup_codes = []
        user.save()
        
        logger.info(f"MFA disabled for user {user.email}")
        
        return ok(
            message="MFA disabled successfully",
            request=request
        )
        
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"MFA disable error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@csrf_exempt
@require_http_methods(["POST"])
def verify_mfa_login(request):
    """
    Verify MFA code during login.
    
    POST /api/v1/accounts/mfa/verify-login/
    
    Body:
    {
        "user_id": 1,
        "code": "123456"
    }
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        code = data.get('code')
        
        if not user_id or not code:
            return bad_request("User ID and verification code required", request=request)
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return not_found("User not found", request=request)
        
        if not user.mfa_enabled:
            return bad_request("MFA not enabled for this user", request=request)
        
        # Verify based on method
        verified = False
        
        if user.mfa_method == 'app':
            verified = user.verify_mfa_code(code)
        elif user.mfa_method == 'email':
            # For email MFA, verify the code (you'd need to store it temporarily)
            from django.core.cache import cache
            cache_key = f"mfa_login_{user.id}"
            stored_code = cache.get(cache_key)
            verified = stored_code == code
            cache.delete(cache_key)  # One-time use
        
        if not verified:
            return unauthorized("Invalid MFA code", request=request)
        
        # Generate new tokens after successful MFA
        access_token, refresh_token = generate_tokens(user)
        
        return ok(
            data={
                 'user': {
                    'id': user.id,
                    'email': user.email,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'role': user.role,
                    'gender': user.gender,
                    'avatar_config': user.avatar_config,
                    'phone_number': user.phone_number,
                    'email_verified': user.email_verified
                },
                'tokens': {
                    'access': access_token,
                    'refresh': refresh_token,
                    'access_expires_in': 900,
                    'refresh_expires_in': 604800
                }
            },
            message="MFA verification successful",
            request=request
        )
        
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"MFA login verification error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)


@jwt_required
@csrf_exempt
@require_http_methods(["GET"])
def get_mfa_status(request):
    """
    Get MFA status for current user.
    
    GET /api/v1/accounts/mfa/status/
    
    Headers:
        Authorization: Bearer <access_token>
    """
    user = request.user
    
    return ok(
        data={
            'mfa_enabled': user.mfa_enabled,
            'mfa_method': user.mfa_method,
            'mfa_email_verified': user.mfa_email_verified if user.mfa_method == 'email' else None
        },
        message="MFA status retrieved",
        request=request
    )


@csrf_exempt
@require_http_methods(["POST"])
def send_mfa_email_code(request):
    """
    Send MFA code via email during login.
    
    POST /api/v1/accounts/mfa/send-email-code/
    
    Body:
    {
        "user_id": 1
    }
    """
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        
        if not user_id:
            return bad_request("User ID required", request=request)
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return not_found("User not found", request=request)
        
        if not user.mfa_enabled or user.mfa_method != 'email':
            return bad_request("Email MFA not enabled for this user", request=request)
        
        # Generate 6-digit code
        verification_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        
        # Store in cache
        from django.core.cache import cache
        cache_key = f"mfa_login_{user.id}"
        cache.set(cache_key, verification_code, timeout=300)  # 5 minutes
        
        # Send email
        email_service.send_mfa_login_email(user, verification_code)
        
        return ok(
            message="Verification code sent to your email",
            request=request
        )
        
    except json.JSONDecodeError:
        return bad_request("Invalid JSON", request=request)
    except Exception as e:
        logger.error(f"Send MFA email error: {str(e)}", exc_info=True)
        return server_error(str(e), request=request)

