import json
import re
import webbrowser
from IPython.display import HTML, display
import agent_core as core
import ipywidgets as widgets

chat_history = widgets.Output(
    layout=widgets.Layout(
        width="100%",
        height="380px",
        overflow_y="auto",
        border="1px solid #d1d5db",
        padding="10px",
        background_color="#ffffff",
        border_radius="8px",
    )
)

user_input = widgets.Text(
    placeholder="Share your mood, instrument preference, or raga...",
    layout=widgets.Layout(width="68%", height="40px"),
)

send_btn = widgets.Button(
    description="Send",
    button_style="primary",
    layout=widgets.Layout(width="15%", height="40px"),
)

reset_btn = widgets.Button(
    description="Reset",
    button_style="warning",
    layout=widgets.Layout(width="14%", height="40px"),
)

status_label = widgets.HTML(
    value=(
        "<span style='color: #6b7280; font-size: 12px;'>Curator ready.</span>"
    ),
    layout=widgets.Layout(margin="4px 0 0 4px"),
)

input_row = widgets.HBox(
    [user_input, send_btn, reset_btn],
    layout=widgets.Layout(width="100%", margin="8px 0 0 0"),
)

CONVERSATION_HISTORY = []
IS_PROCESSING = False


def open_in_apple_music(url: str):
  webbrowser.open(url)


def render_message(sender: str, text: str, track: dict = None):
  with chat_history:
    is_user = sender == "User"
    is_sys = sender == "System"
    is_thought = "Reasoning" in sender

    if is_user:
      bg = "#e8f0fe"
      align = "flex-end"
    elif "Error" in sender:
      bg = "#fef2f2"
      align = "flex-start"
    elif is_thought:
      bg = "#fefce8"
      align = "flex-start"
    elif is_sys:
      bg = "#f3f4f6"
      align = "flex-start"
    else:
      bg = "#ffffff"
      align = "flex-start"

    formatted = text.replace("\n", "<br/>")

    html = f"""
        <div style="display: flex; justify-content: {align}; margin: 6px 0; font-family: -apple-system, BlinkMacSystemFont, sans-serif;">
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

      track_html = f"""
            <div style="background: #fafafa; border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; margin: 6px 0; font-family: -apple-system, sans-serif;">
                <div style="font-size: 13px; font-weight: 600; color: #1f2937;">🎵 {title} — <span style="color: #4b5563; font-weight: normal;">{artist}</span></div>
            """
      if preview_url:
        track_html += f"""
                <div style="margin-top: 6px;">
                    <audio controls src="{preview_url}" style="width: 100%; height: 32px;"></audio>
                </div>
                """
      track_html += "</div>"
      display(HTML(track_html))

      if apple_url:
        play_btn = widgets.Button(
            description="▶ Open Full Track in Apple Music",
            button_style="danger",
            layout=widgets.Layout(
                width="270px", height="34px", margin="4px 0 8px 0"
            ),
        )
        play_btn.on_click(lambda b, u=apple_url: open_in_apple_music(u))
        display(play_btn)


def process_user_turn(user_text: str):
  global CONVERSATION_HISTORY, IS_PROCESSING

  try:
    status_label.value = (
        "<span style='color: #2563eb; font-size: 12px;'>⏳ Thinking...</span>"
    )

    # Clean turn variables to eliminate cross-turn leakage
    found_track = None
    raw_out = None

    core.SESSION.update_from_input(user_text)

    sys_prompt = {"role": "system", "content": core.build_system_prompt()}
    if not CONVERSATION_HISTORY:
      CONVERSATION_HISTORY = [sys_prompt]
    else:
      CONVERSATION_HISTORY[0] = sys_prompt

    CONVERSATION_HISTORY.append({"role": "user", "content": user_text})

    llm_reply = core.call_local_llm(CONVERSATION_HISTORY)

    if llm_reply.startswith("Error"):
      render_message("Error", llm_reply)
      status_label.value = (
          "<span style='color: #dc2626; font-size: 12px;'>Server error.</span>"
      )
      return

    thought, tool_name, tool_arg = core.parse_thought_and_action(llm_reply)

    if thought:
      render_message("Curator (Reasoning)", f"💭 <i>{thought}</i>")

    if tool_name and tool_name in core.TOOL_MAP:
      status_label.value = (
          f"<span style='color: #2563eb; font-size: 12px;'>🔍 Searching: "
          f"{tool_arg}</span>"
      )
      render_message("System", f"🔍 Searching catalog: <code>{tool_arg}</code>")

      raw_out = core.TOOL_MAP[tool_name](tool_arg)

      try:
        parsed = json.loads(raw_out)
        if isinstance(parsed, list) and len(parsed) > 0:
          found_track = parsed[0]
          core.SESSION.record_track(
              found_track.get("title", ""), found_track.get("artist", "")
          )
      except Exception:
        found_track = None

      if not found_track:
        render_message(
            "System",
            f"⚠️ No track preview available for <code>{tool_arg}</code>.",
        )

      CONVERSATION_HISTORY.append({"role": "assistant", "content": llm_reply})
      CONVERSATION_HISTORY.append({
          "role": "user",
          "content": (
              f"Observation: {raw_out}\nBriefly introduce this piece to the"
              " user without repeating your thought."
          ),
      })

      status_label.value = (
          "<span style='color: #2563eb; font-size: 12px;'>⏳ Presenting...</span>"
      )
      final_summary = core.call_local_llm(CONVERSATION_HISTORY)

      clean_text = final_summary.split("Response:")[-1]
      clean_text = re.sub(
          r"^Thought:.*?(?=(Response:|\n\n|$))", "", clean_text, flags=re.DOTALL
      ).strip()
      if not clean_text:
        clean_text = final_summary.strip()

      render_message("Curator", clean_text, track=found_track)
      CONVERSATION_HISTORY.append({"role": "assistant", "content": clean_text})

    else:
      clean_text = llm_reply.split("Response:")[-1].strip()
      render_message("Curator", clean_text, track=None)
      CONVERSATION_HISTORY.append({"role": "assistant", "content": clean_text})

    status_label.value = (
        "<span style='color: #10b981; font-size: 12px;'>● Ready</span>"
    )

  except Exception as e:
    render_message("Error", f"Turn error: {str(e)}")
    status_label.value = (
        "<span style='color: #dc2626; font-size: 12px;'>Error</span>"
    )
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


def _on_reset_clicked(b):
  launch_app()


send_btn.on_click(_on_send_clicked)
reset_btn.on_click(_on_reset_clicked)


def launch_app():
  global CONVERSATION_HISTORY, IS_PROCESSING
  chat_history.clear_output()
  core.SESSION = core.SessionMemory()
  CONVERSATION_HISTORY = [
      {"role": "system", "content": core.build_system_prompt()}
  ]
  IS_PROCESSING = False

  display(chat_history)
  display(input_row)
  display(status_label)
  render_message("Curator", "Namaste! How are you feeling right now?")