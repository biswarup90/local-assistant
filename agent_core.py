from datetime import datetime
import json
import re
import time
import requests

OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"
OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"

API_KEY = "ollama"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}


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


# Define MODEL_NAME as a fallback default
MODEL_NAME = "default"


def get_current_prahar_context() -> str:
  now = datetime.now()
  hour = now.hour
  time_str = f"{hour:02d}:{now.minute:02d}"

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
          "Miyan ki Todi, Jaunpuri, Alhaiya Bilawal, Deshkar, Gujri Todi",
      ),
      (
          12,
          15,
          "3rd Prahar (Afternoon)",
          "Shuddha Sarang, Madhmad Sarang, Bhimpalasi, Multani, Vrindavani Sarang",
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
          "Marwa, Puriya, Purvi, Yaman, Shuddha Kalyan, Hameer, Kedar",
      ),
      (
          21,
          24,
          "6th Prahar (Night)",
          "Bageshree, Bihag, Chandrakauns, Kafi, Jaijaiwanti, Rageshree",
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
          "8th Prahar (Pre-dawn / Brahma Muhurta)",
          "Bhatiyar, Lalit, Sohini, Vibhas",
      ),
  ]

  for start, end, label, ragas in prahar_map:
    if start <= hour < end:
      return (
          f"Current Time: {time_str}. Prahar: {label}. Ragas for this prahar:"
          f" {ragas}."
      )

  return (
      f"Current Time: {time_str}. Prahar: 8th Prahar (Pre-dawn). Ragas:"
      " Bhatiyar, Lalit, Sohini, Vibhas."
  )


def build_system_prompt() -> str:
  prahar_info = get_current_prahar_context()
  return f"""You are an Indian Classical Music Curator.
Temporal Reference: {prahar_info}

Core Directives:
1. Diversity of Tradition: Explore varied mediums—vocal (khayal, dhrupad, thumri) and diverse instruments (sitar, sarod, flute/bansuri, santoor, violin, shehnai, rudra veena). Avoid repeating the same artist or raga consecutively.
2. User Priority: If the user requests a specific mood, artist, or raga, prioritize their wish over the Prahar. Otherwise, curate using the active Prahar.
3. Decision Protocol:
   - If the request is ambiguous, ask ONE focused question.
   - When curating, formulate exactly ONE tool action:
     Action: search_itunes(ArtistName RagaName)
   - Do NOT produce multiple actions or generic placeholders.
4. Response Format:
   Response: <Explain the musical ethos, why this raga matches the sentiment, and introduce the artist.>
"""


def call_local_llm(messages: list[dict], temperature: float = 0.55) -> str:
  global MODEL_NAME

  # Dynamically discover the active model from ai.local
  active_model = get_active_model()
  if active_model != "default":
    MODEL_NAME = active_model

  payload = {
      "model": MODEL_NAME,
      "messages": messages,
      "stream": False,
      "options": {
          "temperature": temperature,
          "top_p": 0.9,
          "num_predict": 300,
      },
  }
  try:
    res = requests.post(
        OLLAMA_CHAT_URL, json=payload, headers=HEADERS, timeout=40
    )
    if res.status_code == 401:
      return "Error 401: Unauthorized."
    data = res.json()
    if "error" in data:
      return f"Local server error: {data['error']}"
    return data["message"]["content"]
  except Exception as e:
    return f"Error contacting local server: {e}"


def tool_search_itunes(query: str) -> str:
  cleaned = query.strip("'\"\n ")
  cleaned = cleaned.split("\n")[0].split("Action:")[0].strip()

  if not cleaned or cleaned.lower() in [
      "query_string",
      "query",
      "artistname raganame",
      "artist name raga name",
  ]:
    return "Error: Please specify a recognized maestro and raga name."

  def _query_itunes(term: str):
    url = "https://itunes.apple.com/search"
    params = {
        "term": term,
        "media": "music",
        "entity": "song",
        "country": "IN",
        "limit": 3,
    }
    r = requests.get(url, params=params, timeout=8)
    return r.json().get("results", [])

  try:
    tracks = _query_itunes(cleaned)

    # Fallback retry: If no track found, split and search main keywords
    if not tracks and " " in cleaned:
      parts = cleaned.split()
      if len(parts) > 2:
        tracks = _query_itunes(f"{parts[0]} {parts[-1]}")

    clean = [
        {
            "title": t.get("trackName"),
            "artist": t.get("artistName"),
            "album": t.get("collectionName"),
            "apple_music_link": t.get("trackViewUrl"),
            "preview_url": t.get("previewUrl"),
        }
        for t in tracks
    ]
    return json.dumps(clean[:1]) if clean else "No tracks found."
  except Exception as e:
    return f"iTunes search failed: {e}"


TOOL_MAP = {"search_itunes": tool_search_itunes}


def parse_action(text: str):
  match = re.search(r"Action:\s*([a-zA-Z0-9_]+)\s*\((.*?)\)", text)
  if match:
    name = match.group(1).strip()
    arg = match.group(2).strip("'\"\n ")
    if arg.lower() not in [
        "query_string",
        "query",
        "artistname raganame",
        "artist name raga name",
    ]:
      return name, arg

  match2 = re.search(r"Action:\s*([a-zA-Z0-9_]+)\s*:\s*(.*)", text)
  if match2:
    name = match2.group(1).strip()
    arg = match2.group(2).strip("'\"\n ")
    if arg.lower() not in [
        "query_string",
        "query",
        "artistname raganame",
        "artist name raga name",
    ]:
      return name, arg

  return None, None