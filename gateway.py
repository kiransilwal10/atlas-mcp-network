import os
import asyncio
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv

# load credentials
load_dotenv()

app = FastAPI(title="Atlas-MCP-Production-Gateway")

#global in-memory draft staging store
pending_actions = {}

#pydantic request models
class EmailDraftRequest(BaseModel):
    recipient: str
    subject: str
    body: str
    session_id: str = "default_user"

class ConfirmationRequest(BaseModel):
    session_id: str = "default_user"
    confirmation: bool
    corrected_email: Optional[str] = None

#stage email draft endpoint
@app.post("/agent/stage_email")
async def stage_email_draft(req: EmailDraftRequest):
    """
    stages an email draft instead of sending it directly
    """
    pending_actions[req.session_id] = {
    
        "action": "send_email",
        "params": {
            "recipient": req.recipient,
            "subject": req.subject,
            "body": req.body

        }
    }
    return {
        "status": "pending_confirmation",
        "message": f"I've prepared the draft to {req.recipient}. Should I send it, or would you like to correct the recipient?"
    }

#execution endpoint which is called after user confirms verbally
@app.post("/agent/confirm_action")
async def confirm_and_execute(req: ConfirmationRequest):
    """
    Executes or updates the action after user verification
    """
    draft = pending_actions.get(req.session_id)
    if not draft:
        return {"status": "error", "message": "No pending action found."}
    
    #user correctd the transcibed email verbally
    if req.corrected_email:
        draft["params"]["recipient"] = req.corrected_email
        return{
            "status": "updated",
            "message": f"Updated recipient to {req.corrected_email}. Confirm to send now?"
        }
    #user said "yes" -> execute the staged action via the MCP email server
    if req.confirmation:
        try:
            tool_output = await execute_mcp_tool(
                EMAIL_SERVER_PATH,
                draft["action"],
                draft["params"]
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Action execution failed: {str(e)}")

        #clear the staged draft now that it has been sent
        pending_actions.pop(req.session_id, None)

        return {
            "status": "sent",
            "message": f"Email sent to {draft['params']['recipient']}.",
            "tool_output": tool_output
        }

    #user declined -> discard the staged draft
    pending_actions.pop(req.session_id, None)
    return {"status": "cancelled", "message": "Okay, I've discarded the draft."}


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
            return response.content[0].text


@app.post("/agent/chat")
async def run_ai_agent_loop(request: AgentRequest):
    """
    Production Agent Loop: Handles single or multi-turn tool calling seamlessly
    by verifying and executing all tool requests made by Claude in a given turn.
    """
    try:
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

        conversation_history = [{"role": "user", "content": request.prompt}]
        tools_executed = []

        while True:
            # Query Claude using the active production string
            message = anthropic_client.messages.create(
                model="claude-sonnet-5",
                max_tokens=1024,
                tools=available_tools,
                messages=conversation_history
            )

            # Record Claude's action turn directly into history state
            conversation_history.append({"role": "assistant", "content": message.content})

            # Base Case: Break out if Claude is done processing tools
            if message.stop_reason != "tool_use":
                break

            # Gather all individual tool calls requested in this message turn
            tool_use_blocks = [block for block in message.content if block.type == "tool_use"]
            tool_results_content = []

            for tool_use in tool_use_blocks:
                tool_name = tool_use.name
                tool_args = tool_use.input

                print(f"\n[LOOP INTERCEPT] Claude executing: '{tool_name}' with parameters: {tool_args}")
                tools_executed.append(tool_name)

                # Route execution parameters contextually
                if tool_name == "log_flight":
                    tool_output = await execute_mcp_tool(FLIGHT_SERVER_PATH, tool_name, tool_args)
                elif tool_name == "send_email":
                    tool_output = await execute_mcp_tool(EMAIL_SERVER_PATH, tool_name, tool_args)
                else:
                    raise HTTPException(status_code=400, detail="Unknown tool requested by model")

                # Accumulate the response inside a tool_result block
                tool_results_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": tool_output
                })

            # Feed the complete answer block array back as a single user interaction
            conversation_history.append({
                "role": "user",
                "content": tool_results_content
            })

        # Safely capture string text fields out of final assistant payload
        final_text = ""
        for block in conversation_history[-1]["content"]:
            if hasattr(block, 'text'):
                final_text = block.text
                break

        return {
            "agent_response": final_text,
            "pipeline_steps": tools_executed
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent Loop failure: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gateway:app", host="127.0.0.1", port=8000, reload=True)