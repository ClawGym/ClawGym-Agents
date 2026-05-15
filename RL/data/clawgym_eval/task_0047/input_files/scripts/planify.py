import json, csv, os

CONFIG_PATH = 'config/roadmap.json'
PLAN_DIR = 'plan'
PLAN_CSV = os.path.join(PLAN_DIR, 'plan.csv')


def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_plan_csv(tasks, out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['id', 'title', 'status'])
        for t in sorted(tasks, key=lambda x: x.get('id', '')):
            w.writerow([t.get('id', ''), t.get('title', ''), t.get('status', '')])


def main():
    data = load_config(CONFIG_PATH)
    tasks = data.get('tasks', [])
    write_plan_csv(tasks, PLAN_CSV)
    print(f"Wrote {len(tasks)} tasks to {PLAN_CSV}")


if __name__ == '__main__':
    main()
