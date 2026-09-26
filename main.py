from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from bot import compose, load_folder

app = FastAPI(title="Magicpin AI Bot")

BASE_DIR = Path(__file__).resolve().parent

# Load dataset when the server starts
categories = load_folder("categories")
merchants = load_folder("merchants")
customers = load_folder("customers")
triggers = load_folder("triggers")


class ComposeRequest(BaseModel):
    trigger_id: str
    merchant_id: str
    customer_id: Optional[str] = None


@app.get("/v1/healthz")
def health_check():
    return {
        "status": "ok",
        "message": "Magicpin bot is running"
    }


@app.get("/v1/metadata")
def metadata():
    return {
        "name": "Magicpin AI Bot",
        "version": "1.0",
        "description": "Merchant engagement assistant",
        "status": "development"
    }


@app.post("/v1/context")
def get_context(data: ComposeRequest):
    return {
        "trigger_id": data.trigger_id,
        "merchant_id": data.merchant_id,
        "customer_id": data.customer_id,
        "status": "context_received"
    }


@app.post("/v1/compose")
def compose_message(data: ComposeRequest):
    trigger = triggers.get(data.trigger_id)
    if not trigger:
        raise HTTPException(
            status_code=404,
            detail=f"Trigger not found: {data.trigger_id}"
        )

    merchant = merchants.get(data.merchant_id)
    if not merchant:
        raise HTTPException(
            status_code=404,
            detail=f"Merchant not found: {data.merchant_id}"
        )

    category_slug = merchant.get("category_slug")
    category = categories.get(category_slug)

    if not category:
        raise HTTPException(
            status_code=404,
            detail=f"Category not found: {category_slug}"
        )

    customer = None
    if data.customer_id:
        customer = customers.get(data.customer_id)
        if not customer:
            raise HTTPException(
                status_code=404,
                detail=f"Customer not found: {data.customer_id}"
            )

    return compose(category, merchant, trigger, customer)


@app.get("/v1/debug/dataset")
def dataset_debug():
    return {
        "categories": len(categories),
        "merchants": len(merchants),
        "customers": len(customers),
        "triggers": len(triggers),
        "trigger_ids": list(triggers.keys())[:20]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)