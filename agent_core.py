import json
import re
import time
from datetime import datetime
import requests

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

API_KEY = "ollama"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}


class SessionMemory:

  def __init__(self):
    self.active_directives = []
    self.played_tracks = []

  def update_from_input(self, text: str):
    t = text.lower()
    if "no vocal" in t or "instrumental" in t:
      if "Instrumental only" not in self.active_directives:
        self.active_directives.append("Instrumental only")
    elif "vocal" in t and "no vocal" not in t:
      if "Vocal preferred" not in self.active_directives:
        self.active_directives.append("Vocal preferred")

    if any(k in t for k in ["percussion", "tabla", "pakhawaj"]):
      if (
          "Emphasize rhythmic/percussive accompaniment"
          not in self.active_directives
      ):
        self.active_directives.append(
            "Emphasize rhythmic/percussive accompaniment"
        )

  def record_track(self, title: str, artist: str):
    if title and artist:
      self.played_tracks.append(f"{artist} - {title}")

  def get_context_block(self) -> str:
    lines = []
    if self.active_directives:
      lines.append(
          "Active User Constraints: " + "; ".join(self.active_directives)
      )
    if self.played_tracks:
      recent = self.played_tracks[-5:]
      lines.append(
          "Already Recommended This Session (DO NOT repeat): "
          + "; ".join(recent)
      )
    return "\n".join(lines) if lines else "None active."


SESSION = SessionMemory()


def get_active_model(retries: int = 3) -> str:
  for attempt in range(retries):
    try:
      res = requests.get(OLLAMA_TAGS_URL, headers=HEADERS, timeout=4).json()
      models = res.get("models", [])
      if models:
        return models[0]["name"]
    except Exception:
      if attempt < retries - 1:
        time.sleep(1)
  return "default"


MODEL_NAME = "default"


def get_current_prahar_context() -> str:
  hour = datetime.now().hour
  prahar_map = [
      (
          6,
          9,
          "1st Prahar (Morning)",
          "Bhairav, Ahir Bhairav, Ramkali, Gunakri, Lalit, Todi",
      ),
      (
          9,
          12,
          "2nd Prahar (Late Morning)",
          "Miyan ki Todi, Jaunpuri, Alhaiya Bilawal, Deshkar",
      ),
      (
          12,
          15,
          "3rd Prahar (Afternoon)",
          "Shuddha Sarang, Madhmad Sarang, Bhimpalasi, Multani",
      ),
      (
          15,
          18,
          "4th Prahar (Late Afternoon)",
          "Multani, Bhimpalasi, Patdeep, Pilu, Madhuvanti",
      ),
      (
          18,
          21,
          "5th Prahar (Twilight / Sandhiprakash)",
          "Marwa, Puriya, Purvi, Yaman, Shuddha Kalyan, Kedar",
      ),
      (
          21,
          24,
          "6th Prahar (Night)",
          "Bageshree, Bihag, Chandrakauns, Kafi, Jaijaiwanti",
      ),
      (
          0,
          3,
          "7th Prahar (Midnight)",
          "Darbari Kanada, Malkauns, Shankara, Adana, Abhogi",
      ),
      (
          3,
          6,
          "8th Prahar (Pre-dawn)",
          "Bhatiyar, Lalit, Sohini, Vibhas",
      ),
  ]
  for start, end, label, ragas in prahar_map:
    if start <= hour < end:
      return f"{label}. Recommended Ragas: {ragas}"
  return "8th Prahar (Pre-dawn). Recommended Ragas: Bhatiyar, Lalit, Sohini"


def build_system_prompt() -> str:
  temporal_context = get_current_prahar_context()
  memory_block = SESSION.get_context_block()

  return f"""You are a master Indian Classical Music Curator.
Current Temporal Context: {temporal_context}

SESSION CONSTRAINTS & HISTORY:
{memory_block}

REASONING PROTOCOL:
Before you search, you MUST explicitly write a brief Thought line analyzing:
1. The user's mood, explicit constraints (instruments, tempo), and the Prahar.
2. The specific maestro and raga you are picking to fulfill this exact mood.

FORMAT:
Thought: <Your reasoning explaining why this raga, maestro, and accompaniment match the request>
Action: search_itunes(MaestroName RagaName)

Do not output multiple searches. Make one definitive choice.
"""


def call_local_llm(messages: list[dict], temperature: float = 0.5) -> str:
  global MODEL_NAME
  active = get_active_model()
  if active != "default":
    MODEL_NAME = active

  payload = {
      "model": MODEL_NAME,
      "messages": messages,
      "stream": False,
      "options": {
          "temperature": temperature,
          "top_p": 0.9,
          "num_predict": 350,
      },
  }
  try:
    res = requests.post(
        OLLAMA_CHAT_URL, json=payload, headers=HEADERS, timeout=40
    )
    if res.status_code == 401:
      return "Error: Unauthorized."
    data = res.json()
    return data.get("message", {}).get("content", "")
  except Exception as e:
    return f"Error contacting local server: {e}"


def tool_search_itunes(query: str) -> str:
  cleaned = query.strip("'\"\n ").split("\n")[0].split("Action:")[0].strip()
  if not cleaned or cleaned.lower() in [
      "query",
      "artistname raganame",
      "artist name raga name",
  ]:
    return "Error: Provide real artist and raga names."

  def _query_api(term: str):
    url = "https://itunes.apple.com/search"
    params = {
        "term": term,
        "media": "music",
        "entity": "song",
        "country": "IN",
        "limit": 5,
    }
    try:
      r = requests.get(url, params=params, timeout=7)
      return r.json().get("results", [])
    except Exception:
      return []

  # Pass 1: Raw search query
  results = _query_api(cleaned)

  # Pass 2: Strip common honorifics that iTunes metadata often omits
  if not results:
    simplified = re.sub(
        r"\b(pandit|pt\.|pt|ustad|vidwan)\b", "", cleaned, flags=re.IGNORECASE
    ).strip()
    if simplified != cleaned:
      results = _query_api(simplified)

  # Pass 3: Keyword search with first and last terms
  if not results and " " in cleaned:
    parts = cleaned.split()
    if len(parts) >= 3:
      results = _query_api(f"{parts[0]} {parts[-1]}")

  if not results:
    return "No tracks found on Apple Music for this query."

  track = results[0]
  clean_result = [{
      "title": track.get("trackName"),
      "artist": track.get("artistName"),
      "album": track.get("collectionName"),
      "apple_music_link": track.get("trackViewUrl"),
      "preview_url": track.get("previewUrl"),
  }]
  return json.dumps(clean_result)


TOOL_MAP = {"search_itunes": tool_search_itunes}


def parse_thought_and_action(text: str):
  thought = ""
  action_name = None
  action_arg = None

  thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", text, re.DOTALL)
  if thought_match:
    thought = thought_match.group(1).strip()

  action_match = re.search(r"Action:\s*([a-zA-Z0-9_]+)\s*\((.*?)\)", text)
  if action_match:
    action_name = action_match.group(1).strip()
    action_arg = action_match.group(2).strip("'\"\n ")
  else:
    action_match2 = re.search(r"Action:\s*([a-zA-Z0-9_]+)\s*:\s*(.*)", text)
    if action_match2:
      action_name = action_match2.group(1).strip()
      action_arg = action_match2.group(2).strip("'\"\n ")

  return thought, action_name, action_arg