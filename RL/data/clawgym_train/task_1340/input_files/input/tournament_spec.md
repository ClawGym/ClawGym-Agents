MoltRPG Offline Mini-Season — Tournament Spec

Overview
- Mode: offline only. Do not use any online sync, web dashboards, or external services.
- Inputs:
  - input/agents.json — agent names with starting level and starting_credits
  - input/raids.json — raid list with id, name, hp, reward_usdc
- Deliverables to write:
  1) output/season_plan.json
  2) output/ledger.json
  3) output/summary.md

Stat Formulas (derive from level)
- Use flooring (truncate down) after multiplication.
- hp = floor(100 * 1.2^(level - 1))
- atk = floor(10 * 1.15^(level - 1))
- def = floor(5 * 1.1^(level - 1))

Raid Rule
- A raid attempt is a victory if (atk * 2) ≥ raid.hp; otherwise defeat.
- On victory: award exactly reward_usdc credits to the agent.
- On defeat: award 0 credits.

PVP Rules (offline)
- Use the per-engine turn sequence up to 20 rounds max:
  - Each round:
    - player2_hp -= max(1, player1_atk - player2_def)
    - if player2_hp ≤ 0: player1 wins
    - else player1_hp -= max(1, player2_atk - player1_def)
  - Stop when one HP ≤ 0 or after 20 rounds.
- Winner must have remaining HP > 0; loser must have remaining HP ≤ 0.
- Award: PVP victory adds exactly 10 credits to the winner (no other PVP credit changes).

Party Requirement
- Create exactly one party object:
  - leader: must be an agent from input/agents.json
  - members: include at least the leader and one joiner (>= 2 total)
  - Include a minimal invite → join flow (e.g., invites list showing invite sent, then a join event).

Messaging and Notifications
- Messaging: include at least 2 messages related to the party formation or PVP (e.g., type "agent_to_agent").
- Notifications: include at least 2 notifications (e.g., "party_join", "pvp_challenge").

Output Schemas

1) output/season_plan.json must include:
- mode: "offline"
- agents: array of computed agent entries:
  - { "name", "level", "hp", "atk", "def", "starting_credits" }
  - hp/atk/def computed via formulas above
- party: object containing:
  - leader (string, agent name)
  - members (array of agent names, length >= 2)
  - invites (array with at least one invite record)
  - events (array showing at least an invite and a join)
- raids: at least 3 raid attempts. Each entry:
  - raid_id (must exist in input/raids.json)
  - agent (agent name)
  - hp (copied from the referenced raid)
  - reward_usdc (copied from the referenced raid)
  - agent_atk (the attacker’s atk for clarity)
  - result ("victory" or "defeat" by the raid rule)
  - credits_awarded (reward_usdc on victory, 0 on defeat)
- pvp_matches: at least 2 matches. Each entry:
  - player1_name, player2_name (agent names)
  - player1_stats, player2_stats: objects with hp/atk/def matching computed stats
  - rounds: integer in [1, 20]
  - winner: equals one of the players
  - p1_remaining_hp, p2_remaining_hp: integers ensuring winner’s > 0 and loser’s ≤ 0
- messaging: at least 2 messages, each:
  - { "id", "type", "from", "to", "content", "timestamp" }
- notifications: at least 2, each:
  - { "id", "player_id", "type", "data", "timestamp" }

2) output/ledger.json must include:
- balances: object mapping each agent name → final credits
- transactions: array; enumerate only the following:
  - raid victory: +reward_usdc to the agent
  - PVP victory: +10 to the winner
- Balances must equal: starting_credits + sum(raid rewards won) + 10 * (number of PVP wins)

3) output/summary.md must be a short narrative including (case-insensitive) the keywords:
- "offline", "raid", "PVP", "party", "wallet", "notification"

Validation Notes
- Names must match exactly those from input/agents.json.
- All referenced raid ids must exist in input/raids.json and their hp and reward_usdc must match.
- Do not include any other sources of credit changes beyond the rules stated here.