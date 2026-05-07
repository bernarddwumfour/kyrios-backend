"""
Structured logging with request ID support.
Atomic Design Level: Atom
"""

import logging
import json
from datetime import datetime
from typing import Dict, Optional
from ..middleware.request_id import get_current_request_id


class RequestIDLogger:
    """
    Logger that automatically includes request ID in all log entries.
    
    Features:
    - Automatically adds request_id to every log
    - Supports structured logging (JSON format)
    - Includes timestamp, module, function, line number
    - Thread-safe
    
    Usage:
        from apps.utils.helpers.logging import get_logger
        
        logger = get_logger(__name__)
        
        logger.info("User logged in", user_id=123)
        logger.error("Database connection failed", db='postgres')
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name
    
    def _get_extra_context(self, extra: Optional[Dict] = None) -> Dict:
        """Build extra context with request ID and timestamp"""
        context = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'logger_name': self.name,
        }
        
        # Add request ID if available
        request_id = get_current_request_id()
        if request_id:
            context['request_id'] = request_id
        
        # Add custom extra fields (filter out reserved parameters)
        if extra:
            # Reserved parameters that should not be added to extra context
            reserved = ('exc_info', 'stack_info', 'stacklevel')
            for key, value in extra.items():
                if key not in reserved:
                    context[key] = value
        
        return context
    
    def _log(self, level: int, message: str, extra: Optional[Dict] = None, 
             exc_info: bool = False):
        """Internal logging method"""
        context = self._get_extra_context(extra)
        
        # Pass exc_info as a proper logging parameter, not in extra context
        self.logger.log(level, message, extra=context, exc_info=exc_info)
    
    def debug(self, message: str, **extra):
        """Log debug message"""
        self._log(logging.DEBUG, message, extra)
    
    def info(self, message: str, **extra):
        """Log info message"""
        self._log(logging.INFO, message, extra)
    
    def warning(self, message: str, **extra):
        """Log warning message"""
        self._log(logging.WARNING, message, extra)
    
    def error(self, message: str, exc_info: bool = True, **extra):
        """Log error message"""
        self._log(logging.ERROR, message, extra, exc_info)
    
    def critical(self, message: str, exc_info: bool = True, **extra):
        """Log critical message"""
        self._log(logging.CRITICAL, message, extra, exc_info)


# Convenience function to get a logger
def get_logger(name: str) -> RequestIDLogger:
    """
    Get a request-ID enabled logger.
    
    Usage:
        logger = get_logger(__name__)
        logger.info("Something happened", user_id=123)
    """
    return RequestIDLogger(name)


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs JSON for structured logging.
    Ideal for production environments and log aggregation tools.
    """
    
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'name': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add request ID if present in extra
        if hasattr(record, 'request_id'):
            log_entry['request_id'] = record.request_id
        
        # Add any extra fields from the record (skip reserved ones)
        reserved = ('name', 'msg', 'args', 'levelname', 'levelno', 'pathname', 
                   'filename', 'module', 'exc_info', 'exc_text', 'stack_info', 
                   'lineno', 'funcName', 'created', 'msecs', 'relativeCreated', 
                   'thread', 'threadName', 'processName', 'process', 'message')
        
        if hasattr(record, '__dict__'):
            for key, value in record.__dict__.items():
                if key not in log_entry and key not in reserved:
                    log_entry[key] = value
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry)