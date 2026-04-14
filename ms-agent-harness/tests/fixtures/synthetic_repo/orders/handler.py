"""Orders Lambda — receives HTTP, writes to DynamoDB, fans out to SQS."""
import json
import boto3
from shared.util import normalize

ddb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")
table = ddb.Table("Orders")


def handler(event, context):
    body = json.loads(event["body"])
    item = normalize(body)
    table.put_item(Item=item)
    sqs.send_message(QueueUrl="payments-queue", MessageBody=json.dumps(item))
    return {"statusCode": 200, "body": json.dumps({"id": item["id"]})}
