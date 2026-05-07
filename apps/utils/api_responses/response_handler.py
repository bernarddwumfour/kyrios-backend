from django.http import JsonResponse
from django.db.models import QuerySet, Model
from django.forms.models import model_to_dict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from typing import Any, Dict, List, Optional
import json


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for handling Django models and other complex types"""
    
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat() + 'Z'
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, Model):
            return model_to_dict(obj)
        if isinstance(obj, QuerySet):
            return list(obj.values())
        if hasattr(obj, 'isoformat'):  # Handle date, time, etc
            return obj.isoformat()
        return super().default(obj)


class APIResponse:
    """
    Standard API Response formatter.
    
    Industry Standard Format:
    {
        "status": "success|error|fail",
        "code": 200,
        "message": "Human readable message",
        "data": {},    # Response payload
        "errors": [],  # Validation/error details
        "meta": {      # Additional metadata
            "timestamp": "2024-01-01T00:00:00Z",
            "version": "v1",
            "request_id": null
        }
    }
    """
    
    # Class-level constants
    STATUS_SUCCESS = 'success'
    STATUS_ERROR = 'error'
    STATUS_FAIL = 'fail'
    API_VERSION = 'v1'
    
    def __init__(self):
        # Don't store state in instance - build fresh each time
        pass
    
    def _get_timestamp(self):
        """Get current UTC timestamp"""
        return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    def _get_request_id(self, request=None):
        """Extract request ID if available"""
        if request and hasattr(request, 'request_id'):
            return request.request_id
        return None
    
    def _format_errors(self, errors: Any) -> List[Dict]:
        """Format errors consistently"""
        if errors is None:
            return []
        
        # If errors is already a list of dicts with field/message
        if isinstance(errors, list) and all(isinstance(e, dict) for e in errors):
            return errors
        
        # If errors is a list of strings
        if isinstance(errors, list):
            return [{'message': str(e)} for e in errors]
        
        # If errors is a dict (field -> errors)
        if isinstance(errors, dict):
            formatted = []
            for field, field_errors in errors.items():
                if isinstance(field_errors, list):
                    for err in field_errors:
                        formatted.append({
                            'field': field,
                            'message': str(err)
                        })
                else:
                    formatted.append({
                        'field': field,
                        'message': str(field_errors)
                    })
            return formatted
        
        # If errors is a single string
        return [{'message': str(errors)}]
    
    def _serialize_data(self, data: Any) -> Any:
        """
        Serialize complex data types to JSON-serializable format
        """
        if data is None:
            return None
        
        try:
            # Use custom JSON encoder to handle complex types
            return json.loads(json.dumps(data, cls=CustomJSONEncoder))
        except (TypeError, ValueError) as e:
            # If serialization fails, return error info
            return {'error': f'Data serialization failed: {str(e)}'}
    
    def _build_response(self, status: str, message: str, code: int, 
                       data: Any = None, errors: Any = None, 
                       meta: Optional[Dict] = None, request=None) -> JsonResponse:
        """
        Build a JSON response with consistent structure
        """
        response_data = {
            'status': status,
            'code': code,
            'message': message,
            'data': self._serialize_data(data),
            'errors': self._format_errors(errors),
            'meta': {
                'timestamp': self._get_timestamp(),
                'version': self.API_VERSION,
                'request_id': self._get_request_id(request),
                **(meta or {})
            }
        }
        
        return JsonResponse(
            response_data,
            status=code,
            encoder=CustomJSONEncoder,
            json_dumps_params={'indent': 2} if code < 300 else None
        )
    
    def success(self, data: Any = None, message: str = "Operation successful", 
                status_code: int = 200, meta: Optional[Dict] = None, 
                request=None) -> JsonResponse:
        """Success response (2xx status codes)"""
        return self._build_response(
            self.STATUS_SUCCESS, message, status_code, data, None, meta, request
        )
    
    def error(self, message: str = "An error occurred", status_code: int = 500, 
              errors: Any = None, meta: Optional[Dict] = None, 
              request=None) -> JsonResponse:
        """Error response (5xx status codes) - Server errors"""
        return self._build_response(
            self.STATUS_ERROR, message, status_code, None, errors, meta, request
        )
    
    def fail(self, message: str = "Validation failed", status_code: int = 400, 
             errors: Any = None, meta: Optional[Dict] = None, 
             request=None) -> JsonResponse:
        """Fail response (4xx status codes) - Client errors"""
        return self._build_response(
            self.STATUS_FAIL, message, status_code, None, errors, meta, request
        )

# Create singleton instance
response = APIResponse()


# ============================================================================
# Convenience functions with request support
# ============================================================================

def ok(data: Any = None, message: str = "Success", meta: Optional[Dict] = None, 
       request=None) -> JsonResponse:
    """200 OK response"""
    return response.success(data, message, 200, meta, request)


def created(data: Any = None, message: str = "Resource created", 
            meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """201 Created response"""
    return response.success(data, message, 201, meta, request)


def accepted(data: Any = None, message: str = "Request accepted", 
             meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """202 Accepted response"""
    return response.success(data, message, 202, meta, request)





def bad_request(message: str = "Bad request", errors: Any = None, 
                meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """400 Bad Request response"""
    return response.fail(message, 400, errors, meta, request)


def unauthorized(message: str = "Unauthorized", errors: Any = None, 
                 meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """401 Unauthorized response"""
    return response.fail(message, 401, errors, meta, request)


def forbidden(message: str = "Forbidden", errors: Any = None, 
              meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """403 Forbidden response"""
    return response.fail(message, 403, errors, meta, request)


def not_found(message: str = "Resource not found", errors: Any = None, 
              meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """404 Not Found response"""
    return response.fail(message, 404, errors, meta, request)


def method_not_allowed(message: str = "Method not allowed", errors: Any = None, 
                       meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """405 Method Not Allowed response"""
    return response.fail(message, 405, errors, meta, request)


def conflict(message: str = "Resource conflict", errors: Any = None, 
             meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """409 Conflict response"""
    return response.fail(message, 409, errors, meta, request)


def validation_error(errors: Any, message: str = "Validation failed", 
                     meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """422 Unprocessable Entity - validation errors"""
    return response.fail(message, 422, errors, meta, request)


def too_many_requests(message: str = "Too many requests", 
                      meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """429 Too Many Requests response"""
    return response.fail(message, 429, None, meta, request)


def server_error(message: str = "Internal server error", errors: Any = None, 
                 meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """500 Internal Server Error response"""
    return response.error(message, 500, errors, meta, request)


def not_implemented(message: str = "Not implemented", errors: Any = None, 
                    meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """501 Not Implemented response"""
    return response.error(message, 501, errors, meta, request)


def service_unavailable(message: str = "Service unavailable", 
                        meta: Optional[Dict] = None, request=None) -> JsonResponse:
    """503 Service Unavailable response"""
    return response.error(message, 503, None, meta, request)