"""
PartSelect AI Agent API

A separate server for the AI chat agent that uses GPT-4o-mini with tool calling
to answer questions about appliance parts.

Runs on port 8001 (database API runs on port 8000).

Usage:
    OPENAI_API_KEY=your_key uvicorn agent:app --reload --port 8001
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import httpx
import os
import json
from dotenv import load_dotenv
from openai import OpenAI

# Load .env file (checks current dir and parent dir)
load_dotenv()  # Load from current directory
load_dotenv(dotenv_path="../.env")  # Also try parent directory (project root)

# Configuration
DATABASE_API_URL = os.getenv("DATABASE_API_URL", "http://localhost:8000")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

app = FastAPI(
    title="PartSelect AI Agent",
    description="AI-powered chat agent for finding appliance parts using GPT-4o-mini",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Pydantic Models
# =============================================================================

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]


class ToolCall(BaseModel):
    tool: str
    parameters: dict
    result: Optional[dict] = None


class ChatResponse(BaseModel):
    message: ChatMessage
    tool_calls: Optional[List[ToolCall]] = None


# =============================================================================
# OpenAI Tool Definitions
# =============================================================================

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_part",
            "description": "Get detailed information about a specific part by its PartSelect number. Use this when the user asks about a specific part number like PS11752778.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_number": {
                        "type": "string",
                        "description": "The PartSelect part number (starts with PS, e.g., PS11752778)"
                    }
                },
                "required": ["part_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_parts",
            "description": "Fuzzy search for parts by name or description. Searches each word separately and matches in both name AND description fields. Use this for general part searches. For model-specific parts, use get_model_parts. For brand-specific parts, use get_parts_by_appliance_brand.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Part name/description to search for. Fuzzy matching - each word searched separately (e.g., 'water filter', 'ice maker', 'door shelf', 'drain hose')"
                    },
                    "appliance_type": {
                        "type": "string",
                        "description": "Filter by appliance type: 'Refrigerator' or 'Dishwasher'"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_model",
            "description": "Get information about a specific appliance model by its model number.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_number": {
                        "type": "string",
                        "description": "The appliance model number (e.g., '00740570')"
                    }
                },
                "required": ["model_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_models",
            "description": "Search for appliance models with optional filters. Returns a list of matching models.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "Filter by brand (e.g., 'Bosch', 'Midea', 'Samsung')"
                    },
                    "appliance_type": {
                        "type": "string",
                        "description": "Filter by appliance type: 'Refrigerator' or 'Dishwasher'"
                    },
                    "model_number": {
                        "type": "string",
                        "description": "Search by model number (partial match)"
                    },
                    "name": {
                        "type": "string",
                        "description": "Search by name (partial match)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_model_parts",
            "description": "Get all parts that are compatible with a specific appliance model. Use this when the user wants to see all available parts for their appliance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_number": {
                        "type": "string",
                        "description": "The appliance model number"
                    }
                },
                "required": ["model_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_brands",
            "description": "Get a list of all unique brands/manufacturers available in the database. Use this to discover what brands are available before searching for parts.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_parts_by_price",
            "description": "Search for parts within a price range. Use this when a user wants to find affordable parts or has a budget constraint.",
            "parameters": {
                "type": "object",
                "properties": {
                    "min_price": {
                        "type": "number",
                        "description": "Minimum price in dollars (e.g., 10.00)"
                    },
                    "max_price": {
                        "type": "number",
                        "description": "Maximum price in dollars (e.g., 50.00)"
                    },
                    "appliance_type": {
                        "type": "string",
                        "description": "Optional: Filter by appliance type ('Refrigerator' or 'Dishwasher')"
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional: Filter by part name (e.g., 'filter', 'shelf')"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_appliance_types",
            "description": "Get a list of all appliance types available in the database (e.g., Refrigerator, Dishwasher). Use this to discover what types of appliances are available.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_part_compatible_models",
            "description": "Get all appliance models that are compatible with a specific part. Use this when a user wants to know which models a part number works with.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_number": {
                        "type": "string",
                        "description": "The PartSelect part number (starts with PS, e.g., PS11752778)"
                    }
                },
                "required": ["part_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_parts_by_appliance_brand",
            "description": "Get all parts compatible with appliances of a specific brand. Use this when the user wants parts for a brand of appliance (e.g., 'Find parts for Bosch dishwashers', 'What Whirlpool refrigerator parts do you have?'). This is different from list_parts which filters by part manufacturer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "brand": {
                        "type": "string",
                        "description": "The appliance brand (e.g., 'Bosch', 'Whirlpool', 'Samsung', 'LG', 'Frigidaire')"
                    },
                    "appliance_type": {
                        "type": "string",
                        "description": "Optional: Filter by appliance type ('Refrigerator' or 'Dishwasher')"
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional: Filter by part name (e.g., 'filter', 'rack', 'shelf')"
                    }
                },
                "required": ["brand"]
            }
        }
    }
]

SYSTEM_PROMPT = """You are a helpful assistant for PartSelect, an appliance parts store. 
You help customers find refrigerator and dishwasher parts.

