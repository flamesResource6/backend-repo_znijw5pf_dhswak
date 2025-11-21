from pydantic import BaseModel, Field
from typing import Optional, List

# Collections

class Product(BaseModel):
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in INR")
    thumbnail_url: Optional[str] = Field(None, description="Thumbnail image URL")
    file_url: Optional[str] = Field(None, description="Public link to digital file (for demo)")

class Order(BaseModel):
    status: str = Field(..., description="Order status e.g., paid, failed, pending")
    amount: float = Field(..., ge=0, description="Total amount")
    items: List[dict] = Field(default_factory=list, description="Cart items with product_id and quantity")
    customer_name: str = Field(...)
    customer_email: str = Field(...)
    download_links: List[dict] = Field(default_factory=list)
