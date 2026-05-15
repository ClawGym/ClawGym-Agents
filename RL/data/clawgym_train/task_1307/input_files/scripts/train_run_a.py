import argparse
import json
from datetime import datetime

# Deterministic toy "training" for run_a (no external deps)
RUN_ID = "run_a"
SEED = 1337
EPOCHS = 5
FINAL_ACC = 0.8421
FINAL_LOSS = 0.5743


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Path to write metrics JSON")
    args = parser.parse_args()

    print(f"Starting {RUN_ID} with seed={SEED}")
    base_loss, base_acc = 0.90, 0.60
    for epoch in range(1, EPOCHS + 1):
        # simple linear schedule toward final metrics for display
        t = epoch / EPOCHS
        loss = round(base_loss * (1 - t) + FINAL_LOSS * t, 4)
        acc = round(base_acc * (1 - t) + FINAL_ACC * t, 4)
        print(f"epoch {epoch}/{EPOCHS}: loss={loss} acc={acc}")

    metrics = {
        "run_id": RUN_ID,
        "seed": SEED,
        "epochs": EPOCHS,
        "accuracy": FINAL_ACC,
        "loss": FINAL_LOSS,
        "finished_at": datetime.utcnow().isoformat() + "Z"
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"Completed {RUN_ID}. Final acc={FINAL_ACC} loss={FINAL_LOSS}. Metrics -> {args.out}")


if __name__ == "__main__":
    main()
