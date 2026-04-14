"""Payments Lambda — consumes SQS, reads Orders, writes Payments table, publishes SNS."""
import json
import boto3
from shared.util import normalize

ddb = boto3.resource("dynamodb")
orders = ddb.Table("Orders")
payments = ddb.Table("Payments")
sns = boto3.client("sns")


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        order = orders.get_item(Key={"id": body["id"]}).get("Item")
        result = normalize({"order_id": body["id"], "status": "paid"})
        payments.put_item(Item=result)
        sns.publish(TopicArn="payment-events", Message=json.dumps(result))
    return {"statusCode": 200}
