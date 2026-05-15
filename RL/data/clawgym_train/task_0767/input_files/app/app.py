import argparse
import sys
from app import model

try:
    # Optional: present to allow GUI expansion; not required for this task
    from PyQt4 import QtGui  # type: ignore
except Exception:  # pragma: no cover
    QtGui = None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Todo prototype CLI/GUI")
    parser.add_argument("--export", help="Path to CSV to export data model rows")
    args = parser.parse_args(argv)

    if args.export:
        try:
            tasks = model.load_tasks("data/tasks.json")
            n = model.export_csv(tasks, args.export)
            print(f"Exported {n} rows to {args.export}")
            return 0
        except Exception as e:
            print(f"Export failed: {e}", file=sys.stderr)
            return 1

    if QtGui is None:
        print("PyQt4 not available; GUI mode is optional for this prototype. Use --export to validate.")
        return 0

    # Minimal, optional GUI placeholder
    try:
        app = QtGui.QApplication(sys.argv)
        tasks = model.load_tasks("data/tasks.json")
        msg = QtGui.QMessageBox()
        msg.setWindowTitle("Todo Prototype")
        msg.setText(f"Loaded {len(tasks)} tasks. This is a minimal placeholder UI.")
        msg.exec_()
        return 0
    except Exception as e:
        print(f"GUI failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
