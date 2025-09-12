from pydantic import BaseModel, HttpUrl, EmailStr
from typing import Optional

class OrganizationOut(BaseModel):
    organization_id: int
    name: str
    description: Optional[str] = None
    website: Optional[HttpUrl] = None
    contact_email: Optional[EmailStr] = None
    created_at: str

class ProjectOut(BaseModel):
    project_id: int
    name: str
    description: Optional[str] = None
    created_at: str
    organization_id: int
