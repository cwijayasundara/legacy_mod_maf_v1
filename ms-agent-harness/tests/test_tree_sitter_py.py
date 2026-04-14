from agent_harness.discovery.tools.tree_sitter_py import (
    parse_imports, extract_boto3_calls,
)


def test_parse_imports_simple(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "from .siblings import helper\n"
        "from ..pkg.mod import x as y\n"
    )
    imports = parse_imports(str(f))
    assert {"os", "pathlib", ".siblings", "..pkg.mod"} == {i.module for i in imports}


def test_extract_boto3_calls(tmp_path):
    f = tmp_path / "h.py"
    f.write_text(
        "import boto3\n"
        "ddb = boto3.resource('dynamodb')\n"
        "table = ddb.Table('Orders')\n"
        "table.put_item(Item={'id': '1'})\n"
        "s3 = boto3.client('s3')\n"
        "s3.get_object(Bucket='my-bucket', Key='k')\n"
    )
    calls = extract_boto3_calls(str(f))
    services = {c.service for c in calls}
    assert "dynamodb" in services
    assert "s3" in services
    methods = {c.method for c in calls}
    assert "put_item" in methods
    assert "get_object" in methods


def test_extract_boto3_resource_names(tmp_path):
    f = tmp_path / "h.py"
    f.write_text(
        "import boto3\n"
        "t = boto3.resource('dynamodb').Table('Orders')\n"
        "boto3.client('s3').put_object(Bucket='analytics-bucket', Key='k', Body='b')\n"
    )
    calls = extract_boto3_calls(str(f))
    seen = {c.resource_name for c in calls if c.resource_name}
    assert "Orders" in seen or "analytics-bucket" in seen


def test_chain_propagation_across_statements(tmp_path):
    """table = ddb.Table(...); table.put_item(...) must resolve service."""
    f = tmp_path / "h.py"
    f.write_text(
        "import boto3\n"
        "ddb = boto3.resource('dynamodb')\n"
        "orders = ddb.Table('Orders')\n"
        "orders.put_item(Item={'id': '1'})\n"
    )
    calls = extract_boto3_calls(str(f))
    put = [c for c in calls if c.method == "put_item"]
    assert put, "put_item call not captured"
    assert put[0].service == "dynamodb"


def test_malformed_source_returns_empty(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(:\n")
    assert parse_imports(str(f)) == []
    assert extract_boto3_calls(str(f)) == []
