import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

# 1. SETUP & CONFIGURATION
load_dotenv()

app = FastAPI(title="Atlas-MCP-Production-Gateway")
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Paths for local servers
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, ".venv", "bin", "python3")
EMAIL_SERVER_PATH = os.path.join(BASE_DIR, "email_server.py")
FLIGHT_SERVER_PATH = os.path.join(BASE_DIR, "flight_server.py")

# Global staging dictionary for Human-in-the-Loop confirmations
pending_actions = {}


# 2. SCHEMAS (Request models)
class AgentRequest(BaseModel):
    prompt: str

class EmailDraftRequest(BaseModel):
    recipient: str
    subject: str
    body: str
    session_id: str = "default_user"

class ConfirmationRequest(BaseModel):
    session_id: str = "default_user"
    confirmation: bool
    corrected_email: Optional[str] = None


# 3. MCP HELPER (Runs background tools)
async def execute_mcp_tool(server_path: str, tool_name: str, arguments: dict) -> str:
    """Launches an MCP tool server via stdio, runs the tool, and returns the output."""
    server_params = StdioServerParameters(command=VENV_PYTHON, args=[server_path])

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            response = await session.call_tool(tool_name, arguments=arguments)
            return response.content[0].text


# 4. ENDPOINTS

@app.post("/agent/chat")
async def run_ai_agent_loop(request: AgentRequest):
    """Main endpoint: Takes user prompt, sends it to Claude, and routes tool requests."""
    try:
        available_tools = [
            {
                "name": "log_flight",
                "description": "Logs a flight into the SQL database.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "flight_number": {"type": "string"},
                        "departure": {"type": "string"},
                        "arrival": {"type": "string"},
                        "date": {"type": "string"}
                    },
                    "required": ["flight_number", "departure", "arrival", "date"]
                }
            },
            {
                "name": "send_email",
                "description": "Prepares and stages an email for confirmation.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "recipient": {"type": "string"},
                        "subject": {"type": "string"},
                        "body": {"type": "string"}
                    },
                    "required": ["recipient", "subject", "body"]
                }
            },
            {
                "name": "confirm_staged_action",
                "description": "Executes or cancels a staged draft action based on user confirmation.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "confirmation": {"type": "boolean", "description": "True if user confirmed 'yes', False if 'no'"},
                        "corrected_email": {"type": "string", "description": "Updated email address if user corrected it verbally"}
                    },
                    "required": ["confirmation"]
                }
            }
        ]

        conversation_history = [{"role": "user", "content": request.prompt}]
        tools_executed = []

        while True:
            message = anthropic_client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1024,
                system=" You are a voice assistant. ALWAYS provide a concise verbal response alongside any tool calls." \
                "When staging an email, state that you staged the draft and ask the user for confirmation.",
                tools=available_tools,
                messages=conversation_history
            )

            conversation_history.append({"role": "assistant", "content": message.content})

            # If Claude doesn't need to run tools, exit the loop
            if message.stop_reason != "tool_use":
                break

            tool_use_blocks = [block for block in message.content if block.type == "tool_use"]
            tool_results_content = []

            for tool_use in tool_use_blocks:
                tool_name = tool_use.name
                tool_args = tool_use.input
                tools_executed.append(tool_name)

                # Flight tool runs immediately
                if tool_name == "log_flight":
                    tool_output = await execute_mcp_tool(FLIGHT_SERVER_PATH, tool_name, tool_args)

                # Email tool STAGES a draft for confirmation
                elif tool_name == "send_email":
                    pending_actions["default_user"] = {
                        "action": "send_email",
                        "params": tool_args
                    }
                    tool_output = (
                        f"DRAFT STAGED for {tool_args.get('recipient')}. "
                        "Ask the user for verbal confirmation before sending."
                    )
                
                elif tool_name == "confirm_staged_action":
                    #execute the draft from pending actions
                    draft = pending_actions.get("default_user")
                    if draft and tool_args.get("confirmation"):
                        tool_output = await execute_mcp_tool(
                            EMAIL_SERVER_PATH,
                            draft["action"],
                            draft["params"]
                        )
                        pending_actions.pop("default_user", None)
                    else:
                        pending_actions.pop("default_user", None)
                        tool_output = "Draft discarded as required"
                else:
                    raise HTTPException(status_code=400, detail="Unknown tool")

                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": tool_output
                })

            conversation_history.append({"role": "user", "content": tool_results_content})

        # Extract final text answer
        final_text = ""
        for block in conversation_history[-1]["content"]:
            if hasattr(block, 'text'):
                final_text = block.text
                break

        return {"agent_response": final_text, "pipeline_steps": tools_executed}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Loop failure: {str(e)}")


@app.post("/agent/confirm_action")
async def confirm_and_execute(req: ConfirmationRequest):
    """Executes or cancels the staged email after human confirmation."""
    draft = pending_actions.get(req.session_id)
    if not draft:
        return {"status": "error", "message": "No pending draft found."}

    # User corrected the email recipient verbally
    if req.corrected_email:
        draft["params"]["recipient"] = req.corrected_email
        return {"status": "updated", "message": f"Updated email recipient to {req.corrected_email}."}

    # User confirmed "Yes"
    if req.confirmation:
        try:
            tool_output = await execute_mcp_tool(
                EMAIL_SERVER_PATH,
                draft["action"],
                draft["params"]
            )
            pending_actions.pop(req.session_id, None)
            return {"status": "sent", "message": f"Email successfully sent!", "tool_output": tool_output}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Action execution failed: {str(e)}")

    # User said "No"
    pending_actions.pop(req.session_id, None)
    return {"status": "cancelled", "message": "Draft discarded."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gateway:app", host="127.0.0.1", port=8000, reload=True)