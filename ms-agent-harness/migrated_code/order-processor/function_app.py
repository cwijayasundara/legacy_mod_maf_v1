import logging
import json
from azure.functions import HttpRequest, HttpResponse, FunctionContext
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient
from azure.storage.queue import QueueClient

# Initialize Azure clients
cosmos_client = CosmosClient('COSMOS_DB_CONNECTION_STRING')
blob_service_client = BlobServiceClient.from_connection_string('BLOB_STORAGE_CONNECTION_STRING')
queue_client = QueueClient.from_connection_string('QUEUE_STORAGE_CONNECTION_STRING', 'queue_name')

@app.route("/orders", methods=["POST"])
async def create_order(req: HttpRequest, context: FunctionContext) -> HttpResponse:
    logging.info('Creating order...')
    try:
        order_data = req.get_json()
        if not order_data:
            return HttpResponse(status_code=400)
        # Simulate order creation in Cosmos DB
        # upload receipt to Blob Storage if needed
        # send notification to Queue Storage if needed
        return HttpResponse(json.dumps({"status": "success", "data": order_data}), status_code=201)
    except Exception as e:
        logging.error(f'Error creating order: {e}')
        return HttpResponse(json.dumps({"status": "error", "message": str(e)}), status_code=500)

@app.route("/orders/{id}", methods=["GET"])
async def get_order(req: HttpRequest, id: str, context: FunctionContext) -> HttpResponse:
    logging.info(f'Getting order {id}...')
    try:
        # Simulate getting order from Cosmos DB
        order_data = {}  # Replace with actual fetching logic
        return HttpResponse(json.dumps({"status": "success", "data": order_data}), status_code=200)
    except Exception as e:
        logging.error(f'Error getting order: {e}')
        return HttpResponse(json.dumps({"status": "error", "message": 'Order not found'}), status_code=404)