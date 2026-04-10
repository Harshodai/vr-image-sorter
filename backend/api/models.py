from pydantic import BaseModel
from typing import List

class FileResponse(BaseModel):
    original_name: str
    new_name: str
    preview_url: str

class FailedFileResponse(BaseModel):
    original_name: str
    preview_url: str = None

class UploadResponse(BaseModel):
    session_id: str
    session_token: str
    processed: List[FileResponse]
    failed: List[FailedFileResponse]
    has_processed: bool
    has_failed: bool
    download_url: str = None
    failed_download_url: str = None

class ManualUploadRequest(BaseModel):
    vrcode: str

class SareeDetails(BaseModel):
    id: str  # Note: Actually it's the Item column in CSV, e.g., 'SA RE E 001'
    description: str
    amount: str
    rate: str
    discount: str

class RetryRequest(BaseModel):
    filenames: List[str]
