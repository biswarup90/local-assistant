import json
import re
import webbrowser
import ipywidgets as widgets
from IPython.display import HTML, display
import agent_core as core

chat_history = widgets.Output(
    layout=widgets.Layout(
        width="100%",
        height="380px",
        overflow_y="auto",
        border="1px solid #d1d5db",
        padding="10px",
        background_color="#ffffff",
        border_radius="8px"
    )
)

user_input = widgets.Text(
    placeholder="Share your mood, instrument preference, or raga...",
    layout=widgets.Layout(width="78%", height="40px")
)

send_btn = widgets.Button(
    description="Send",
    button_style="primary",
    layout=widgets.Layout(width="20%", height="40px")
)

status_label = widgets.HTML(
    value="<span style='color: #6b7280; font-size: 12px;'>Curator ready.</span>",
    layout=widgets.Layout(margin="4px 0 0 4px")
)

input_row = widgets.HBox(
    [user_input, send_btn],
    layout=widgets.Layout(width="100%", margin="8px 0 0 0")
)

CONVERSATION_HISTORY = []
LAST_TRACK = None
IS_PROCESSING = False


def open_in_apple_music(url: str):
    webbrowser.open(url)


def render_message(sender: str, text: str, track: dict = None):
    with chat_history:
        is_user = sender == "User"
        is_sys = sender == "System"
        bg = "#e8f0fe" if is_user else ("#fef2f2" if "Error" in sender else ("#f3f4f6" if is_sys else "#ffffff"))
        align = "flex-end" if is_user else "flex-start"
        formatted = text.replace("\n", "<br/>")

        html = f"""
        <div style="display: flex; justify-content: {align}; margin: 6px 0; font-family: -apple-system, sans-serif;">
            <div style="background-color: {bg}; border: 1px solid #e5e7eb; padding: 10px 14px; border-radius: 10px; max-width: 85%;">
                <div style="font-size: 11px; color: #6b7280; font-weight: 600; margin-bottom: 3px;">{sender}</div>
                <div style="font-size: 14px; color: #111827; line-height: 1.4;">{formatted}</div>
            </div>
        </div>
        """
        display(HTML(html))

        if track:
            preview_url = track.get("preview_url")
            apple_url = track.get("apple_music_link")
            title = track.get("title", "Selected Piece")
            artist = track.get("artist", "")

            track_info_html = f"""
            <div style="background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; margin: 6px 0; font-family: -apple-system, sans-serif;">
                <div style="font-size: 13px; font-weight: 600; color: #1f2937;">🎵 {title} — <span style="color: #4b5563; font-weight: normal;">{artist}</span></div>
            """
            if preview_url:
                track_info_html += f"""
                <div style="margin-top: 6px;">
                    <audio controls src="{preview_url}" style="width: 100%; height: 32px;"></audio>
                </div>
                """
            track_info_html += "</div>"
            display(HTML(track_info_html))

            if apple_url:
                play_btn = widgets.Button(
                    description="▶ Open Full Track in Apple Music",
                    button_style="danger",
                    layout=widgets.Layout(width="260px", height="34px", margin="4px 0 8px 0")
                )
                play_btn.on_click(lambda b, u=apple_url: open_in_apple_music(u))
                display(play_btn)


def process_user_turn(user_text: str):
    global CONVERSATION_HISTORY, LAST_TRACK, IS_PROCESSING

    status_label.value = "<span style='color: #2563eb; font-size: 12px;'>⏳ Thinking... querying local model</span>"
    CONVERSATION_HISTORY.append({"role": "user", "content": user_text})

    try:
        llm_reply = core.call_local_llm(CONVERSATION_HISTORY)

        # Check if local backend threw an explicit error
        if llm_reply.startswith("Error") or "Local server error:" in llm_reply:
            render_message("Error", llm_reply)
            status_label.value = "<span style='color: #dc2626; font-size: 12px;'>Connection error.</span>"
            return

        tool_name, tool_arg = core.parse_action(llm_reply)
        found_track = None

        if tool_name and tool_name in core.TOOL_MAP:
            status_label.value = f"<span style='color: #2563eb; font-size: 12px;'>🔍 Searching iTunes for: {tool_arg}</span>"
            render_message("System", f"🔍 Searching catalog: <code>{tool_arg}</code>")

            raw_out = core.TOOL_MAP[tool_name](tool_arg)
            try:
                parsed = json.loads(raw_out)
                if isinstance(parsed, list) and len(parsed) > 0:
                    found_track = parsed[0]
                    LAST_TRACK = found_track
            except Exception:
                pass

            CONVERSATION_HISTORY.append({"role": "assistant", "content": llm_reply})
            CONVERSATION_HISTORY.append(
                {"role": "user", "content": f"Observation: {raw_out}\nNow introduce this track to the listener."})

            status_label.value = "<span style='color: #2563eb; font-size: 12px;'>⏳ Formatting reflection...</span>"
            final_summary = core.call_local_llm(CONVERSATION_HISTORY)
            clean_text = final_summary.split("Response:")[-1].strip()
            render_message("Curator", clean_text, track=found_track)
            CONVERSATION_HISTORY.append({"role": "assistant", "content": clean_text})
        else:
            clean_text = llm_reply.split("Response:")[-1].strip()
            render_message("Curator", clean_text, track=None)
            CONVERSATION_HISTORY.append({"role": "assistant", "content": clean_text})

        status_label.value = "<span style='color: #10b981; font-size: 12px;'>● Ready</span>"

    except Exception as e:
        render_message("Error", f"Execution error in turn: {str(e)}")
        status_label.value = "<span style='color: #dc2626; font-size: 12px;'>Error occurred.</span>"
    finally:
        IS_PROCESSING = False


def _on_send_clicked(b):
    global IS_PROCESSING
    if IS_PROCESSING:
        return
    q = user_input.value.strip()
    if not q:
        return
    IS_PROCESSING = True
    user_input.value = ""
    render_message("User", q)
    process_user_turn(q)


send_btn.on_click(_on_send_clicked)


def launch_app():
    global CONVERSATION_HISTORY, LAST_TRACK, IS_PROCESSING
    CONVERSATION_HISTORY = [{"role": "system", "content": core.build_system_prompt()}]
    LAST_TRACK = None
    IS_PROCESSING = False

    display(chat_history)
    display(input_row)
    display(status_label)
    render_message("Curator", "Namaste! How are you feeling right now?")