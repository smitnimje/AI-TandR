import pyttsx3
import datetime
import json
import os
import wave
import struct
import math
import platform
import tempfile
from groq import Groq

# ==========================================
# DATABASE FILES
# ==========================================
DB_FILE        = "daily_itinerary.json"
HIDDEN_DB_FILE = "hidden_reminders.json"

# ==========================================
# GROQ CONFIG
# ==========================================
os.environ["GROQ_API_KEY"] = "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"
client = Groq()

# ==========================================
# SPEAK
# ==========================================
import threading as _threading
_tts_lock = _threading.Lock()

def speak(text):
    """Uses a lock so only one speak runs at a time.
    Reinits engine only if previous one crashed."""
    with _tts_lock:
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 170)
            engine.setProperty("volume", 1.0)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
            print("Agent:", text)
        except Exception as e:
            print(f"TTS Error: {e}")

# ==========================================
# BEEP / AUDIO CUE
# ==========================================
# Pre-generate beep WAV once at import time — reused on every call
_BEEP_PATH = os.path.join(tempfile.gettempdir(), "agent_beep.wav")
def _generate_beep_file(freq=880, duration=0.2, volume=0.7):
    try:
        sample_rate = 44100
        n    = int(sample_rate * duration)
        fade = int(sample_rate * 0.02)
        with wave.open(_BEEP_PATH, "w") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(sample_rate)
            for i in range(n):
                val = math.sin(2 * math.pi * freq * i / sample_rate)
                if i < fade:       val *= i / fade
                elif i > n - fade: val *= (n - i) / fade
                f.writeframes(struct.pack("<h", int(val * 32767 * volume)))
    except Exception as e:
        print(f"Beep gen error: {e}")
_generate_beep_file()  # run once at startup

def play_beep():
    """Play the pre-generated beep — no file generation delay."""
    try:
        system = platform.system()
        if system == "Windows":
            import winsound
            winsound.PlaySound(_BEEP_PATH, winsound.SND_FILENAME)
        elif system == "Darwin":
            os.system(f"afplay {_BEEP_PATH}")
        else:
            if os.system(f"aplay -q {_BEEP_PATH} 2>/dev/null") != 0:
                os.system(f"paplay {_BEEP_PATH} 2>/dev/null")
    except Exception as e:
        print(f"Beep error: {e}")

# ==========================================
# DATABASE INIT
# ==========================================

def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f:
            json.dump([], f)
    if not os.path.exists(HIDDEN_DB_FILE):
        with open(HIDDEN_DB_FILE, "w") as f:
            json.dump([], f)

# ==========================================
# LOAD / SAVE
# ==========================================
def load_tasks(file_path):
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except:
        return []

def save_tasks(data, file_path):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

# ==========================================
# NEXT GOAL ID
# ==========================================
def get_next_goal_id(goals):
    if not goals:
        return 1
    return max(goal["goal_id"] for goal in goals) + 1

# ==========================================
# ACTION CLASSIFIER
# Catches any variant the LLM might return
# ==========================================
def _classify_action(action_str: str) -> str:
    a = action_str.lower().strip()
    if "delete_step" in a or "remove_step" in a:
        return "delete_step"
    if ("delete" in a or "remove" in a or "clear" in a) and "step" not in a:
        return "delete"
    if "hidden" in a or "reminder" in a:
        return "hidden"
    if "edit" in a or "rename" in a or "shift" in a or "delay" in a or "forward" in a or "backward" in a or "reschedule" in a:
        return "edit_step"
    if ("delete" in a or "remove" in a) and "step" in a:
        return "delete_step"
    return "update"

# ==========================================
# FALLBACK: parse delete intent from raw command
# Used when AI returns wrong action but user clearly said delete
# ==========================================
def _command_is_delete(user_command: str) -> bool:
    cmd = user_command.lower()
    # If command mentions "step", it is an edit — NOT a goal delete
    if "step" in cmd:
        return False
    keywords = ["delete", "remove", "clear", "erase", "cancel goal", "drop goal"]
    return any(k in cmd for k in keywords)

