"""
Authentication decorators for protecting views.
Atomic Design Level: Atom
"""

from functools import wraps

# Import Django modules inside functions to avoid app registry issues
# from ..api_responses.response_handler import response
from ..api_responses.response_handler import unauthorized,forbidden

def jwt_required(view_func):
    """
    Decorator to require valid JWT access token.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from ..security.tokens import token_manager
        
        auth_header = request.headers.get('Authorization', '')
        
        if not auth_header.startswith('Bearer '):
            return unauthorized(
                "Authentication required. Format: Authorization: Bearer <token>",
                request=request
            )
        
        token = auth_header.split(' ')[1]
        
        try:
            # Get user from token
            user = token_manager.get_user_from_token(token)
            request.user = user
            
            # Also get payload for additional data
            payload = token_manager.verify_token(token)
            request.token_payload = payload
            
            return view_func(request, *args, **kwargs)
            
        except Exception as e:
            return unauthorized(str(e), request=request)
    
    return wrapper


def jwt_optional(view_func):
    """
    Decorator that optionally authenticates with JWT.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # Import inside function
        from django.contrib.auth.models import AnonymousUser
        from ..security.tokens import token_manager
        
        auth_header = request.headers.get('Authorization', '')
        
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            
            try:
                user = token_manager.get_user_from_token(token)
                request.user = user
                payload = token_manager.verify_token(token)
                request.token_payload = payload
            except Exception:
                request.user = AnonymousUser()
                request.token_payload = None
        else:
            request.user = AnonymousUser()
            request.token_payload = None
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def admin_required(view_func):
    """
    Decorator to require admin role.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return unauthorized("Authentication required", request=request)
        
        # Check if user is admin
        user_role = getattr(request.user, 'role', 'USER')
        if user_role != 'ADMIN' and not request.user.is_superuser:
            return forbidden("Admin access required", request=request)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def staff_required(view_func):
    """
    Decorator to require staff role.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return unauthorized("Authentication required", request=request)
        
        # Check if user is staff or admin
        user_role = getattr(request.user, 'role', 'USER')
        if user_role not in ['ADMIN', 'STAFF'] and not request.user.is_staff:
            return forbidden("Staff access required", request=request)
        
        return view_func(request, *args, **kwargs)
    
    return wrapper