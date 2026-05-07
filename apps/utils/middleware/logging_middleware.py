"""
API logging middleware to log all requests and responses.
Atomic Design Level: Molecule
"""

import time
import json
from django.utils.deprecation import MiddlewareMixin
from ..helpers.logging import get_logger

logger = get_logger('api.requests')


class APILoggingMiddleware(MiddlewareMixin):
    """
    Middleware that logs all API requests and responses.
    
    Logs:
    - Request method, path, IP, user agent
    - Response status code
    - Request duration
    - Request body (optional, be careful with sensitive data)
    """
    
    def process_request(self, request):
        """Log incoming request"""
        request.start_time = time.time()
        
        # Don't log sensitive endpoints with full body
        sensitive_paths = ['/login', '/register', '/password']
        log_body = not any(path in request.path for path in sensitive_paths)
        
        log_data = {
            'method': request.method,
            'path': request.path,
            'ip': self._get_client_ip(request),
            'user_agent': request.headers.get('User-Agent', 'unknown'),
        }
        
        # Log request body for non-sensitive endpoints (optional)
        if log_body and request.method in ['POST', 'PUT', 'PATCH'] and request.body:
            try:
                body = json.loads(request.body)
                # Don't log passwords
                if 'password' in body:
                    body['password'] = '***REDACTED***'
                log_data['body'] = body
            except :
                pass
        
        logger.info(f"Request: {request.method} {request.path}", **log_data)
    
    def process_response(self, request, response):
        """Log response"""
        duration = time.time() - request.start_time if hasattr(request, 'start_time') else 0
        
        log_data = {
            'method': request.method,
            'path': request.path,
            'status_code': response.status_code,
            'duration_ms': round(duration * 1000, 2),
        }
        
        if response.status_code >= 400:
            logger.warning(f"Response: {response.status_code}", **log_data)
        else:
            logger.info(f"Response: {response.status_code}", **log_data)
        
        return response
    
    def process_exception(self, request, exception):
        """Log unhandled exceptions"""
        logger.error(
            f"Unhandled exception: {str(exception)}",
            method=request.method,
            path=request.path,
            exc_info=True
        )
        return None
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.headers.get('X-Forwarded-For')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip