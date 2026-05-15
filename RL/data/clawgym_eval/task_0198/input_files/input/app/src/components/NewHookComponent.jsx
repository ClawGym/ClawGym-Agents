import React, { useState, useEffect, useMemo } from 'react';

export function NewHookComponent({ items }) {
  const [count, setCount] = useState(0);
  const [query, setQuery] = useState('');
  useEffect(() => {
    document.title = `Count: ${count}`;
    return () => {
      // cleanup
    };
  }, [count]);
  useEffect(() => {
    if (query) {
      console.log('Searching', query);
    }
  }, [query]);
  const filtered = useMemo(() => items.filter(i => i.includes(query)), [items, query]);
  return (
    <div>
      <button onClick={() => setCount(count + 1)}>Inc</button>
      <input value={query} onChange={e => setQuery(e.target.value)} />
      {filtered.map(i => <span key={i}>{i}</span>)}
    </div>
  );
}
