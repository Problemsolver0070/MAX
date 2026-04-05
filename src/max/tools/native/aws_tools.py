"""AWS tools — S3, EC2, Lambda, CloudWatch."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from max.tools.registry import ToolDefinition

try:
    import boto3

    HAS_BOTO3 = True
except ImportError:
    boto3 = None  # type: ignore[assignment]
    HAS_BOTO3 = False

MAX_CONTENT_SIZE = 50_000  # 50KB content cap

TOOL_DEFINITIONS = [
    ToolDefinition(
        tool_id="aws.s3_list",
        category="cloud",
        description="List S3 buckets or objects in a bucket with optional prefix.",
        permissions=["cloud.aws.s3.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "bucket": {
                    "type": "string",
                    "description": "S3 bucket name. If omitted, lists all buckets.",
                },
                "prefix": {
                    "type": "string",
                    "description": "Object key prefix filter (only with bucket).",
                    "default": "",
                },
            },
        },
    ),
    ToolDefinition(
        tool_id="aws.s3_get",
        category="cloud",
        description="Download an S3 object and return its content (50KB cap).",
        permissions=["cloud.aws.s3.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "bucket": {"type": "string", "description": "S3 bucket name"},
                "key": {"type": "string", "description": "Object key"},
            },
            "required": ["bucket", "key"],
        },
    ),
    ToolDefinition(
        tool_id="aws.s3_put",
        category="cloud",
        description="Upload content to an S3 object.",
        permissions=["cloud.aws.s3.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "bucket": {"type": "string", "description": "S3 bucket name"},
                "key": {"type": "string", "description": "Object key"},
                "content": {"type": "string", "description": "Content to upload"},
                "content_type": {
                    "type": "string",
                    "description": "MIME type of the content",
                    "default": "application/octet-stream",
                },
            },
            "required": ["bucket", "key", "content"],
        },
    ),
    ToolDefinition(
        tool_id="aws.s3_delete",
        category="cloud",
        description="Delete an S3 object.",
        permissions=["cloud.aws.s3.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "bucket": {"type": "string", "description": "S3 bucket name"},
                "key": {"type": "string", "description": "Object key"},
            },
            "required": ["bucket", "key"],
        },
    ),
    ToolDefinition(
        tool_id="aws.ec2_list",
        category="cloud",
        description="List EC2 instances with optional filters.",
        permissions=["cloud.aws.ec2.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "filters": {
                    "type": "object",
                    "description": "EC2 describe_instances Filters as {Name: Values} dict",
                },
            },
        },
    ),
    ToolDefinition(
        tool_id="aws.ec2_manage",
        category="cloud",
        description="Start, stop, or reboot EC2 instances.",
        permissions=["cloud.aws.ec2.write"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "instance_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of EC2 instance IDs",
                },
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "reboot"],
                    "description": "Action to perform",
                },
            },
            "required": ["instance_ids", "action"],
        },
    ),
    ToolDefinition(
        tool_id="aws.lambda_invoke",
        category="cloud",
        description="Invoke an AWS Lambda function.",
        permissions=["cloud.aws.lambda.invoke"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "function_name": {
                    "type": "string",
                    "description": "Lambda function name or ARN",
                },
                "payload": {
                    "type": "object",
                    "description": "JSON payload to send to the function",
                },
            },
            "required": ["function_name"],
        },
    ),
    ToolDefinition(
        tool_id="aws.cloudwatch_query",
        category="cloud",
        description="Query CloudWatch Logs with filter pattern.",
        permissions=["cloud.aws.cloudwatch.read"],
        provider_id="native",
        input_schema={
            "type": "object",
            "properties": {
                "log_group": {
                    "type": "string",
                    "description": "CloudWatch log group name",
                },
                "query": {
                    "type": "string",
                    "description": "Filter pattern for log events",
                },
                "start_time": {
                    "type": "integer",
                    "description": "Start time as epoch milliseconds",
                },
                "end_time": {
                    "type": "integer",
                    "description": "End time as epoch milliseconds",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of events to return",
                    "default": 100,
                },
            },
            "required": ["log_group"],
        },
    ),
]


def _check_boto3() -> dict[str, Any] | None:
    """Return error dict if boto3 is not installed, None otherwise."""
    if not HAS_BOTO3:
        return {"error": "boto3 is required for AWS tools. Install with: pip install boto3"}
    return None


async def _run_sync(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous function in the default executor."""
    loop = asyncio.get_running_loop()
    import functools

    call = functools.partial(fn, *args, **kwargs)
    return await loop.run_in_executor(None, call)


# ── S3 handlers ───────────────────────────────────────────────────────


