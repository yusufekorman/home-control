#!/usr/bin/env python3
"""
Home Control MCP Server

Runs as a standalone stdio MCP server.
Set environment variables:
  HOME_CONTROL_URL  - Base URL of the Home Control server (default: http://localhost:8000)
  HOME_CONTROL_KEY  - API key (X-API-Key header)

Add to Claude Desktop config:
{
  "mcpServers": {
    "home-control": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "HOME_CONTROL_URL": "http://localhost:8000",
        "HOME_CONTROL_KEY": "hck_..."
      }
    }
  }
}
"""

import asyncio
import json
import os
import sys

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

BASE_URL = os.environ.get("HOME_CONTROL_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.environ.get("HOME_CONTROL_KEY", "")

server = Server("home-control")


def api_headers() -> dict:
    return {"X-API-Key": API_KEY, "Content-Type": "application/json"}


async def api_get(path: str) -> dict | list:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE_URL}/api/v1{path}", headers=api_headers(), timeout=15)
        r.raise_for_status()
        return r.json()


async def api_post(path: str, body: dict | None = None) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{BASE_URL}/api/v1{path}",
            headers=api_headers(),
            json=body or {},
            timeout=15,
        )
        r.raise_for_status()
        if r.status_code == 204:
            return {"success": True}
        return r.json()


async def api_put(path: str, body: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{BASE_URL}/api/v1{path}", headers=api_headers(), json=body, timeout=15
        )
        r.raise_for_status()
        return r.json()


async def api_delete(path: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.delete(f"{BASE_URL}/api/v1{path}", headers=api_headers(), timeout=15)
        r.raise_for_status()
        return {"success": True}


# ─── Tool definitions ─────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_devices",
            description="List all home control devices with their details and actions.",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_device",
            description="Get detailed information about a specific device including its actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID"}
                },
                "required": ["device_id"],
            },
        ),
        types.Tool(
            name="create_device",
            description="Add a new home control device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Device name"},
                    "description": {"type": "string", "description": "Device description"},
                    "ip_address": {"type": "string", "description": "IP address of the device"},
                    "base_url": {"type": "string", "description": "Base URL e.g. http://192.168.1.10"},
                    "auth_header_name": {"type": "string", "description": "Auth header name (optional)"},
                    "auth_header_value": {"type": "string", "description": "Auth header value (optional)"},
                    "icon": {"type": "string", "description": "Icon key: light, plug, thermostat, camera, lock, device"},
                },
                "required": ["name", "ip_address", "base_url"],
            },
        ),
        types.Tool(
            name="update_device",
            description="Update an existing device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "ip_address": {"type": "string"},
                    "base_url": {"type": "string"},
                    "auth_header_name": {"type": "string"},
                    "auth_header_value": {"type": "string"},
                    "is_active": {"type": "boolean"},
                    "icon": {"type": "string"},
                },
                "required": ["device_id", "name", "ip_address", "base_url"],
            },
        ),
        types.Tool(
            name="delete_device",
            description="Delete a device and all its actions and logs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Device ID to delete"}
                },
                "required": ["device_id"],
            },
        ),
        types.Tool(
            name="list_actions",
            description="List all actions defined for a device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer"}
                },
                "required": ["device_id"],
            },
        ),
        types.Tool(
            name="create_action",
            description="Add a new trigger action to a device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer"},
                    "name": {"type": "string", "description": "Action name e.g. 'Turn On'"},
                    "description": {"type": "string"},
                    "path": {"type": "string", "description": "HTTP path e.g. /api/relay/1/on"},
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
                    "body": {"type": "string", "description": "Optional JSON request body"},
                    "extra_headers": {"type": "string", "description": "Optional JSON extra headers"},
                },
                "required": ["device_id", "name", "path"],
            },
        ),
        types.Tool(
            name="delete_action",
            description="Delete an action from a device.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer"},
                    "action_id": {"type": "integer"},
                },
                "required": ["device_id", "action_id"],
            },
        ),
        types.Tool(
            name="trigger_action",
            description="Trigger a device action (sends the HTTP request to the device).",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer"},
                    "action_id": {"type": "integer"},
                },
                "required": ["device_id", "action_id"],
            },
        ),
        types.Tool(
            name="get_logs",
            description="Get recent trigger logs for a device or all devices.",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "integer", "description": "Optional: filter by device"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        ),
    ]


# ─── Tool handler ─────────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        if name == "list_devices":
            result = await api_get("/devices")

        elif name == "get_device":
            result = await api_get(f"/devices/{arguments['device_id']}")

        elif name == "create_device":
            payload = {
                "name": arguments["name"],
                "description": arguments.get("description", ""),
                "ip_address": arguments["ip_address"],
                "base_url": arguments["base_url"],
                "auth_header_name": arguments.get("auth_header_name"),
                "auth_header_value": arguments.get("auth_header_value"),
                "is_active": True,
                "icon": arguments.get("icon", "device"),
            }
            result = await api_post("/devices", payload)

        elif name == "update_device":
            did = arguments.pop("device_id")
            result = await api_put(f"/devices/{did}", arguments)

        elif name == "delete_device":
            result = await api_delete(f"/devices/{arguments['device_id']}")

        elif name == "list_actions":
            result = await api_get(f"/devices/{arguments['device_id']}/actions")

        elif name == "create_action":
            did = arguments.pop("device_id")
            result = await api_post(f"/devices/{did}/actions", arguments)

        elif name == "delete_action":
            result = await api_delete(
                f"/devices/{arguments['device_id']}/actions/{arguments['action_id']}"
            )

        elif name == "trigger_action":
            result = await api_post(
                f"/devices/{arguments['device_id']}/actions/{arguments['action_id']}/trigger"
            )

        elif name == "get_logs":
            if "device_id" in arguments:
                result = await api_get(
                    f"/devices/{arguments['device_id']}/logs?limit={arguments.get('limit', 20)}"
                )
            else:
                result = await api_get(f"/logs?limit={arguments.get('limit', 20)}")

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    except httpx.HTTPStatusError as e:
        err = {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        return [types.TextContent(type="text", text=json.dumps(err))]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({"error": str(e)}))]


# ─── Entry point ──────────────────────────────────────────────────────────────

async def main():
    if not API_KEY:
        print(
            "WARNING: HOME_CONTROL_KEY is not set. Set it to a valid API key.",
            file=sys.stderr,
        )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
