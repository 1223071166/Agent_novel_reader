from services.chat_service import ChatService
from cli_debug import display, execute_summary_command, execute_user_tool, show_help
from config import BOOK_ID, BookPaths


def chat():
    service = ChatService()
    book_path = BookPaths(BOOK_ID)
    conversation_id = "cli"
    while True:
        try:
            user_input=input("\n[user]:")
        except (EOFError, KeyboardInterrupt):
            print("\n[chat ended]")
            break

        if user_input.lower() in ["exit","quit",'/exit','/quit']:
            break
        if user_input.startswith("/help"):
            show_help(service._tools)
            continue
        if user_input.startswith("/tool"):
            execute_user_tool(user_input,service._available_tools)
            continue
        if user_input.startswith("/summary"):
            execute_summary_command(user_input, book_path)
            continue

        print("[AI searching...]")
        printed_header = False
        for event in service.stream_message(BOOK_ID, conversation_id, user_input):
            if event.event == "token":
                if not printed_header:
                    print("[assistant]:")
                    printed_header = True
                print(event.data["content"], end="", flush=True)
            elif event.event == "tool_start":
                print(f"\n[tool:{event.data['name']}]")
            elif event.event == "tool_result" and event.data.get("error"):
                print(f"[tool error] {event.data['result']['display']}")
            elif event.event == "tool_result":
                display(event.data["result"])
            elif event.event == "usage":
                print()
                from usage_stats import display_usage
                display_usage(event.data)
            elif event.event == "error":
                print(f"\n[API error] {event.data['message']}")
        if printed_header:
            print()
if __name__=="__main__":
    chat()
