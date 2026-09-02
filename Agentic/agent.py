"""
Google Agent Development Kit (ADK) Root Agent Definition Entry Point.
"""

from fintech_agent.agent import root_agent

__all__ = ["root_agent"]

if __name__ == "__main__":
    tool_names = [getattr(t, "__name__", str(t)) for t in root_agent.tools]
    print("=" * 70)
    print(f"ADK Root Agent '{root_agent.name}' initialized successfully!")
    print(f"  Model: {root_agent.model}")
    print(f"  Registered Tools ({len(tool_names)}): {', '.join(tool_names)}")
    print("=" * 70)
