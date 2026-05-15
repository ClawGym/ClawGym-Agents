import csv


def load_players():
    # Intentional prototype: expects a CSV that does not exist in this repo
    # to illustrate error handling and format validation needs.
    with open('data/new_players.csv', newline='') as f:
        reader = csv.DictReader(f)
        return list(reader)


def main():
    rows = load_players()
    print(f"Loaded {len(rows)} new players from CSV")


if __name__ == '__main__':
    main()
