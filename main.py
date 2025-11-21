import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents

app = FastAPI(title="Digital Products Store API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------
# Helpers
# ----------------------
class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        try:
            return ObjectId(str(v))
        except Exception:
            raise ValueError("Invalid ObjectId")

def serialize_doc(doc: dict) -> dict:
    if not doc:
        return doc
    doc = dict(doc)
    if doc.get("_id"):
        doc["id"] = str(doc.pop("_id"))
    # convert datetimes to isoformat
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# ----------------------
# Schemas
# ----------------------
class ProductIn(BaseModel):
    title: str
    description: Optional[str] = None
    price: float = Field(..., ge=0)
    thumbnail_url: Optional[str] = None
    file_url: Optional[str] = Field(
        default=None,
        description="Public URL to the digital file (PDF/ZIP/etc.). For demo, provide a link.",
    )

class Product(ProductIn):
    id: str
    created_at: Optional[datetime] = None

class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(1, ge=1, le=50)

class OrderIn(BaseModel):
    customer_name: str
    customer_email: str
    items: List[CartItem]

class DownloadLink(BaseModel):
    product_id: str
    token: str
    expires_at: datetime

class Order(BaseModel):
    id: str
    status: str
    amount: float
    items: List[CartItem]
    customer_name: str
    customer_email: str
    download_links: List[DownloadLink]
    created_at: datetime


# ----------------------
# Routes
# ----------------------
@app.get("/")
def read_root():
    return {"message": "Digital Products Store Backend running"}


# Products
@app.get("/api/products", response_model=List[Product])
def list_products():
    docs = get_documents("product", {}, limit=None)
    products: List[Product] = []
    for d in docs:
        products.append(Product(**serialize_doc(d)))
    return products


@app.post("/api/products", response_model=Product)
def create_product(product: ProductIn):
    data = product.model_dump()
    new_id = create_document("product", data)
    created = db["product"].find_one({"_id": ObjectId(new_id)})
    return Product(**serialize_doc(created))


# Orders
@app.post("/api/orders", response_model=Order)
def create_order(payload: OrderIn):
    # Validate products and compute total
    total = 0.0
    validated_items: List[CartItem] = []
    for item in payload.items:
        prod = db["product"].find_one({"_id": PyObjectId.validate(item.product_id)})
        if not prod:
            raise HTTPException(status_code=404, detail=f"Product not found: {item.product_id}")
        price = float(prod.get("price", 0))
        total += price * item.quantity
        validated_items.append(item)

    # Simulate instant payment success for demo
    status = "paid"

    # Generate secure download tokens per product
    download_links = []
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    for item in validated_items:
        token = secrets.token_urlsafe(24)
        download_links.append({
            "product_id": item.product_id,
            "token": token,
            "expires_at": expires_at,
        })

    order_doc = {
        "status": status,
        "amount": round(total, 2),
        "items": [i.model_dump() for i in validated_items],
        "customer_name": payload.customer_name,
        "customer_email": payload.customer_email,
        "download_links": download_links,
    }

    new_id = create_document("order", order_doc)
    saved = db["order"].find_one({"_id": ObjectId(new_id)})
    return Order(id=str(saved["_id"]),
                 status=saved["status"],
                 amount=float(saved["amount"]),
                 items=[CartItem(**i) for i in saved["items"]],
                 customer_name=saved["customer_name"],
                 customer_email=saved["customer_email"],
                 download_links=[DownloadLink(
                     product_id=dl["product_id"],
                     token=dl["token"],
                     expires_at=dl["expires_at"],
                 ) for dl in saved["download_links"]],
                 created_at=saved.get("created_at", datetime.now(timezone.utc)))


@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    doc = db["order"].find_one({"_id": PyObjectId.validate(order_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Order not found")
    return Order(id=str(doc["_id"]),
                 status=doc["status"],
                 amount=float(doc["amount"]),
                 items=[CartItem(**i) for i in doc["items"]],
                 customer_name=doc["customer_name"],
                 customer_email=doc["customer_email"],
                 download_links=[DownloadLink(
                     product_id=dl["product_id"],
                     token=dl["token"],
                     expires_at=dl["expires_at"],
                 ) for dl in doc["download_links"]],
                 created_at=doc.get("created_at", datetime.now(timezone.utc)))


@app.get("/api/download/{token}")
def resolve_download(token: str):
    order = db["order"].find_one({"download_links.token": token})
    if not order:
        raise HTTPException(status_code=404, detail="Invalid token")

    # Find the specific link
    link = None
    for dl in order.get("download_links", []):
        if dl.get("token") == token:
            link = dl
            break
    if not link:
        raise HTTPException(status_code=404, detail="Download not found")

    # Check expiry
    expires_at = link.get("expires_at")
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except Exception:
            pass
    if expires_at and datetime.now(timezone.utc) > expires_at.replace(tzinfo=timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")

    # Resolve product file URL
    prod = db["product"].find_one({"_id": PyObjectId.validate(link["product_id"])})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    file_url = prod.get("file_url")
    if not file_url:
        raise HTTPException(status_code=404, detail="File not available for this product")

    return {
        "product": serialize_doc(prod),
        "file_url": file_url,
        "message": "Direct your client to this URL to download the file. In production, stream the file from secure storage.",
    }


# Demo lead capture to simulate DM/contact
class DemoLead(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    message: Optional[str] = None

@app.post("/api/demo-lead")
def demo_lead(lead: DemoLead):
    create_document("lead", lead.model_dump())
    return {"status": "ok", "message": "We will contact you in 15 minutes."}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