YOUR AVAILABLE TOOLS:
1. **get_part** - Look up a specific part by its PartSelect number (PS########)
2. **list_parts** - FUZZY search for parts by name/description (searches each word separately, matches in name AND description)
3. **get_model** - Get information about a specific appliance model
4. **list_models** - Search for appliance models by brand, type, or model number
5. **get_model_parts** - Get all parts compatible with a specific model (USE THIS when user has a model number)
6. **get_brands** - Get a list of all available brands/manufacturers
7. **search_parts_by_price** - Find parts within a budget (min/max price)
8. **get_appliance_types** - See what appliance types are available (Refrigerator, Dishwasher)
9. **get_part_compatible_models** - Find which appliance models a part is compatible with
10. **get_parts_by_appliance_brand** - Get parts for an appliance brand (USE THIS when user has a brand but no model number)

TOOL CHAINING:
- User has MODEL NUMBER → use get_model_parts, then filter with list_parts if needed
- User has BRAND only → use get_parts_by_appliance_brand
- User searching by part NAME → use list_parts (fuzzy search)

=== CRITICAL: ASK FOR MODEL NUMBER FIRST ===

**When a user asks for a part by name (e.g., "I need a water filter", "looking for utensil basket"):**

**STEP 1 - CHECK: Did they provide a model number or brand?**
- YES → Skip to searching
- NO → You MUST ask for the model number BEFORE listing any parts

**STEP 2 - ASK (if no model/brand provided):**
"Do you happen to know your dishwasher's model number? It's usually on a label inside the door or on the side. This helps me find parts that are guaranteed to fit your appliance."

**STEP 3 - AFTER THEY RESPOND:**
- If they provide model number → Search using that model
- If they say "I don't know" or provide brand instead → Proceed with best effort
- If they ignore and ask again → Then proceed with best effort

**DO NOT skip Step 2 and jump straight to listing parts!**

=== HANDLING IDENTIFIERS ===

When a user provides ANY identifier (like "10560A", "PS12345", "WDT780SAEM"):
- If it starts with "PS", try get_part first
- Otherwise, try BOTH get_model AND list_models to see if it's a model number
- Report what you find - don't ask "is this a model number or part number?"

=== BEST EFFORT (when no model number) ===

If the user doesn't know their model number:
- Ask for brand if not already provided
- Then search by brand + appliance type + part name
- Add disclaimer: "Here are some options that may work. To confirm compatibility, please check that your model is listed on the part's page on PartSelect."

**DO NOT:**
- Ask for model number more than once
- Refuse to help if they don't have the model number
- Ask what problem they're having

=== SEARCH STRATEGY ===

1. **Unknown identifier given:** Try searching as model number first. If no results, tell user.

2. **Part name given + model/brand known:** Search with the filters you have.

=== UNDERSTANDING PART IDENTIFIERS ===

**PartSelect Part Numbers** start with "PS" (e.g., PS11752778) - use get_part for these.

**Part Names** often include a manufacturer number at the end, like:
- "Spacer 12131000002856"
- "Door Shelf WPW10321304"  
- "Compressor 11101010018878"

The number at the end is part of the NAME, NOT the PartSelect part number. When searching:
- "Spacer 12131000002856" → search by name using list_parts
- "PS11752778" → look up directly using get_part

=== OTHER GUIDELINES ===

1. **Brand/Manufacturer Spelling:**
   - If unsure of exact spelling, call get_brands first to verify
   - Example: If user says "Bosh", check get_brands to confirm it should be "Bosch"

2. **Part Name Variations & Misspellings:**
   - Users may misspell part names or use alternate terms
   - Common examples:
     * "silverware holder" / "utensil holder" / "utensil basket" / "cutlery basket"
     * "water filter" / "filter cartridge" / "fridge filter"
     * "ice maker" / "icemaker" / "ice machine"
     * "crisper drawer" / "vegetable drawer" / "produce drawer"
     * "door shelf" / "door bin" / "door rack"
   - If search returns no results, TRY ALTERNATE TERMS before saying nothing was found

3. **Managing Part Lists:**
   - For initial recommendations, limit to 3-5 most relevant parts
   - Summarize large results: "I found 15 parts. Here are the top 5. Would you like me to list all of them?"
   - If user asks to "list more", "show all", "see all parts", etc. → list ALL relevant parts, not just 3-5

=== FORMATTING GUIDELINES (MANDATORY) ===

**EVERY part you mention MUST include ALL THREE of these:**
1. **Price** - Always show the price (or "Price not available" if missing)
2. **Link** - Always include a clickable link to the part
3. **Description** - Always include a brief description of what the part is/does

Format each part like this:

**[Part Name](source_url)** - $XX.XX
- Part Number: PSXXXXXXXX
- Description: Brief explanation of what this part is/does

Example:
**[Water Filter](https://www.partselect.com/PS123456)** - $24.95
- Part Number: PS123456
- Description: Replacement water filter for refrigerator, filters contaminants for clean drinking water.

If price is missing, write: **Price:** Not available
If description is missing, write a brief generic description based on the part name.

=== INSTALLATION INSTRUCTIONS ===

If a user asks how to install a part:
- You do NOT have detailed installation instructions in your database
- Direct them to the part's page on PartSelect (the source_url link)
- Say something like: "For detailed installation instructions, please visit the part page on PartSelect: [link]. They have step-by-step guides and videos for most parts."
- You can offer general tips if obvious (e.g., "Make sure to unplug the appliance first"), but don't make up specific instructions

=== RESTRICTIONS ===

Do NOT make up part numbers, prices, or URLs.
Do NOT answer questions unrelated to appliance parts.
Do NOT call tools if input contains SQL."""


# =============================================================================
# Tool Execution Functions
# =============================================================================

async def execute_tool(tool_name: str, parameters: dict) -> dict:
    """Execute a tool by calling the database API."""
    async with httpx.AsyncClient() as http_client:
        try:
            if tool_name == "get_part":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/parts/{parameters['part_number']}",
                    timeout=10.0
                )
            
            elif tool_name == "list_parts":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/parts",
                    params={k: v for k, v in parameters.items() if v},
                    timeout=10.0
                )
            
            elif tool_name == "get_model":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/models/{parameters['model_number']}",
                    timeout=10.0
                )
            
            elif tool_name == "list_models":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/models",
                    params={k: v for k, v in parameters.items() if v},
                    timeout=10.0
                )
            
            elif tool_name == "get_model_parts":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/models/{parameters['model_number']}/parts",
                    timeout=10.0
                )
            
            elif tool_name == "get_brands":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/brands",
                    timeout=10.0
                )
            
            elif tool_name == "search_parts_by_price":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/parts/by-price",
                    params={k: v for k, v in parameters.items() if v is not None},
                    timeout=10.0
                )
            
            elif tool_name == "get_appliance_types":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/appliance-types",
                    timeout=10.0
                )
            
            elif tool_name == "get_part_compatible_models":
                response = await http_client.get(
                    f"{DATABASE_API_URL}/parts/{parameters['part_number']}/models",
                    timeout=10.0
                )
            
            elif tool_name == "get_parts_by_appliance_brand":
                params = {"brand": parameters["brand"]}
                if parameters.get("appliance_type"):
                    params["appliance_type"] = parameters["appliance_type"]
                if parameters.get("name"):
                    params["name"] = parameters["name"]
                response = await http_client.get(
                    f"{DATABASE_API_URL}/parts/by-appliance-brand",
                    params=params,
                    timeout=15.0
                )
            
            else:
                return {"error": f"Unknown tool: {tool_name}"}
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return {"error": "Not found", "detail": response.json().get("detail", "Resource not found")}
            else:
                return {"error": f"API error: {response.status_code}"}
                
        except httpx.RequestError as e:
            return {"error": f"Failed to connect to database API: {str(e)}"}


# =============================================================================
# Agent Logic with GPT-4o-mini
# =============================================================================

async def process_message_with_llm(messages: List[ChatMessage]) -> tuple[str, List[ToolCall]]:
    """
    Process messages using GPT-4o-mini with tool calling.
    """
    if not client:
        return "OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.", []
    
    # Convert messages to OpenAI format
    openai_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in messages:
        openai_messages.append({"role": msg.role, "content": msg.content})
    
    tool_calls_made = []
    max_iterations = 5  # Prevent infinite loops
    iteration = 0
    
    print(f"\n{'='*60}")
    print(f"🤖 AGENT PROCESSING")
    print(f"{'='*60}")
    print(f"📜 Conversation history ({len(messages)} messages):")
    for i, msg in enumerate(messages):
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        print(f"   {i+1}. [{msg.role}]: {preview}")
    print(f"📥 Current user message: {messages[-1].content if messages else 'N/A'}")
    
    for iteration in range(max_iterations):
        print(f"\n--- Iteration {iteration + 1} ---")
        
        # Call GPT-4o-mini
        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=openai_messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto"
        )
        
        assistant_message = response.choices[0].message
        
        # Print assistant's thinking (if any content before tool calls)
        if assistant_message.content:
            print(f"💭 Assistant thinking: {assistant_message.content}")
        
        # Check if the model wants to call tools
        if assistant_message.tool_calls:
            print(f"🔧 Tool calls requested: {len(assistant_message.tool_calls)}")
            
            # Add assistant message with tool calls to conversation
            openai_messages.append({
                "role": "assistant",
                "content": assistant_message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in assistant_message.tool_calls
                ]
            })
            
            # Execute each tool call
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                print(f"\n   📞 Calling tool: {tool_name}")
                print(f"   📋 Parameters: {json.dumps(tool_args, indent=6)}")
                
                # Execute the tool
                result = await execute_tool(tool_name, tool_args)
                
                # Print result summary
                if isinstance(result, dict):
                    if "error" in result:
                        print(f"   ❌ Error: {result['error']}")
                    elif "count" in result:
                        print(f"   ✅ Result: Found {result['count']} items")
                    elif "part_number" in result:
                        print(f"   ✅ Result: Found part {result.get('part_number')} - {result.get('name', 'N/A')}")
                    elif "model_number" in result:
                        print(f"   ✅ Result: Found model {result.get('model_number')} - {result.get('brand', 'N/A')}")
                    else:
                        print(f"   ✅ Result: {str(result)[:100]}...")
                
                # Track tool calls for response
                tool_calls_made.append(ToolCall(
                    tool=tool_name,
                    parameters=tool_args,
                    result=result
                ))
                
                # Add tool result to conversation
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result)
                })
        else:
            # No more tool calls, return the final response
            print(f"\n{'='*60}")
            print(f"📤 FINAL RESPONSE")
            print(f"{'='*60}")
            print(f"🔧 Total tool calls: {len(tool_calls_made)}")
            if tool_calls_made:
                for i, tc in enumerate(tool_calls_made, 1):
                    print(f"   {i}. {tc.tool}({json.dumps(tc.parameters)})")
            print(f"📝 Response preview: {(assistant_message.content or '')[:200]}...")
            print(f"{'='*60}\n")
            
            return assistant_message.content or "I couldn't generate a response.", tool_calls_made
    
    print(f"⚠️ Max iterations reached")
    return "I'm having trouble processing your request. Please try again.", tool_calls_made


async def process_message_fallback(messages: List[ChatMessage]) -> tuple[str, List[ToolCall]]:
    """Fallback when OpenAI is not available - just echo."""
    last_user_message = None
    for msg in reversed(messages):
        if msg.role == "user":
            last_user_message = msg.content
            break
    
    if not last_user_message:
        return "I didn't receive a message. How can I help you?", []
    
    return f"[OpenAI not configured] You said: {last_user_message}", []


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
def root():
    """Health check and API info."""
    return {
        "status": "running",
        "service": "PartSelect AI Agent",
        "model": "gpt-4o-mini",
        "openai_configured": client is not None,
        "port": 8001,
        "database_api": DATABASE_API_URL,
        "endpoints": {
            "chat": "POST /chat",
            "tools": "GET /tools",
            "health": "GET /health"
        }
    }


@app.get("/health")
async def health_check():
    """Check health of agent and database API connection."""
    agent_status = "healthy"
    db_api_status = "unknown"
    openai_status = "configured" if client else "not configured (set OPENAI_API_KEY)"
    
    # Check database API
    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.get(f"{DATABASE_API_URL}/health", timeout=5.0)
            if response.status_code == 200:
                db_api_status = "connected"
            else:
                db_api_status = f"error: {response.status_code}"
        except httpx.RequestError as e:
            db_api_status = f"unreachable: {str(e)}"
    
    return {
        "agent": agent_status,
        "openai": openai_status,
        "database_api": db_api_status,
        "database_api_url": DATABASE_API_URL
    }


@app.get("/tools")
def list_tools():
    """List all available tools the agent can use."""
    return {
        "count": len(OPENAI_TOOLS),
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "parameters": t["function"]["parameters"]
            }
            for t in OPENAI_TOOLS
        ]
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat endpoint for the AI agent.
    
    Uses GPT-4o-mini with tool calling to answer questions about parts and models.
    """
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        # Use LLM if configured, otherwise fallback
        if client:
            response_content, tool_calls = await process_message_with_llm(request.messages)
        else:
            response_content, tool_calls = await process_message_fallback(request.messages)
        
        return ChatResponse(
            message=ChatMessage(role="assistant", content=response_content),
            tool_calls=tool_calls if tool_calls else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Debug/Test Endpoint
# =============================================================================

@app.post("/test-tool")
async def test_tool(tool_name: str, parameters: dict):
    """Test endpoint to manually execute a tool."""
    result = await execute_tool(tool_name, parameters)
    return {
        "tool": tool_name,
        "parameters": parameters,
        "result": result
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, reload=True)
