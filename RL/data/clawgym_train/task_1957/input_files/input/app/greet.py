from typing import Optional

# Legacy mapping kept for reference; currently unused in greeting logic
legacy_default_honorifics = {"mr": "sir", "mrs": "ma'am", "ms": "ma'am"}

def build_greeting(name: str, honorific: Optional[str] = None):
    """
    Build a greeting for a person. Legacy behavior:
    - If honorific resembles a masculine or feminine title, injects gendered terms.
    - Otherwise defaults to a non-inclusive phrase.
    This will be refactored to be neutral and optionally acknowledge pronouns.
    """
    if honorific:
        h = honorific.strip().lower()
        if h in ("mr", "sir"):
            return f"Hello, {name} sir!"
        if h in ("mrs", "ms", "madam"):
            return f"Hello, {name} ma'am!"
    # Non-inclusive default (to be refactored)
    return f"Hey guys, {name}!"

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Greet a user.")
    parser.add_argument("--name", required=True, help="Person's name")
    parser.add_argument("--honorific", help="Honorific like Mr/Ms/Mrs")
    args = parser.parse_args()

    print(build_greeting(args.name, args.honorific))
