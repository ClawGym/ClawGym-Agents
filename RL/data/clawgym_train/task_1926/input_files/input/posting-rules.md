# LiteTrace Community Posting Rules & Guidance

These rules apply to all outreach. They are designed to protect our reputation and ensure value-first engagement.

## Core Rules
1) Value First, Product Second  
   - Provide genuine help (tips, examples, links to docs/tools—even if not ours).  
   - Only mention LiteTrace after addressing the user’s question directly.  
   - Aim for 80% helpful content, 20% product mention.

2) Mandatory Disclosure  
   - Every drafted response must include: “disclaimer: I’m the developer” (or “disclaimer: we built this”).  
   - Do not imply you’re a customer or independent reviewer.

3) No Astroturfing, No Vote-Begging  
   - Do not ask for upvotes, reviews, or favors.  
   - Do not use or create fake or throwaway accounts to simulate community interest.

4) Respect Community Rules  
   - Read subreddit/community rules before posting.  
   - If self-promotion is limited, ensure our comment is primarily educational and not a direct pitch.

5) Target Only Relevant, Recent Threads  
   - Prefer posts < 6 months old with meaningful engagement (comments/points).  
   - Avoid dormant threads and necro-posting.

6) Posting Pace & Etiquette  
   - Max 2 substantive replies per day per community.  
   - Do not cross-post the same comment. Tailor each reply to context.

7) Product Mentions  
   - Keep the mention short and natural. Include the disclosure.  
   - Where possible, link to docs/examples rather than home page.

## Tone Guidance by Community

- Reddit (e.g., r/devops, r/programming, r/golang, r/node)
  - Casual, helpful, and humble.  
  - Use concrete examples, code snippets, or config fragments.  
  - Acknowledge trade-offs and alternatives (e.g., Jaeger, Zipkin, Grafana Tempo).  
  - Avoid corporate tone and buzzwords.

- Hacker News
  - Technical, precise, and data-driven.  
  - Include numbers: install time, overhead, sampling behavior, failure modes.  
  - Be transparent about limitations and roadmap.

- ProductHunt
  - Builder energy with clear story: problem → insight → solution.  
  - Focus on what’s new/different and early user feedback.  
  - Do not solicit votes. Engage with every comment thoughtfully.

## ProductHunt Launch Constraints
- Use the exact tagline in the launch: “Faster distributed tracing without the yak-shave”.
- Prepare a maker comment (story + problem + solution + what’s next).  
- Screenshots/GIFs should show: install in <10 min, Adaptive Burst Sampling, OTLP compatibility.  
- Launch day timing: Tues–Thurs at 00:01 PST is preferred.  
- No mass-DM requests for upvotes. Share progress posts in relevant communities only with context and value.

## Safe Content Pointers
- Good: Explaining when to use head-based vs tail-based sampling, sharing OTLP config snippets, linking to open-source resources (including alternatives).  
- Risky: Directly comparing with FUD, promising “no overhead,” or implying replacements where not appropriate.  
- Forbidden: Fake testimonials, undisclosed affiliations, vote or review requests.

## Quick Examples
- Good Disclosure:  
  “If you want to capture spikes without huge volume, try a baseline rate with a burst trigger on p95 latency. We’ve published a sample config here. We built a tool (LiteTrace) that does this automatically — disclaimer: I’m the developer.”

- Bad (Do Not Do):  
  “We just launched on PH — please upvote!”  
  “This is better than Datadog and Jaeger combined!” (unsubstantiated, inflammatory)

—  
Always default to being helpful, honest, and specific.