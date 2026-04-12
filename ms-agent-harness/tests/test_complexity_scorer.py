"""Tests for agents/context/complexity_scorer.py — pure regex scoring, no LLM calls."""

from agent_harness.context.complexity_scorer import score_complexity, ComplexityResult


class TestScoreLow:
    def test_score_low(self, tmp_dir):
        """A simple Lambda with 1 boto3 client should score LOW (<5)."""
        code = tmp_dir / "simple.py"
        code.write_text(
            "import boto3\n"
            "s3 = boto3.client('s3')\n"
            "\n"
            "def handler(event, context):\n"
            "    return s3.get_object(Bucket='b', Key='k')\n"
        )
        result = score_complexity(str(code), "python")
        assert result.level == "LOW"
        assert result.score < 5


class TestScoreMedium:
    def test_score_medium(self, sample_lambda_path):
        """The sample handler.py has 3 AWS deps and should score MEDIUM."""
        result = score_complexity(sample_lambda_path, "python")
        assert result.level == "MEDIUM", (
            f"Expected MEDIUM, got {result.level} (score={result.score})"
        )
        assert 5 <= result.score < 15


class TestScoreHigh:
    def test_score_high(self, tmp_dir):
        """Lambda with Step Functions + many deps should score HIGH (>=15)."""
        code = tmp_dir / "complex.py"
        code.write_text(
            "import boto3\n"
            "sfn = boto3.client('stepfunctions')\n"
            "sqs = boto3.client('sqs')\n"
            "sns = boto3.client('sns')\n"
            "dynamodb = boto3.client('dynamodb')\n"
            "s3 = boto3.client('s3')\n"
            "events = boto3.client('events')\n"
            "import requests\n"
            "r = requests.get('http://other-service')\n"
            "r2 = requests.post('http://other-service/api')\n"
            "import asyncio\n"
            "# pagination handling\n"
            "while 'LastEvaluatedKey' in response:\n"
            "    pass\n"
        )
        result = score_complexity(str(code), "python")
        assert result.level == "HIGH", (
            f"Expected HIGH, got {result.level} (score={result.score})"
        )
        assert result.score >= 15


class TestScoreBreakdown:
    def test_score_breakdown(self, sample_lambda_path):
        result = score_complexity(sample_lambda_path, "python")
        assert isinstance(result.breakdown, dict)
        assert len(result.breakdown) > 0
        # Breakdown values are ints
        for key, val in result.breakdown.items():
            assert isinstance(key, str)
            assert isinstance(val, int)

    def test_result_has_details(self, sample_lambda_path):
        result = score_complexity(sample_lambda_path, "python")
        assert isinstance(result.details, list)
        assert len(result.details) > 0

    def test_unreadable_file(self):
        result = score_complexity("/nonexistent/file.py", "python")
        assert result.level == "UNKNOWN"
        assert result.score == 0
