"""Tests for agents/tools/ast_tools.py — regex-based AST parsing, no LLM calls."""

from agent_harness.tools.ast_tools import parse_imports, extract_functions, find_aws_dependencies


class TestParseImports:
    def test_parse_imports_python(self, sample_lambda_path):
        result = parse_imports(sample_lambda_path, "python")
        assert "boto3" in result
        assert "import json" in result
        assert "import os" in result

    def test_parse_imports_missing_file(self):
        result = parse_imports("/nonexistent/file.py", "python")
        assert "ERROR" in result


class TestExtractFunctions:
    def test_extract_functions_python(self, sample_lambda_path):
        result = extract_functions(sample_lambda_path, "python")
        for name in ["lambda_handler", "create_order", "get_order",
                      "generate_receipt", "response"]:
            assert name in result, f"Expected function '{name}' in output"

    def test_extract_functions_counts(self, sample_lambda_path):
        result = extract_functions(sample_lambda_path, "python")
        # Should find exactly 5 top-level functions
        lines = [l for l in result.strip().split("\n") if l.strip()]
        assert len(lines) == 5, f"Expected 5 functions, got {len(lines)}: {lines}"


class TestFindAwsDependencies:
    def test_find_aws_dependencies(self, sample_lambda_path):
        result = find_aws_dependencies(sample_lambda_path, "python")
        # The sample handler uses DynamoDB (resource), S3 (client), SQS (client)
        assert "Cosmos DB" in result or "dynamodb" in result.lower()
        assert "Blob Storage" in result or "s3" in result.lower()
        assert "Queue Storage" in result or "sqs" in result.lower()

    def test_find_aws_dependencies_mapping(self, sample_lambda_path):
        """Verify specific AWS -> Azure mappings appear."""
        result = find_aws_dependencies(sample_lambda_path, "python")
        assert "azure-cosmos" in result
        assert "azure-storage-blob" in result
        assert "azure-storage-queue" in result

    def test_find_aws_dependencies_no_deps(self, tmp_dir):
        clean = tmp_dir / "clean.py"
        clean.write_text("import os\nprint('no aws here')\n")
        result = find_aws_dependencies(str(clean), "python")
        assert "No AWS SDK dependencies found" in result
