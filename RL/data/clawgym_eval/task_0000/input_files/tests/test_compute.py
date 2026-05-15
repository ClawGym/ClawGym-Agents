from tools.summarize import compute_summary

def test_compute_summary_from_csv():
    summary = compute_summary("data/tasks.csv")
    assert summary["total_tasks"] == 7
    assert summary["by_status"] == {
        "todo": 2,
        "in_progress": 2,
        "done": 2,
        "blocked": 1,
    }
    assert summary["by_assignee"] == {
        "Tina": 2,
        "Marco": 1,
        "Eli": 2,
        "Sam": 1,
        "Nora": 1,
    }
