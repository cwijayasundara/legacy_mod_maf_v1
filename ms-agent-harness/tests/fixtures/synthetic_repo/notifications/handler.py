"""Notifications Lambda — consumes SNS, reads Secrets Manager, posts to webhook."""
import json
import boto3

sm = boto3.client("secretsmanager")


def handler(event, context):
    secret = sm.get_secret_value(SecretId="webhook/url")
    for record in event["Records"]:
        msg = record["Sns"]["Message"]
        print(f"notify {secret['SecretString']}: {msg}")
    return {"statusCode": 200}
