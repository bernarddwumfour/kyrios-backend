"""
Request ID middleware for request tracing.
Atomic Design Level: Molecule
"""

import uuid
import threading
from django.utils.deprecation import MiddlewareMixin

# Thread-local storage for request data
_thread_locals = threading.local()


def get_current_request_id():
    """Get the current request ID from thread-local storage"""
    return getattr(_thread_locals, 'request_id', None)


class RequestIDMiddleware(MiddlewareMixin):
    """
    Middleware that assigns a unique ID to every request.
    
    Features:
    - Adds request.id to every request object
    - Adds X-Request-ID header to response
    - Stores request ID in thread-local for logging
    - Accepts X-Request-ID header from client for distributed tracing
    """
    
    def process_request(self, request):
        """Generate or extract request ID"""
        # Check if client sent a request ID (for distributed tracing)
        request_id = request.headers.get('X-Request-ID')
        
        # Generate new if none exists
        if not request_id:
            request_id = str(uuid.uuid4())
        
        # Store on request object
        request.request_id = request_id
        
        # Store in thread-local for logging
        _thread_locals.request_id = request_id
    
    def process_response(self, request, response):
        """Add request ID to response headers"""
        if hasattr(request, 'request_id'):
            response['X-Request-ID'] = request.request_id
        
        # Clean up thread-local
        if hasattr(_thread_locals, 'request_id'):
            del _thread_locals.request_id
        
        return response