async def handle_aws_s3_list(inputs: dict[str, Any]) -> dict[str, Any]:
    """List S3 buckets or objects in a bucket."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("s3")
    bucket = inputs.get("bucket")

    if not bucket:
        response = await _run_sync(client.list_buckets)
        buckets = [
            {
                "name": b["Name"],
                "creation_date": b["CreationDate"].isoformat(),
            }
            for b in response.get("Buckets", [])
        ]
        return {"buckets": buckets}

    prefix = inputs.get("prefix", "")
    kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
    response = await _run_sync(client.list_objects_v2, **kwargs)
    objects = [
        {
            "key": obj["Key"],
            "size": obj["Size"],
            "last_modified": obj["LastModified"].isoformat(),
        }
        for obj in response.get("Contents", [])
    ]
    return {"objects": objects}


async def handle_aws_s3_get(inputs: dict[str, Any]) -> dict[str, Any]:
    """Download an S3 object."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("s3")
    bucket = inputs["bucket"]
    key = inputs["key"]

    response = await _run_sync(client.get_object, Bucket=bucket, Key=key)

    def _read_body() -> bytes:
        return response["Body"].read()

    body = await _run_sync(_read_body)
    content = body.decode(errors="replace")[:MAX_CONTENT_SIZE]

    return {
        "content": content,
        "content_type": response.get("ContentType", "application/octet-stream"),
        "size": response.get("ContentLength", len(body)),
    }


async def handle_aws_s3_put(inputs: dict[str, Any]) -> dict[str, Any]:
    """Upload content to S3."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("s3")
    bucket = inputs["bucket"]
    key = inputs["key"]
    content = inputs["content"]
    content_type = inputs.get("content_type", "application/octet-stream")

    response = await _run_sync(
        client.put_object,
        Bucket=bucket,
        Key=key,
        Body=content.encode(),
        ContentType=content_type,
    )
    return {"etag": response.get("ETag", "")}


async def handle_aws_s3_delete(inputs: dict[str, Any]) -> dict[str, Any]:
    """Delete an S3 object."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("s3")
    bucket = inputs["bucket"]
    key = inputs["key"]

    await _run_sync(client.delete_object, Bucket=bucket, Key=key)
    return {"deleted": True}


# ── EC2 handlers ──────────────────────────────────────────────────────


async def handle_aws_ec2_list(inputs: dict[str, Any]) -> dict[str, Any]:
    """List EC2 instances."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("ec2")

    kwargs: dict[str, Any] = {}
    raw_filters = inputs.get("filters")
    if raw_filters:
        kwargs["Filters"] = [
            {"Name": name, "Values": values if isinstance(values, list) else [values]}
            for name, values in raw_filters.items()
        ]

    response = await _run_sync(client.describe_instances, **kwargs)

    instances = []
    for reservation in response.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            name = ""
            for tag in inst.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
                    break
            instances.append(
                {
                    "id": inst["InstanceId"],
                    "type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "public_ip": inst.get("PublicIpAddress", ""),
                    "private_ip": inst.get("PrivateIpAddress", ""),
                    "name": name,
                }
            )
    return {"instances": instances}


async def handle_aws_ec2_manage(inputs: dict[str, Any]) -> dict[str, Any]:
    """Start, stop, or reboot EC2 instances."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("ec2")
    instance_ids = inputs["instance_ids"]
    action = inputs["action"]

    if action == "start":
        await _run_sync(client.start_instances, InstanceIds=instance_ids)
    elif action == "stop":
        await _run_sync(client.stop_instances, InstanceIds=instance_ids)
    elif action == "reboot":
        await _run_sync(client.reboot_instances, InstanceIds=instance_ids)
    else:
        return {"error": f"Invalid action: {action}. Must be start, stop, or reboot."}

    return {"action": action, "instance_ids": instance_ids}


# ── Lambda handler ────────────────────────────────────────────────────


async def handle_aws_lambda_invoke(inputs: dict[str, Any]) -> dict[str, Any]:
    """Invoke an AWS Lambda function."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("lambda")
    function_name = inputs["function_name"]
    payload = inputs.get("payload")

    kwargs: dict[str, Any] = {"FunctionName": function_name}
    if payload is not None:
        kwargs["Payload"] = json.dumps(payload)

    response = await _run_sync(client.invoke, **kwargs)

    def _read_payload() -> bytes:
        return response["Payload"].read()

    response_payload = await _run_sync(_read_payload)
    decoded = response_payload.decode(errors="replace")

    # Try to parse as JSON, fall back to raw string
    try:
        parsed = json.loads(decoded)
    except (json.JSONDecodeError, ValueError):
        parsed = decoded

    return {
        "status_code": response.get("StatusCode", 200),
        "response": parsed,
    }


# ── CloudWatch handler ───────────────────────────────────────────────


async def handle_aws_cloudwatch_query(inputs: dict[str, Any]) -> dict[str, Any]:
    """Query CloudWatch Logs."""
    err = _check_boto3()
    if err:
        return err
    client = boto3.client("logs")
    log_group = inputs["log_group"]
    limit = inputs.get("limit", 100)

    kwargs: dict[str, Any] = {
        "logGroupName": log_group,
        "limit": limit,
    }

    query = inputs.get("query")
    if query:
        kwargs["filterPattern"] = query

    start_time = inputs.get("start_time")
    if start_time is not None:
        kwargs["startTime"] = start_time

    end_time = inputs.get("end_time")
    if end_time is not None:
        kwargs["endTime"] = end_time

    response = await _run_sync(client.filter_log_events, **kwargs)

    events = [
        {
            "timestamp": event.get("timestamp", 0),
            "message": event.get("message", ""),
        }
        for event in response.get("events", [])
    ]
    return {"events": events}
