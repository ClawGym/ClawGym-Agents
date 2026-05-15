import json
from typing import List, Dict


def load_config(path: str = 'app/config.json') -> Dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_books(path: str = 'data/books.json') -> List[Dict]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def search_books(query: str, books: List[Dict], available_only=None, case_sensitive=None) -> List[Dict]:
    """
    Search books by title or author containing the query. Optional filters:
    - available_only: if None, read from config defaults
    - case_sensitive: if None, read from config defaults
    """
    cfg = load_config()
    if available_only is None:
        available_only = cfg.get('defaults', {}).get('available_only', False)
    if case_sensitive is None:
        case_sensitive = cfg.get('defaults', {}).get('case_sensitive', False)

    q = query if case_sensitive else query.lower()

    results: List[Dict] = []
    for book in books:
        title = book.get('title', '')
        author = book.get('author', '')
        hay_title = title if case_sensitive else title.lower()
        hay_author = author if case_sensitive else author.lower()
        if q in hay_title or q in hay_author:
            if available_only:
                # BUG: compares against string instead of the boolean field stored in data
                if book.get('available') == 'true':
                    results.append(book)
            else:
                results.append(book)
    return results
