import os
import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

#load credentials
load_dotenv()

app = FastAPI(title="Atlas-MCP-Production-Gateway")

anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "bin", "python3")

EMAIL_SERVER_PATH = os.path.join(BASE_DIR, "email_server.py")
FLIGHT_SERVER_PATH = os.path.join(BASE_DIR, "flight_server.py")

class AgentRequest(BaseModel):
    prompt: str

async def execute_mcp_tool(server_path: str, tool_name: str, arguments: dict) -> str:
    """
    Subprocess Manager: Launches a local microservice via stdio transport,
    executes the requested tool, returns the payload, and cleanly tears down the process.
    """
    server_params = StdioServerParameters(command=VENV_PYTHON, args=[server_path])

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.call_tool(tool_name, arguments=arguments)
            # Retrieve the raw text result from the MCP JSON-RPC response envelope
            return response.content[0].text

@app.post("/agent/chat")
async def run_ai_agent_loop(request: AgentRequest):
    """
    Core AI Loop: Takes your conversational request, shares your custom tool blueprints 
    with Claude, intercepts any tool calls, runs them locally, and returns the final response.
    """
    try:
        # Define our available tools so Claude knows how to interact with our systems
        available_tools = [
            {
                "name": "log_flight",
                "description": "Logs a real flight itinerary into the local relational SQL database. Use this when the user mentions registering, tracking, or booking a flight.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "flight_number": {"type": "string", "description": "The airline and flight code (e.g., UA182)"},
                        "departure": {"type": "string", "description": "The 3-letter airport code of departure (e.g., SFO)"},
                        "arrival": {"type": "string", "description": "The 3-letter airport code of arrival (e.g., JFK)"},
                        "date": {"type": "string", "description": "The travel date formatted as YYYY-MM-DD"}
                    },
                    "required": ["flight_number", "departure", "arrival", "date"]
                }
            },
            {
                "name": "send_email",
                "description": "Sends a real email to a recipient using secure production-grade SMTP routing. Use this when the user explicitly requests sending an alert, confirmation, or check-in message.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "recipient": {"type": "string", "description": "The receiver's email address"},
                        "subject": {"type": "string", "description": "A concise subject line"},
                        "body": {"type": "string", "description": "The main text body of the email"}
                    },
                    "required": ["recipient", "subject", "body"]
                }
            }
        ]
        #first turn: send your natural language prompt and our tool blueprints to claude
        
        message = anthropic_client.messages.create(
            model = "claude-3-5-sonnet-20241022",
            max_tokens = 1024,
            tools = available_tools,
            messages=[{"role": "user", "content": request.prompt}]
        )

        #check if claude decided that answering this request requires running a tool
        if message.stop_reason == "tool_use":
            ## Extract the specific tool call request block from Claude's response
            tool_use_block = [block for block in message.content if block.type == "tool_use"][0]
            tool_name = tool_use_block.name
            tool_args = tool_use_block.input

            print(f"\n[GATEWAY INTERCEPT] Claude decided to run: '{tool_name}' with parameters: {tool_args}\n")

            # Execute the correct local subprocess based on Claude's decision
            if tool_name == "log_flight":
                tool_output = await execute_mcp_tool(FLIGHT_SERVER_PATH, tool_name, tool_args)
            elif tool_name == "send_email":
                tool_output = await execute_mcp_tool(EMAIL_SERVER_PATH, tool_name, tool_args)
            else:
                raise HTTPException(status_code= 400, detail="Unknown tool requested by model")
            
            #second turn; Feed the tool execution output back to Claude so it can formulate its final reply
            final_response = anthropic_client.messages.create(
                model = "claude-3-5-sonnet-20241022",
                max_tokens = 1024,
                tools = available_tools,
                messages = [
                    {"role": "user", "content": request.prompt},
                    {"role": "assistant", "content": message.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_block.id,
                                "content": tool_output
                            }
                        ]
                    }

                ]
            )
            return {"agent_response": final_response.content[0].text, "tool_executed": tool_name}
        #if claude didnt need any tools
        return {"agent_response": message.content[0].text, "tool_executed": "none"}
    
    except Exception as e:
        raise HTTPException(status_code = 500, detail=f"Agent Pipeline Crash: {str(e)}")
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gateway:app", host = "127.0.0.1", port =8000, reload = True)


