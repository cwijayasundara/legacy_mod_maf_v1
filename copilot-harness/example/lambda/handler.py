"""
Sample AWS Lambda: Order Processor (Python)
Receives an order via API Gateway, validates it, stores in DynamoDB,
uploads receipt to S3, and publishes event to SQS.

This is a representative multi-dependency Lambda for testing the migration pipeline.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3

# AWS clients (initialized outside handler for connection reuse)
dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
sqs = boto3.client("sqs")

ORDERS_TABLE = os.environ.get("ORDERS_TABLE", "orders")
RECEIPTS_BUCKET = os.environ.get("RECEIPTS_BUCKET", "order-receipts")
NOTIFICATIONS_QUEUE = os.environ.get("NOTIFICATIONS_QUEUE_URL", "")


def lambda_handler(event, context):
    """
    API Gateway proxy integration handler.
    POST /orders — create a new order
    GET /orders/{id} — retrieve an order
    """
    http_method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if http_method == "POST":
        return create_order(event)
    elif http_method == "GET" and "id" in path_params:
        return get_order(path_params["id"])
    else:
        return response(404, {"error": "Not found"})


def create_order(event):
    """Validate, persist, generate receipt, and notify."""
    try:
        body = json.loads(event.get("body", "{}"))
    except json.JSONDecodeError:
        return response(400, {"error": "Invalid JSON"})

    # Validate required fields
    required = ["customer_id", "items", "total"]
    missing = [f for f in required if f not in body]
    if missing:
        return response(400, {"error": f"Missing fields: {', '.join(missing)}"})

    if not isinstance(body["items"], list) or len(body["items"]) == 0:
        return response(400, {"error": "Items must be a non-empty list"})

    if not isinstance(body["total"], (int, float)) or body["total"] <= 0:
        return response(400, {"error": "Total must be a positive number"})

    # Create order record
    order_id = str(uuid.uuid4())
    order = {
        "id": order_id,
        "customer_id": body["customer_id"],
        "items": body["items"],
        "total": str(body["total"]),  # DynamoDB needs string for decimals
        "status": "confirmed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # Store in DynamoDB
    table = dynamodb.Table(ORDERS_TABLE)
    table.put_item(Item=order)

    # Generate and upload receipt to S3
    receipt = generate_receipt(order)
    s3.put_object(
        Bucket=RECEIPTS_BUCKET,
        Key=f"receipts/{order_id}.json",
        Body=json.dumps(receipt),
        ContentType="application/json",
    )

    # Publish notification to SQS
    if NOTIFICATIONS_QUEUE:
        sqs.send_message(
            QueueUrl=NOTIFICATIONS_QUEUE,
            MessageBody=json.dumps({
                "event": "order.created",
                "order_id": order_id,
                "customer_id": body["customer_id"],
                "total": body["total"],
            }),
        )

    return response(201, {"order_id": order_id, "status": "confirmed"})


def get_order(order_id):
    """Retrieve an order by ID from DynamoDB."""
    table = dynamodb.Table(ORDERS_TABLE)
    result = table.get_item(Key={"id": order_id})
    item = result.get("Item")

    if not item:
        return response(404, {"error": f"Order {order_id} not found"})

    return response(200, item)


def generate_receipt(order):
    """Generate a simple receipt document."""
    return {
        "receipt_id": f"RCP-{order['id'][:8]}",
        "order_id": order["id"],
        "customer_id": order["customer_id"],
        "items": order["items"],
        "total": order["total"],
        "date": order["created_at"],
        "message": "Thank you for your order!",
    }


def response(status_code, body):
    """Standard API Gateway proxy response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),
    }
