from agent_harness.discovery.tools.aws_sdk_patterns import resolve, ResourceRef
from agent_harness.discovery.tools.tree_sitter_py import Boto3Call


def call(service, method, name=None, line=1):
    return Boto3Call(service=service, method=method, resource_name=name,
                     file="x.py", line=line)


def test_dynamodb_put_is_write():
    ref = resolve(call("dynamodb", "put_item", "Orders"))
    assert ref == ResourceRef(kind="dynamodb_table", name="Orders", access="writes")


def test_dynamodb_get_is_read():
    ref = resolve(call("dynamodb", "get_item", "Orders"))
    assert ref.access == "reads"


def test_s3_put_object_is_write():
    ref = resolve(call("s3", "put_object", "my-bucket"))
    assert ref == ResourceRef(kind="s3_bucket", name="my-bucket", access="writes")


def test_s3_get_object_is_read():
    ref = resolve(call("s3", "get_object", "my-bucket"))
    assert ref.access == "reads"


def test_sqs_send_message_is_produces():
    ref = resolve(call("sqs", "send_message", "my-queue"))
    assert ref == ResourceRef(kind="sqs_queue", name="my-queue", access="produces")


def test_sns_publish_is_produces():
    ref = resolve(call("sns", "publish", "topic-arn"))
    assert ref == ResourceRef(kind="sns_topic", name="topic-arn", access="produces")


def test_kinesis_put_record_is_produces():
    ref = resolve(call("kinesis", "put_record", "stream-1"))
    assert ref.kind == "kinesis_stream"
    assert ref.access == "produces"


def test_secrets_manager_is_read():
    ref = resolve(call("secretsmanager", "get_secret_value", "db/password"))
    assert ref == ResourceRef(kind="secrets_manager_secret", name="db/password", access="reads")


def test_lambda_invoke_is_invokes():
    ref = resolve(call("lambda", "invoke", "other-fn"))
    assert ref == ResourceRef(kind="lambda_function", name="other-fn", access="invokes")


def test_unknown_returns_none():
    assert resolve(call("comprehend", "detect_sentiment")) is None


def test_no_resource_name_returns_ref_without_name():
    ref = resolve(call("s3", "list_buckets"))
    # list_buckets is metadata-only — we treat as read with name = None.
    assert ref is not None and ref.access == "reads" and ref.name is None
