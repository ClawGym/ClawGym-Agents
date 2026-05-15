import json
import os
import sys
from datetime import datetime

def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def is_iso_timestamp(s):
    if not isinstance(s, str) or not s.strip():
        return False
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except Exception:
        return False

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    wake_dir = os.path.join(output_dir, "wake")
    state_path = os.path.join(wake_dir, "state.json")
    tasks_path = os.path.join(wake_dir, "tasks.json")
    hb_path = os.path.join(wake_dir, "heartbeat.json")
    cp_meta_path = os.path.join(wake_dir, "checkpoints", "pre-migration", "meta.json")
    summary_path = os.path.join(output_dir, "state_summary.json")

    checks = {
        # Existence checks
        "exists_state_json": False,
        "exists_tasks_json": False,
        "exists_heartbeat_json": False,
        "exists_checkpoint_meta_json": False,
        "exists_state_summary_json": False,

        # State content checks
        "state_status_ok": False,
        "state_current_task_ok": False,
        "state_notes_contains_kickoff": False,
        "state_custom_no_phase": False,

        # Tasks content checks
        "tasks_have_ids_1_2_3_only": False,
        "tasks_all_pending": False,
        "task1_details_ok": False,
        "task2_details_ok": False,
        "task3_details_ok": False,

        # Heartbeat checks
        "heartbeat_last_beat_iso": False,
        "heartbeat_last_session_ok": False,

        # Summary checks
        "summary_status_ok": False,
        "summary_current_task_ok": False,
        "summary_note_count_ok": False,
        "summary_custom_is_object_no_phase": False,
        "summary_pending_tasks_ok": False,
        "summary_done_tasks_empty": False,
        "summary_checkpoint_exists_true": False,
        "summary_heartbeat_matches": False,
        "summary_phase_value_null": False,
    }

    # Existence
    if os.path.isfile(state_path):
        checks["exists_state_json"] = True
    if os.path.isfile(tasks_path):
        checks["exists_tasks_json"] = True
    if os.path.isfile(hb_path):
        checks["exists_heartbeat_json"] = True
    if os.path.isfile(cp_meta_path):
        checks["exists_checkpoint_meta_json"] = True
    if os.path.isfile(summary_path):
        checks["exists_state_summary_json"] = True

    # Load files if exist
    state_data = load_json(state_path) if checks["exists_state_json"] else None
    tasks_data = load_json(tasks_path) if checks["exists_tasks_json"] else None
    hb_data = load_json(hb_path) if checks["exists_heartbeat_json"] else None
    summary_data = load_json(summary_path) if checks["exists_state_summary_json"] else None

    # State checks
    if isinstance(state_data, dict):
        if state_data.get("status") == "Planning rollout":
            checks["state_status_ok"] = True
        if state_data.get("current_task") == "Prepare migration plan":
            checks["state_current_task_ok"] = True
        notes = state_data.get("notes", [])
        if isinstance(notes, list):
            for n in notes:
                try:
                    content = n.get("content", "") if isinstance(n, dict) else ""
                except Exception:
                    content = ""
                if isinstance(content, str) and "Kickoff at 09:00 UTC" in content:
                    checks["state_notes_contains_kickoff"] = True
                    break
        custom = state_data.get("custom", {})
        if isinstance(custom, dict) and ("phase" not in custom):
            checks["state_custom_no_phase"] = True

    # Tasks checks
    tmap = {}
    tasks_list = None
    if isinstance(tasks_data, dict):
        tasks_list = tasks_data.get("tasks")
    if isinstance(tasks_list, list):
        for t in tasks_list:
            if isinstance(t, dict) and isinstance(t.get("id"), int):
                tmap[t["id"]] = t
        if set(tmap.keys()) == {1, 2, 3} and len(tasks_list) == 3:
            checks["tasks_have_ids_1_2_3_only"] = True
        # All pending for ids 1,2,3
        if all(isinstance(tmap.get(i), dict) and tmap[i].get("status") == "pending" for i in [1, 2, 3]):
            checks["tasks_all_pending"] = True
        # Details per task
        t1 = tmap.get(1)
        if isinstance(t1, dict) and t1.get("priority") == "critical" and isinstance(t1.get("task"), str) and "Take db snapshot" in t1.get("task", ""):
            checks["task1_details_ok"] = True
        t2 = tmap.get(2)
        if isinstance(t2, dict) and t2.get("priority") == "high" and isinstance(t2.get("task"), str) and "Notify stakeholders" in t2.get("task", ""):
            checks["task2_details_ok"] = True
        t3 = tmap.get(3)
        if isinstance(t3, dict) and t3.get("priority") == "normal" and isinstance(t3.get("task"), str) and "Update runbook" in t3.get("task", ""):
            checks["task3_details_ok"] = True

    # Heartbeat checks
    if isinstance(hb_data, dict):
        last_beat = hb_data.get("last_beat")
        if is_iso_timestamp(last_beat):
            checks["heartbeat_last_beat_iso"] = True
        beats = hb_data.get("beats")
        if isinstance(beats, list) and len(beats) > 0:
            last = beats[-1]
            if isinstance(last, dict) and last.get("session") == "test-session":
                checks["heartbeat_last_session_ok"] = True

    # Summary checks
    if isinstance(summary_data, dict):
        if summary_data.get("status") == "Planning rollout":
            checks["summary_status_ok"] = True
        if summary_data.get("current_task") == "Prepare migration plan":
            checks["summary_current_task_ok"] = True
        note_count = summary_data.get("note_count")
        if isinstance(note_count, int) and note_count >= 1:
            checks["summary_note_count_ok"] = True
        custom_sum = summary_data.get("custom")
        if isinstance(custom_sum, dict) and ("phase" not in custom_sum):
            checks["summary_custom_is_object_no_phase"] = True
        pending_tasks = summary_data.get("pending_tasks")
        if isinstance(pending_tasks, list) and pending_tasks == [1, 2, 3]:
            checks["summary_pending_tasks_ok"] = True
        done_tasks = summary_data.get("done_tasks")
        if isinstance(done_tasks, list) and len(done_tasks) == 0:
            checks["summary_done_tasks_empty"] = True
        if summary_data.get("checkpoint_exists") is True:
            checks["summary_checkpoint_exists_true"] = True
        # heartbeat_last_beat matches hb last_beat
        sm_hb = summary_data.get("heartbeat_last_beat")
        hb_last = hb_data.get("last_beat") if isinstance(hb_data, dict) else None
        if isinstance(sm_hb, str) and sm_hb == hb_last and sm_hb:
            checks["summary_heartbeat_matches"] = True
        # phase_value null
        if "phase_value" in summary_data and summary_data.get("phase_value") is None:
            checks["summary_phase_value_null"] = True

    # Compute reward
    total_checks = len(checks)
    passed_checks = sum(1 for v in checks.values() if v)
    # Ensure no-op baseline yields 0.0 if nothing was produced
    reward = 0.0
    if passed_checks > 0:
        reward = passed_checks / total_checks
    result = {"reward": reward}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()