import asyncio
import os
import sys
from pathlib import Path


def test_real_stdio_tools_and_assistant_identity(tmp_path):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    async def run():
        env={**os.environ,'PET_NEST_DATA_DIR':str(tmp_path),'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
        params=StdioServerParameters(command=sys.executable,args=['-m','cove_pet_nest','mcp'],env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                names={t.name for t in (await session.list_tools()).tools}
                assert names=={'nest_status','pet_adopt','pet_care'}
                result=await session.call_tool('pet_adopt',{'kind':'cat','name':'团团','request_id':'mcp-adopt'})
                assert result.is_error is False
                import json
                pet=json.loads(result.content[0].text)['pet']
                result=await session.call_tool('pet_care',{'action':'feed','pet_ids':[pet['id']],'request_id':'mcp-feed'})
                assert json.loads(result.content[0].text)['results'][0]['status']=='fed'
                result=await session.call_tool('nest_status',{})
                assert json.loads(result.content[0].text)['events'][0]['actor']=='assistant'
    asyncio.run(run())
