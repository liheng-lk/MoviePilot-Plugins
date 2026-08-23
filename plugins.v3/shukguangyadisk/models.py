"""MoviePilot V3 API response models for GuangYaDisk."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GuangYaConfigData(BaseModel):
    """Configuration/status payload consumed by the Vue remote component."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    access_token: str = ""
    refresh_token: str = ""
    client_id: str = ""
    device_id: str = ""
    poll_interval: int = 5
    page_size: int = 100
    order_by: int = 3
    sort_type: int = 1
    permanently_delete: bool = False
    upload_progress_log: bool = False
    logged_in: bool = False
    storage_name: str = "光鸭云盘助手"
    remote_status_available: bool = True
    remote_status_message: str = ""
    user_name: str = ""
    user_id: str = ""
    vip_level: str = ""
    member_expire_time: int = 0
    total_space: int = 0
    used_space: int = 0
    free_space: int = 0
    file_count: int = 0
    user_code: str = ""
    verification_uri: str = ""
    qr_expires_in: int = 0


class GuangYaConfigSaveResponse(BaseModel):
    """Config save response. Kept as the existing three-field envelope."""

    success: bool
    message: str = ""
    data: Optional[GuangYaConfigData] = None


class GuangYaActionResponse(BaseModel):
    """Flexible login/logout response while retaining a documented stable core."""

    model_config = ConfigDict(extra="allow")

    success: bool
    message: str = ""
    waiting: Optional[bool] = None
    stage: str = ""
    enabled: Optional[bool] = None
    device_id: str = ""
    user_code: str = ""
    verification_uri: str = ""
    verification_uri_complete: str = ""
    expires_in: int = 0
    has_access_token: Optional[bool] = None
    has_refresh_token: Optional[bool] = None
    phone_number: str = ""
    verification_id: str = ""
    captcha_token: str = ""


class GuangYaBrowseItem(BaseModel):
    """One file/directory returned by the browse endpoint."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: str
    path: str
    size: int = 0
    extension: str = ""
    modify_time: int = 0
    stream_url: Optional[str] = None


class GuangYaBrowseResponse(BaseModel):
    """Directory browse response."""

    model_config = ConfigDict(extra="allow")

    path: str = "/"
    name: str = ""
    type: str = "dir"
    items: List[GuangYaBrowseItem] = Field(default_factory=list)
    stream_base: str = ""
    browse_base: str = ""
    total_files: int = 0
    total_dirs: int = 0
    error: str = ""
