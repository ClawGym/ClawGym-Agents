import yaml

with open('input/training_config.yaml') as f:
    cfg = yaml.safe_load(f)


def print_plan(cfg):
    print("Weekly sessions:", cfg['weekly_sessions'])
    print("Focus skills:", ", ".join(cfg['focus_skills']))
    # Note: this uses a different key name than the YAML might provide
    min_hang = cfg.get('hangboard_minutes', 10)
    print("Hangboard minimum minutes:", min_hang)
    # Expects a plural list of rest days
    rest_days = cfg['rest_days']
    print("Rest days:", ", ".join(rest_days))
    goal = cfg['max_grade_goal']
    print("Max grade goal:", goal)


if __name__ == "__main__":
    print_plan(cfg)
