"""Tests for AWS tools — all boto3 calls are mocked."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from max.tools.native.aws_tools import (
    TOOL_DEFINITIONS,
    handle_aws_cloudwatch_query,
    handle_aws_ec2_list,
    handle_aws_ec2_manage,
    handle_aws_lambda_invoke,
    handle_aws_s3_delete,
    handle_aws_s3_get,
    handle_aws_s3_list,
    handle_aws_s3_put,
)


@contextmanager
def mock_boto3_client(mock_client: MagicMock) -> Generator[MagicMock, None, None]:
    """Patch both boto3 module and HAS_BOTO3 flag so handlers work."""
    with (
        patch("max.tools.native.aws_tools.boto3") as mock_boto3,
        patch("max.tools.native.aws_tools.HAS_BOTO3", True),
    ):
        mock_boto3.client.return_value = mock_client
        yield mock_boto3


# ── Tool definitions ─────────────────────────────────────────────────


class TestToolDefinitions:
    def test_has_eight_definitions(self):
        assert len(TOOL_DEFINITIONS) == 8

    def test_all_category_cloud(self):
        for td in TOOL_DEFINITIONS:
            assert td.category == "cloud", f"{td.tool_id} should be 'cloud'"

    def test_all_provider_native(self):
        for td in TOOL_DEFINITIONS:
            assert td.provider_id == "native", f"{td.tool_id} should be 'native'"

    def test_tool_ids(self):
        ids = {td.tool_id for td in TOOL_DEFINITIONS}
        expected = {
            "aws.s3_list",
            "aws.s3_get",
            "aws.s3_put",
            "aws.s3_delete",
            "aws.ec2_list",
            "aws.ec2_manage",
            "aws.lambda_invoke",
            "aws.cloudwatch_query",
        }
        assert ids == expected

    def test_required_fields_present(self):
        for td in TOOL_DEFINITIONS:
            assert td.tool_id
            assert td.description
            assert td.input_schema
            assert td.input_schema["type"] == "object"


# ── Missing dependency ───────────────────────────────────────────────


class TestMissingDependency:
    @pytest.mark.asyncio
    async def test_missing_boto3_s3(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_s3_list({})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_s3_get(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_s3_get({"bucket": "b", "key": "k"})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_s3_put(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_s3_put({"bucket": "b", "key": "k", "content": "c"})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_s3_delete(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_s3_delete({"bucket": "b", "key": "k"})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_ec2(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_ec2_list({})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_ec2_manage(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_ec2_manage({"instance_ids": ["i-1"], "action": "stop"})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_lambda(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_lambda_invoke({"function_name": "fn"})
            assert "error" in result
            assert "boto3 is required" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_boto3_cloudwatch(self):
        with patch("max.tools.native.aws_tools.HAS_BOTO3", False):
            result = await handle_aws_cloudwatch_query({"log_group": "/test"})
            assert "error" in result
            assert "boto3 is required" in result["error"]


# ── S3 List ──────────────────────────────────────────────────────────


class TestS3List:
    @pytest.mark.asyncio
    async def test_list_buckets(self):
        mock_client = MagicMock()
        mock_client.list_buckets.return_value = {
            "Buckets": [
                {
                    "Name": "my-bucket",
                    "CreationDate": datetime(2024, 1, 1, tzinfo=UTC),
                },
                {
                    "Name": "other-bucket",
                    "CreationDate": datetime(2024, 6, 15, tzinfo=UTC),
                },
            ]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_list({})

        assert "buckets" in result
        assert len(result["buckets"]) == 2
        assert result["buckets"][0]["name"] == "my-bucket"
        assert result["buckets"][1]["name"] == "other-bucket"

    @pytest.mark.asyncio
    async def test_list_objects(self):
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {
                    "Key": "file1.txt",
                    "Size": 1024,
                    "LastModified": datetime(2024, 3, 1, tzinfo=UTC),
                },
                {
                    "Key": "file2.txt",
                    "Size": 2048,
                    "LastModified": datetime(2024, 3, 2, tzinfo=UTC),
                },
            ]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_list({"bucket": "my-bucket", "prefix": "files/"})

        assert "objects" in result
        assert len(result["objects"]) == 2
        assert result["objects"][0]["key"] == "file1.txt"
        assert result["objects"][0]["size"] == 1024
        mock_client.list_objects_v2.assert_called_once_with(Bucket="my-bucket", Prefix="files/")

    @pytest.mark.asyncio
    async def test_list_objects_empty_bucket(self):
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {}

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_list({"bucket": "empty-bucket"})

        assert result["objects"] == []

    @pytest.mark.asyncio
    async def test_list_objects_default_prefix(self):
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {"Contents": []}

        with mock_boto3_client(mock_client):
            await handle_aws_s3_list({"bucket": "my-bucket"})

        mock_client.list_objects_v2.assert_called_once_with(Bucket="my-bucket", Prefix="")


# ── S3 Get ───────────────────────────────────────────────────────────


class TestS3Get:
    @pytest.mark.asyncio
    async def test_get_object(self):
        mock_body = MagicMock()
        mock_body.read.return_value = b"Hello, World!"

        mock_client = MagicMock()
        mock_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "text/plain",
            "ContentLength": 13,
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_get({"bucket": "my-bucket", "key": "hello.txt"})

        assert result["content"] == "Hello, World!"
        assert result["content_type"] == "text/plain"
        assert result["size"] == 13

    @pytest.mark.asyncio
    async def test_get_object_large_content_capped(self):
        """Content exceeding 50KB should be truncated."""
        large_content = b"x" * 60_000
        mock_body = MagicMock()
        mock_body.read.return_value = large_content

        mock_client = MagicMock()
        mock_client.get_object.return_value = {
            "Body": mock_body,
            "ContentType": "text/plain",
            "ContentLength": 60_000,
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_get({"bucket": "b", "key": "big.txt"})

        assert len(result["content"]) == 50_000
        assert result["size"] == 60_000

    @pytest.mark.asyncio
    async def test_get_object_default_content_type(self):
        mock_body = MagicMock()
        mock_body.read.return_value = b"data"

        mock_client = MagicMock()
        mock_client.get_object.return_value = {
            "Body": mock_body,
            "ContentLength": 4,
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_get({"bucket": "b", "key": "k"})

        assert result["content_type"] == "application/octet-stream"


# ── S3 Put ───────────────────────────────────────────────────────────


class TestS3Put:
    @pytest.mark.asyncio
    async def test_put_object(self):
        mock_client = MagicMock()
        mock_client.put_object.return_value = {"ETag": '"abc123"'}

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_put(
                {
                    "bucket": "my-bucket",
                    "key": "test.txt",
                    "content": "hello",
                    "content_type": "text/plain",
                }
            )

        assert result["etag"] == '"abc123"'
        mock_client.put_object.assert_called_once_with(
            Bucket="my-bucket",
            Key="test.txt",
            Body=b"hello",
            ContentType="text/plain",
        )

    @pytest.mark.asyncio
    async def test_put_object_default_content_type(self):
        mock_client = MagicMock()
        mock_client.put_object.return_value = {"ETag": '"def456"'}

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_put({"bucket": "b", "key": "k", "content": "data"})

        assert result["etag"] == '"def456"'
        mock_client.put_object.assert_called_once_with(
            Bucket="b",
            Key="k",
            Body=b"data",
            ContentType="application/octet-stream",
        )


# ── S3 Delete ────────────────────────────────────────────────────────


class TestS3Delete:
    @pytest.mark.asyncio
    async def test_delete_object(self):
        mock_client = MagicMock()
        mock_client.delete_object.return_value = {}

        with mock_boto3_client(mock_client):
            result = await handle_aws_s3_delete({"bucket": "my-bucket", "key": "old.txt"})

        assert result["deleted"] is True
        mock_client.delete_object.assert_called_once_with(Bucket="my-bucket", Key="old.txt")


# ── EC2 List ─────────────────────────────────────────────────────────


class TestEC2List:
    @pytest.mark.asyncio
    async def test_list_instances(self):
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-1234567890",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "running"},
                            "PublicIpAddress": "1.2.3.4",
                            "PrivateIpAddress": "10.0.0.1",
                            "Tags": [{"Key": "Name", "Value": "web-server"}],
                        }
                    ]
                }
            ]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_list({})

        assert len(result["instances"]) == 1
        inst = result["instances"][0]
        assert inst["id"] == "i-1234567890"
        assert inst["type"] == "t3.micro"
        assert inst["state"] == "running"
        assert inst["public_ip"] == "1.2.3.4"
        assert inst["private_ip"] == "10.0.0.1"
        assert inst["name"] == "web-server"

    @pytest.mark.asyncio
    async def test_list_instances_no_tags(self):
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-abc",
                            "InstanceType": "t2.nano",
                            "State": {"Name": "stopped"},
                            "PrivateIpAddress": "10.0.0.2",
                        }
                    ]
                }
            ]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_list({})

        inst = result["instances"][0]
        assert inst["name"] == ""
        assert inst["public_ip"] == ""

    @pytest.mark.asyncio
    async def test_list_with_filters(self):
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {"Reservations": []}

        with mock_boto3_client(mock_client):
            await handle_aws_ec2_list({"filters": {"instance-state-name": ["running"]}})

        mock_client.describe_instances.assert_called_once_with(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        )

    @pytest.mark.asyncio
    async def test_list_with_scalar_filter_value(self):
        """A scalar filter value should be wrapped in a list."""
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {"Reservations": []}

        with mock_boto3_client(mock_client):
            await handle_aws_ec2_list({"filters": {"instance-type": "t3.micro"}})

        mock_client.describe_instances.assert_called_once_with(
            Filters=[{"Name": "instance-type", "Values": ["t3.micro"]}]
        )

    @pytest.mark.asyncio
    async def test_list_multiple_reservations(self):
        mock_client = MagicMock()
        mock_client.describe_instances.return_value = {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": "i-111",
                            "InstanceType": "t3.micro",
                            "State": {"Name": "running"},
                        }
                    ]
                },
                {
                    "Instances": [
                        {
                            "InstanceId": "i-222",
                            "InstanceType": "t3.small",
                            "State": {"Name": "stopped"},
                        }
                    ]
                },
            ]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_list({})

        assert len(result["instances"]) == 2
        assert result["instances"][0]["id"] == "i-111"
        assert result["instances"][1]["id"] == "i-222"


# ── EC2 Manage ───────────────────────────────────────────────────────


class TestEC2Manage:
    @pytest.mark.asyncio
    async def test_start_instances(self):
        mock_client = MagicMock()
        mock_client.start_instances.return_value = {}

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_manage({"instance_ids": ["i-123"], "action": "start"})

        assert result["action"] == "start"
        assert result["instance_ids"] == ["i-123"]
        mock_client.start_instances.assert_called_once_with(InstanceIds=["i-123"])

    @pytest.mark.asyncio
    async def test_stop_instances(self):
        mock_client = MagicMock()
        mock_client.stop_instances.return_value = {}

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_manage(
                {"instance_ids": ["i-456", "i-789"], "action": "stop"}
            )

        assert result["action"] == "stop"
        assert result["instance_ids"] == ["i-456", "i-789"]
        mock_client.stop_instances.assert_called_once_with(InstanceIds=["i-456", "i-789"])

    @pytest.mark.asyncio
    async def test_reboot_instances(self):
        mock_client = MagicMock()
        mock_client.reboot_instances.return_value = {}

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_manage({"instance_ids": ["i-abc"], "action": "reboot"})

        assert result["action"] == "reboot"
        mock_client.reboot_instances.assert_called_once_with(InstanceIds=["i-abc"])

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        mock_client = MagicMock()

        with mock_boto3_client(mock_client):
            result = await handle_aws_ec2_manage({"instance_ids": ["i-123"], "action": "terminate"})
            assert "error" in result
            assert "Invalid action" in result["error"]


# ── Lambda Invoke ────────────────────────────────────────────────────


class TestLambdaInvoke:
    @pytest.mark.asyncio
    async def test_invoke_with_payload(self):
        mock_payload = MagicMock()
        mock_payload.read.return_value = b'{"result": "ok"}'

        mock_client = MagicMock()
        mock_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": mock_payload,
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_lambda_invoke(
                {"function_name": "my-func", "payload": {"input": "data"}}
            )

        assert result["status_code"] == 200
        assert result["response"] == {"result": "ok"}
        mock_client.invoke.assert_called_once_with(
            FunctionName="my-func",
            Payload='{"input": "data"}',
        )

    @pytest.mark.asyncio
    async def test_invoke_without_payload(self):
        mock_payload = MagicMock()
        mock_payload.read.return_value = b'"done"'

        mock_client = MagicMock()
        mock_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": mock_payload,
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_lambda_invoke({"function_name": "my-func"})

        assert result["response"] == "done"
        mock_client.invoke.assert_called_once_with(FunctionName="my-func")

    @pytest.mark.asyncio
    async def test_invoke_non_json_response(self):
        mock_payload = MagicMock()
        mock_payload.read.return_value = b"plain text response"

        mock_client = MagicMock()
        mock_client.invoke.return_value = {
            "StatusCode": 200,
            "Payload": mock_payload,
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_lambda_invoke({"function_name": "fn"})

        assert result["response"] == "plain text response"
        assert result["status_code"] == 200


# ── CloudWatch Query ─────────────────────────────────────────────────


class TestCloudWatchQuery:
    @pytest.mark.asyncio
    async def test_query_basic(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {
            "events": [
                {"timestamp": 1700000000000, "message": "Log line 1"},
                {"timestamp": 1700000001000, "message": "Log line 2"},
            ]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_cloudwatch_query({"log_group": "/app/logs"})

        assert len(result["events"]) == 2
        assert result["events"][0]["message"] == "Log line 1"
        assert result["events"][1]["timestamp"] == 1700000001000
        mock_client.filter_log_events.assert_called_once_with(logGroupName="/app/logs", limit=100)

    @pytest.mark.asyncio
    async def test_query_with_filter_pattern(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {"events": []}

        with mock_boto3_client(mock_client):
            result = await handle_aws_cloudwatch_query({"log_group": "/app/logs", "query": "ERROR"})

        assert result["events"] == []
        mock_client.filter_log_events.assert_called_once_with(
            logGroupName="/app/logs", limit=100, filterPattern="ERROR"
        )

    @pytest.mark.asyncio
    async def test_query_with_time_range(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {"events": []}

        with mock_boto3_client(mock_client):
            await handle_aws_cloudwatch_query(
                {
                    "log_group": "/app/logs",
                    "start_time": 1700000000000,
                    "end_time": 1700000060000,
                    "limit": 50,
                }
            )

        mock_client.filter_log_events.assert_called_once_with(
            logGroupName="/app/logs",
            limit=50,
            startTime=1700000000000,
            endTime=1700000060000,
        )

    @pytest.mark.asyncio
    async def test_query_with_all_params(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {
            "events": [{"timestamp": 1700000000000, "message": "Found it"}]
        }

        with mock_boto3_client(mock_client):
            result = await handle_aws_cloudwatch_query(
                {
                    "log_group": "/app/logs",
                    "query": "ERROR",
                    "start_time": 1700000000000,
                    "end_time": 1700000060000,
                    "limit": 10,
                }
            )

        assert len(result["events"]) == 1
        mock_client.filter_log_events.assert_called_once_with(
            logGroupName="/app/logs",
            limit=10,
            filterPattern="ERROR",
            startTime=1700000000000,
            endTime=1700000060000,
        )

    @pytest.mark.asyncio
    async def test_query_empty_events(self):
        mock_client = MagicMock()
        mock_client.filter_log_events.return_value = {}

        with mock_boto3_client(mock_client):
            result = await handle_aws_cloudwatch_query({"log_group": "/app/logs"})

        assert result["events"] == []
