from app.search import load_books, search_books


def test_case_insensitive_default():
    books = load_books('data/books.json')
    results = search_books('odyssey', books)
    assert any(b['title'] == 'The Odyssey' for b in results)


def test_available_only_filter():
    books = load_books('data/books.json')
    results = search_books('python', books, available_only=True)
    titles = [b['title'] for b in results]
    assert 'Automate the Boring Stuff with Python' in titles
    assert 'Fluent Python' not in titles
