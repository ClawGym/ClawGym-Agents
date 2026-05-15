-----
name: searxng
description: Privacy-respecting metasearch using your local SearXNG instance. Search the web, images, news, and more without external API dependencies.
author: Avinash Venkatswamy
version: 1.0.1
homepage: https://searxng.org
triggers:
  - "search for"
  - "search web"
  - "find information"
  - "look up"
metadata: {"clawdbot":{"emoji":"🔍","requires":{"bins":["python3"]},"config":{"env":{"SEARXNG_URL":{"description":"SearXNG instance URL","default":"http://localhost:8080","required":true}}}}}
-----

# SearXNG Search

Search the web using your local SearXNG instance - a privacy-respecting metasearch engine. Supports categories: general, images, videos, news, map, music, files, it, science. Outputs table or JSON. No credentials required; reads SEARXNG_URL from environment.