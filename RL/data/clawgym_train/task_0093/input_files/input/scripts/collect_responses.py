import csv

def save_response(record, path="input/data/survey_responses.csv"):
    fieldnames = ["response_id","name","email","age","city","religion_affiliation","political_preference"]
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writerow(record)

# NOTE: This script stores names and email addresses for potential follow-up.

if __name__ == "__main__":
    sample = {"response_id":3,"name":"Sample Student","email":"student@university.edu","age":20,"city":"Lakeview","religion_affiliation":"None","political_preference":"Moderate"}
    save_response(sample)
