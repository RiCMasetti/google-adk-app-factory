"""ADK root agent for `adk web .` and related ADK CLI tools."""

from app.agents import create_orchestrator_agent
from app.config import load_env_file

load_env_file()
root_agent = create_orchestrator_agent()
