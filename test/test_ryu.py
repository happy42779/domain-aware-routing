import asyncio

sock_path = "/tmp/ryu.sock"


async def start_client(commands):
    reader, writer = await asyncio.open_unix_connection(sock_path)
    print("Connected to the unix socket")
    writer.write(b"Hello from client")
    await writer.drain()


async def main():
    # comamdns
    commands = [{"command": "block", "ips": []}]
    asyncio.gather