# ==========================================
# PROCESS VOICE COMMAND
# ==========================================
def process_voice_command(user_command):

    now_str       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_goals = load_tasks(DB_FILE)

    # Compact goals summary — only send full JSON for edit/update actions
    # to keep token count low and response fast
    goals_summary = "\n".join(
        f"  goal_id={g['goal_id']}  name={g['goal_name']}  steps={len(g.get('steps',[]))}"
        for g in current_goals
    ) or "  (no goals currently)"

    # Only include full step details if command mentions step/rename/delay/time
    cmd_lower = user_command.lower()
    needs_full_data = any(w in cmd_lower for w in [
        "step", "rename", "delay", "push", "move", "shift",
        "reschedule", "forward", "backward", "earlier", "later", "time"
    ])
    full_data_str = json.dumps(current_goals, indent=2) if needs_full_data else "(omitted for speed — use goals_summary above)"

    prompt = f"""You are a task manager. Current time: {now_str}

Goals: {goals_summary}
Step data: {full_data_str}
Command: "{user_command}"

Return ONLY this JSON (no extra text):
{{"action":"update_goals|delete_goal|add_hidden|edit_step","delete_goal_ids":[],"hidden_reminder":{{"task":"","trigger_time":"YYYY-MM-DDTHH:MM:SS"}},"edit":{{"goal_id":0,"step_index":0,"new_task":null,"new_trigger_time":"YYYY-MM-DDTHH:MM:SS"}},"goals":[{{"goal_id":0,"goal_name":"","steps":[{{"task":"","trigger_time":"YYYY-MM-DDTHH:MM:SS","completed":false}}]}}]}}

Rules:
- delete/remove/clear goal (no "step" mentioned) -> delete_goal, fill delete_goal_ids
- delete/remove step -> delete_step, fill edit with goal_id and step_index
- remind me -> add_hidden, fill hidden_reminder
- rename/delay/shift/move/reschedule step -> edit_step, fill edit (step_index is 0-based)
- new plan/goal -> update_goals, fill goals with 2-4 steps
- ALL trigger_time fields MUST be full ISO format: YYYY-MM-DDTHH:MM:SS using current time {now_str} as base
- For delays: add the requested minutes/hours to the step's current trigger_time in step data above"""

    try:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "JSON only. No text. No markdown."},
                {"role": "user",   "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=400
        )

        raw  = chat.choices[0].message.content.strip()
        print("\n[GROQ RESPONSE]\n", raw)
        data = json.loads(raw)

        action_raw = data.get("action", "update_goals")
        action     = _classify_action(action_raw)
        print(f"[ACTION] raw='{action_raw}'  classified='{action}'")

        import re
        # Safety net: delete STEP override
        # If user said "delete step X of goal Y" but LLM returned edit_step
        cmd_l = user_command.lower()
        if action != "delete_step" and "step" in cmd_l and any(w in cmd_l for w in ["delete","remove","erase","cancel"]):
            print("[ACTION] Override -> delete_step")
            action = "delete_step"
            nums = re.findall(r'\d+', user_command)
            # Try to find goal_id and step_index from spoken numbers
            # "delete step 3 of goal 1" -> nums = [3, 1]
            # "delete step 2 of goal 2" -> nums = [2, 2]
            if len(nums) >= 2:
                step_num  = int(nums[0])   # 1-based from speech
                goal_num  = int(nums[1])
            elif len(nums) == 1:
                step_num  = int(nums[0])
                goal_num  = data.get("edit", {}).get("goal_id", 1)
            else:
                step_num, goal_num = 1, 1
            data["edit"] = {"goal_id": goal_num, "step_index": step_num - 1}  # convert to 0-based

        # Safety net: if LLM returned wrong action but user clearly said delete GOAL
        elif action != "delete" and _command_is_delete(user_command):
            print("[ACTION] Override -> delete")
            action = "delete"
            nums = re.findall(r'\d+', user_command)
            data["delete_goal_ids"] = [int(n) for n in nums] if nums else [g["goal_id"] for g in current_goals]

        # ---- DELETE ----
        if action == "delete":
            ids_to_delete = set(data.get("delete_goal_ids", []))
            if not ids_to_delete:
                ids_to_delete = {g["goal_id"] for g in current_goals}
            current = load_tasks(DB_FILE)
            updated = [g for g in current if g["goal_id"] not in ids_to_delete]
            # Renumber remaining goals 1, 2, 3... so gaps never appear
            for i, g in enumerate(updated, 1):
                g["goal_id"] = i
            save_tasks(updated, DB_FILE)
            print(f"[DELETE] Removed goal IDs: {ids_to_delete}")
            return "deleted"

        # ---- HIDDEN REMINDER ----
        elif action == "hidden":
            hidden_db = load_tasks(HIDDEN_DB_FILE)
            reminder  = data.get("hidden_reminder")
            if reminder:
                hidden_db.append(reminder)
                save_tasks(hidden_db, HIDDEN_DB_FILE)
            return "hidden"

        # ---- EDIT STEP ----
        elif action == "edit_step":
            edit      = data.get("edit", {})
            goal_id   = edit.get("goal_id")
            step_idx  = edit.get("step_index", 0)
            new_task  = edit.get("new_task")
            new_time  = edit.get("new_trigger_time")

            current = load_tasks(DB_FILE)
            changed = False
            for goal in current:
                if goal["goal_id"] == goal_id:
                    steps = goal.get("steps", [])
                    if 0 <= step_idx < len(steps):
                        if new_task:
                            steps[step_idx]["task"] = new_task
                            changed = True
                        if new_time:
                            steps[step_idx]["trigger_time"] = new_time
                            changed = True
                    break

            if changed:
                save_tasks(current, DB_FILE)
                print(f"[EDIT] Goal {goal_id} step {step_idx} updated")
            return "edited"

        # ---- DELETE STEP ----
        elif action == "delete_step":
            edit     = data.get("edit", {})
            goal_id  = edit.get("goal_id")
            step_idx = edit.get("step_index", 0)

            current = load_tasks(DB_FILE)
            for goal in current:
                if goal["goal_id"] == goal_id:
                    steps = goal.get("steps", [])
                    if 0 <= step_idx < len(steps):
                        steps.pop(step_idx)
                        print(f"[DELETE STEP] Goal {goal_id} step {step_idx} removed")
                    break
            save_tasks(current, DB_FILE)
            return "step_deleted"

        # ---- UPDATE / ADD GOALS ----
        else:
            current   = load_tasks(DB_FILE)
            new_goals = data.get("goals", [])
            for goal in new_goals:
                existing_ids = {g["goal_id"] for g in current}
                if goal.get("goal_id") not in existing_ids:
                    goal["goal_id"] = get_next_goal_id(current)
                    current.append(goal)
                else:
                    current = [goal if g["goal_id"] == goal["goal_id"] else g for g in current]
            save_tasks(current, DB_FILE)
            return "visible"

    except Exception as e:
        print(f"[GROQ ERROR] {e}")
        return "error"

# ==========================================
# CHECK DEADLINES
# ==========================================
def check_and_trigger_tasks():

    now       = datetime.datetime.now()
    triggered = []

    db      = load_tasks(DB_FILE)
    changed = False

    for goal in db:
        for step in goal["steps"]:
            if not step["completed"]:
                trigger_time = datetime.datetime.fromisoformat(step["trigger_time"])
                if now >= trigger_time:
                    triggered.append(step["task"])
                    step["completed"] = True
                    changed = True

    if changed:
        save_tasks(db, DB_FILE)

    hidden_db = load_tasks(HIDDEN_DB_FILE)
    remaining = []

    for reminder in hidden_db:
        trigger_time = datetime.datetime.fromisoformat(reminder["trigger_time"])
        if now >= trigger_time:
            triggered.append(reminder["task"])
        else:
            remaining.append(reminder)

    save_tasks(remaining, HIDDEN_DB_FILE)
    return triggered

# ==========================================
# STARTUP
# ==========================================
init_db()