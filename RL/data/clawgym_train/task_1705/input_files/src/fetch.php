<?php
/**
 * CacheDemo proof-of-concept.
 * TODO: Add Redis-backed caching. Read config from config/app.json.
 */

function expensiveCompute($key) {
    // Simulate an expensive computation deterministically
    return hash('sha256', "value:".$key);
}

function loadConfig() {
    $path = __DIR__ . '/../config/app.json';
    if (!file_exists($path)) {
        throw new RuntimeException("Missing config at $path");
    }
    $json = file_get_contents($path);
    $cfg = json_decode($json, true);
    if (!is_array($cfg)) {
        throw new RuntimeException("Invalid JSON config");
    }
    return $cfg;
}

// Simple demo function that should use caching
function getValue($key) {
    $cfg = loadConfig();
    $backend = $cfg['cache']['backend'] ?? 'none';
    $ttl = $cfg['cache']['ttl_seconds'] ?? 0;
    $prefix = $cfg['cache']['key_prefix'] ?? 'cache:';

    // TODO: Implement: if backend is 'redis' and Redis extension is available, read/write from Redis.
    // Otherwise, use a local in-memory array fallback for this process.
    // Use a cache key prefix to avoid collisions.
    // When cache miss occurs, compute via expensiveCompute($key), then cache it with TTL.

    // Placeholder: no caching
    return expensiveCompute($key);
}

// Basic CLI test
if (PHP_SAPI === 'cli' && basename(__FILE__) === basename($_SERVER['SCRIPT_FILENAME'])) {
    $key = $argv[1] ?? 'demo';
    $value = getValue($key);
    echo $value . PHP_EOL;
}
