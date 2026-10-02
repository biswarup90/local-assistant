import importlib
import agent_core as core
import chat_ui

# Forces Python to reload the modules from disk if you edited them
importlib.reload(core)
importlib.reload(chat_ui)

chat_ui.launch_app()
