import re
import os
import secrets
from fastapi import HTTPException

# Global dictionary to store temporary session tracking in memory
# In a real enterprise app, this would be Redis/Memcached.
temp_dirs = {}

def validate_filename(filename: str) -> str:
    """Security: Prevent directory traversal and invalid characters"""
    safe_name = os.path.basename(filename)
    safe_name = re.sub(r'[^a-zA-Z0-9.\-_ ()]', '_', safe_name)
    if not safe_name or safe_name.startswith('.'):
        safe_name = f"unnamed_file_{secrets.token_hex(4)}"
    return safe_name

def validate_session_id(session_id: str) -> None:
    """Security: Validate UUID format to prevent path traversal via session_id"""
    if not re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', session_id):
        raise HTTPException(status_code=400, detail="Invalid session ID format")

def validate_session_token(session_id: str, auth_header: str) -> dict:
    """Security: Prevent unauthorized downloading of zips"""
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication")
        
    token = auth_header.split(" ")[1]
    import hashlib
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    
    if session_id not in temp_dirs:
        raise HTTPException(status_code=404, detail="Session not found or expired")
        
    session = temp_dirs[session_id]
    if session["token_hash"] != token_hash:
        raise HTTPException(status_code=403, detail="Invalid session token")
        
    return session

def generate_session_token() -> str:
    """Generate a secure random token for downloading session files"""
    return secrets.token_urlsafe(32)
