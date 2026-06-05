"""Exercise every vm-agent tool over real MCP HTTP. Run against a loopback server."""

import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def _text(result):
    out = []
    for block in result.content:
        if block.type == "text":
            out.append(block.text)
        elif block.type == "image":
            out.append(f"<image {block.mimeType} {len(block.data)}b64>")
    return "\n".join(out)


async def main():
    token = sys.argv[1]
    url = "http://127.0.0.1:8800/mcp"
    headers = {"Authorization": f"Bearer {token}"}

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"connected; {len(tools.tools)} tools\n")

            async def call(_tool, **args):
                r = await session.call_tool(_tool, args)
                txt = _text(r)
                print(f"--- {_tool}({args}) ---\n{txt[:600]}\n")
                return txt

            # system_info
            await call("system_info")

            # exec + persistent cwd
            await call("exec", command="pwd")
            await call("exec", command="cd /tmp && echo now-in-tmp")
            await call("exec", command="pwd")  # should still be /tmp
            await call("exec", command="echo $((6*7)); false")  # exit_code 1

            # background job
            jtxt = await call("exec", command="for i in 1 2 3; do echo line$i; sleep 0.3; done", background=True)
            job_id = json.loads(jtxt)["job_id"]
            await asyncio.sleep(1.5)
            await call("job_output", job_id=job_id)
            await call("job_list")

            # files round-trip
            await call("write_file", path="/tmp/vm_agent_test.txt", content="hello from vm-agent\n")
            await call("read_file", path="/tmp/vm_agent_test.txt")
            await call("list_dir", path="/tmp")
            await call("delete_path", path="/tmp/vm_agent_test.txt")

            # clipboard round-trip
            await call("clipboard_set", text="vm-agent-clip-123")
            await call("clipboard_get")

            # processes + services
            await call("list_processes", filter="python", limit=3)
            await call("service_control", name="tailscaled", action="status")

            # screenshot (Wayland/grim)
            await call("screenshot")

    print("SELFTEST DONE")


if __name__ == "__main__":
    if "PYTHONPATH" in os.environ:
        del os.environ["PYTHONPATH"]
    asyncio.run(main())
