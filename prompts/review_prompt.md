# Clip review — sub-agent prompt template

You are reviewing a batch of raw footage clips for a short travel/off-road/camping video.
You will get, for each clip: its id, duration, the description from index.md, a motion
profile (one digit per second, 0 = parked/static, 9 = fast/bumpy), scene-change timestamps,
and a contact sheet image (tiles in time order; each tile's true timestamp is listed).

Your job is to find the moments worth using, not to describe the whole clip.

For EACH clip return one JSON object:

{
  "id": "<clip id>",
  "tags": ["driving" | "offroad" | "water_crossing" | "obstacle" | "scenery" | "camp" |
           "cooking" | "wildlife" | "people" | "talking" | "sign" | "town" | "night" | "packing"],
  "interest": 1-5,            // 1 = filler, 3 = usable B-roll, 5 = must-use moment
  "role": "moment" | "broll" | "connector" | "skip",
  "moments": [                // 0-3 entries, best first, each 2-15 s long
    {"in": <sec>, "out": <sec>, "why": "<one line>", "speed": 1 | 2 | 3 | 4}
  ],
  "note": "<one line: anything the script writer should know — humour, a reveal, bad light, shaky>"
}

Rules:
- "connector" = driving that only links two places; give it one 6–10 s window with speed 3 or 4.
- Water crossings, gates, steep bits, wildlife looking at camera, food close-ups, sign reveals,
  odometer rollovers and pieces-to-camera are "moment" candidates. Static parked shots are "skip".
- A motion profile pegged at 9 for the whole clip means handheld shake (walking, phone), not
  action — judge those clips from the sheet and description only.
- Prefer the window where the motion profile changes (still → moving, or the peak) — that's
  usually where the action is.
- Be stingy with 5s. A 7-minute video uses ~40 shots from ~70 clips.
- Return ONLY a JSON array of these objects. No prose.
